"""Personal dashboard (Individual)

Design goals
- Use session-level aggregation so uploads do not overweight trends.
- Keep the UI calm and scannable: tabs with compact charts (no long scrolling).
- Non-diagnostic language.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Add backend path for imports
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.append(str(backend_path))

from utils.auth import init_auth_service
from utils.auth_sidebar import render_auth_sidebar
from utils.db_client import DBClient
from utils.depression_detection import (
    analyze_depression,
    evaluate_recent_data_requirements,
    prepare_dashboard_data,
    BDI_SYMPTOM_NAMES,
)
from utils.export_utils import df_to_csv_bytes, figs_to_pdf_bytes

# Symptom code to name mapping for AI recommendations
SYMPTOM_NAMES = BDI_SYMPTOM_NAMES
try:
    import importlib
    import model.recommendation as _rec

    if not hasattr(_rec, "generate_self_support_recommendation"):
        _rec = importlib.reload(_rec)

    generate_self_support_recommendation = getattr(_rec, "generate_self_support_recommendation", None)
    if generate_self_support_recommendation is None:
        raise ImportError("generate_self_support_recommendation not found")

    _RECOMMENDER_AVAILABLE = True
except Exception as e:
    generate_self_support_recommendation = None
    _RECOMMENDER_IMPORT_ERROR = str(e)


if _RECOMMENDER_AVAILABLE:
    @st.cache_data(ttl=3600, show_spinner=False)
    def _cached_self_recommendation(symptoms_json: str, overall_severity: str, trend_direction: str) -> str:
        top_symptoms = json.loads(symptoms_json)
        return generate_self_support_recommendation(
            overall_severity=overall_severity,
            trend_direction=trend_direction,
            top_symptoms=top_symptoms,
            model_name="gemma-3-27b-it",
        )
else:
    def _cached_self_recommendation(symptoms_json: str, overall_severity: str, trend_direction: str) -> str:
        return ""


def _safe_mode(values: pd.Series, default: str = "Neutral") -> str:
    try:
        m = values.dropna().mode()
        if m is None or m.empty:
            return default
        if len(m) > 1 and default in set(m.astype(str).tolist()):
            return default
        return str(m.iloc[0])
    except Exception:
        return default


def _view_options() -> list[str]:
    return [
        "Last 30 days",
        "Last 60 days",
        "Last 90 days",
        "All time",
    ]


def _view_to_days(view_label: str) -> Optional[int]:
    mapping = {
        "Last 30 days": 30,
        "Last 60 days": 60,
        "Last 90 days": 90,
        "All time": None,
    }
    return mapping.get(str(view_label), 30)


def _label_severity(score: float) -> str:
    if pd.isna(score):
        return "Doing great"
    if score < 10:
        return "Doing great"
    if score < 19:
        return "Hazy"
    if score < 30:
        return "Foggy"
    return "Dense Fog"


def _severity_caption(label: str) -> str:
    label = str(label)
    captions = {
        "Doing great": "This is a wonderful time to lean into the habits, hobbies, and connections that help you feel grounded and balanced.",
        "Hazy": "Things feel a little blurred or out of focus this week. Moving at a gentler pace and being kind to yourself will help you navigate the mist.",
        "Foggy": "Your mind feels a bit crowded and heavy. Remember, fog always lifts eventually—for now, just focus on taking one small, careful step at a time.",
        "Dense Fog": "Visibility feels very low right now. It is okay to stop, rest, and let someone you trust help you find the way until the air clears again.",
    }
    return captions.get(label, "")


def _parse_uploaded_file_timestamp(uploaded_file: object) -> Optional[datetime]:
    if not isinstance(uploaded_file, str) or "_" not in uploaded_file:
        return None
    try:
        ts = uploaded_file[-15:]  # YYYYMMDD_HHMMSS
        return datetime.strptime(ts, "%Y%m%d_%H%M%S")
    except Exception:
        return None


def _extract_symptom_scores(assessment_data: object) -> dict[str, float]:
    if not isinstance(assessment_data, dict) or not assessment_data:
        return {}

    scores: dict[str, float] = {}
    for key, val in assessment_data.items():
        score = None
        if isinstance(val, dict):
            for possible_key in ["level", "score", "value"]:
                if possible_key in val and isinstance(val[possible_key], (int, float)):
                    score = float(val[possible_key])
                    break
        elif isinstance(val, (int, float)):
            score = float(val)

        if score is None:
            continue
        if 0 <= score <= 3:
            scores[str(key)] = score

    return scores


def _build_session_df(entry_df: pd.DataFrame) -> pd.DataFrame:
    """Collapse uploads to one row per uploaded_file; typed entries remain 1 row each."""
    if entry_df is None or entry_df.empty:
        return pd.DataFrame()

    work = entry_df.copy()
    if "entry_type" not in work.columns:
        work["entry_type"] = "by_typing"
    if "uploaded_file" not in work.columns:
        work["uploaded_file"] = None
    if "entry_id" not in work.columns:
        work["entry_id"] = None

    work["datetime"] = pd.to_datetime(work["datetime"], errors="coerce")
    work = work.dropna(subset=["datetime"]).copy()
    if work.empty:
        return pd.DataFrame()

    # Typed sessions: one per row
    typed = work[work["entry_type"] != "by_upload"].copy()
    typed["session_type"] = "typed"
    typed["session_id"] = typed["entry_id"].astype(str)

    # Upload sessions: one per uploaded_file
    uploads = work[work["entry_type"] == "by_upload"].copy()
    upload_rows: list[dict] = []

    if not uploads.empty:
        for file_key, g in uploads.groupby("uploaded_file", dropna=True):
            if not isinstance(file_key, str) or not file_key:
                continue

            session_dt = _parse_uploaded_file_timestamp(file_key)
            if session_dt is None:
                try:
                    session_dt = pd.to_datetime(g["datetime"], errors="coerce").max()
                    if pd.isna(session_dt):
                        session_dt = None
                except Exception:
                    session_dt = None

            if session_dt is None:
                continue

            bdi_scores = pd.to_numeric(g.get("bdi_total_score"), errors="coerce").dropna()
            avg_bdi = float(bdi_scores.mean()) if not bdi_scores.empty else float("nan")
            sev = _label_severity(avg_bdi)

            sent = _safe_mode(g.get("sentiment_label"), default="Neutral")
            if sent not in {"Positive", "Neutral", "Negative"}:
                sent = "Neutral"

            # Average symptoms across messages in file
            symptom_sum: dict[str, float] = {}
            symptom_count: dict[str, int] = {}
            for _, r in g.iterrows():
                scores = _extract_symptom_scores(r.get("assessment_data"))
                for k, v in scores.items():
                    symptom_sum[k] = symptom_sum.get(k, 0.0) + float(v)
                    symptom_count[k] = symptom_count.get(k, 0) + 1

            agg_assessment: dict[str, float] = {}
            for k in symptom_sum:
                c = symptom_count.get(k, 0)
                if c > 0:
                    agg_assessment[k] = symptom_sum[k] / c

            upload_rows.append(
                {
                    "entry_id": None,
                    "entry_type": "by_upload",
                    "uploaded_file": file_key,
                    "datetime": session_dt,
                    "bdi_total_score": avg_bdi,
                    "bdi_severity": sev,
                    "assessment_data": agg_assessment,
                    "sentiment_label": sent,
                    "text": "",
                    "session_type": "upload",
                    "session_id": file_key,
                }
            )

    uploads_sessions = pd.DataFrame(upload_rows) if upload_rows else pd.DataFrame()
    sessions = pd.concat([typed, uploads_sessions], ignore_index=True)
    sessions["datetime"] = pd.to_datetime(sessions["datetime"], errors="coerce")
    sessions = sessions.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    return sessions


def _build_daily_df(df_sessions: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sessions to one row per calendar day.

    This is used for charts/weekly summaries so uploads that span many days
    don't collapse into a single dot.

    Weighting rule: each session contributes equally within a day.
    """
    if df_sessions is None or df_sessions.empty:
        return pd.DataFrame()

    work = df_sessions.copy()
    work["datetime"] = pd.to_datetime(work["datetime"], errors="coerce")
    work = work.dropna(subset=["datetime"]).copy()
    if work.empty:
        return pd.DataFrame()

    work["date"] = work["datetime"].dt.date

    rows: list[dict] = []
    for day, g in work.groupby("date"):
        day_dt = pd.Timestamp(day)

        bdi_scores = pd.to_numeric(g.get("bdi_total_score"), errors="coerce").dropna()
        avg_bdi = float(bdi_scores.mean()) if not bdi_scores.empty else float("nan")
        sev = _label_severity(avg_bdi)

        sent = _safe_mode(g.get("sentiment_label"), default="Neutral")
        if sent not in {"Positive", "Neutral", "Negative"}:
            sent = "Neutral"

        symptom_sum: dict[str, float] = {}
        symptom_count: dict[str, int] = {}
        for _, r in g.iterrows():
            scores = _extract_symptom_scores(r.get("assessment_data"))
            for k, v in scores.items():
                symptom_sum[k] = symptom_sum.get(k, 0.0) + float(v)
                symptom_count[k] = symptom_count.get(k, 0) + 1

        agg_assessment: dict[str, float] = {}
        for k in symptom_sum:
            c = symptom_count.get(k, 0)
            if c > 0:
                agg_assessment[k] = symptom_sum[k] / c

        rows.append(
            {
                "date": day,
                "datetime": day_dt,
                "bdi_total_score": avg_bdi,
                "bdi_severity": sev,
                "sentiment_label": sent,
                "assessment_data": agg_assessment,
                "sessions": int(len(g)),
            }
        )

    out = pd.DataFrame(rows)
    out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
    out = out.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    return out


def _sessions_in_last_days(df_sessions: pd.DataFrame, days: int) -> pd.DataFrame:
    cutoff = datetime.now() - timedelta(days=days)
    return df_sessions[df_sessions["datetime"] >= cutoff].copy()


def _weekly_summary(df_sessions: pd.DataFrame) -> pd.DataFrame:
    if df_sessions is None or df_sessions.empty:
        return pd.DataFrame()

    work = df_sessions.copy()
    work["week"] = work["datetime"].dt.to_period("W").apply(lambda p: p.start_time)
    out = (
        work.groupby("week")
        .agg(
            avg_bdi=("bdi_total_score", "mean"),
            days=("datetime", "count"),
        )
        .reset_index()
        .sort_values("week")
    )
    out["severity"] = out["avg_bdi"].apply(_label_severity)
    return out


def _weekly_sentiment(df_sessions: pd.DataFrame) -> pd.DataFrame:
    if df_sessions is None or df_sessions.empty:
        return pd.DataFrame()

    work = df_sessions.copy()
    work["week"] = work["datetime"].dt.to_period("W").apply(lambda p: p.start_time)
    c = work.groupby(["week", "sentiment_label"]).size().reset_index(name="count")

    # Ensure consistent order
    for lbl in ["Positive", "Neutral", "Negative"]:
        if lbl not in set(c["sentiment_label"].astype(str).tolist()):
            c = pd.concat([c, pd.DataFrame([{ "week": c["week"].min() if not c.empty else datetime.now(), "sentiment_label": lbl, "count": 0 }])], ignore_index=True)

    return c


# -----------------------------
# PAGE CONFIG
# -----------------------------
st.set_page_config(
    page_title="Personal Dashboard",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------
# AUTH
# -----------------------------
auth_service = init_auth_service()
render_auth_sidebar(auth_service)
auth_service.require_role(["individual"])

current_user = auth_service.get_current_user()
if not current_user:
    st.error("Authentication required")
    st.stop()

user_profile = auth_service.get_user_profile()
user_id = current_user["id"]
db_client = DBClient(user_id=user_id)

user_name = user_profile.get("name", "User") if isinstance(user_profile, dict) else "User"

# -----------------------------
# LOAD + AGGREGATE DATA
# -----------------------------
with st.spinner("Loading your insights..."):
    entry_df = prepare_dashboard_data(db_client, window_days=90)

if entry_df is None or entry_df.empty:
    st.info("👋 Welcome! Add a few entries to unlock insights.")
    st.stop()

session_df = _build_session_df(entry_df)
if session_df.empty:
    st.info("👋 Welcome! We need a few more analyzed entries to show insights.")
    st.stop()

# Gate based on sessions (not messages)
req = evaluate_recent_data_requirements(session_df, window_days=30, min_entries=10, min_distinct_days=5)
if not req.get("meets", False):
    st.warning(req.get("message", "Not enough recent sessions to show the dashboard yet."))
    st.stop()

analysis_30 = analyze_depression(session_df, window_days=30)

support_mode_on = bool(analysis_30.get("depression_detected", False))

# For PDF export (populated if AI suggestions are generated)
ai_recommendation_text = ""

# -----------------------------
# HEADER
# -----------------------------
st.title("🌿 Personal Well-being Dashboard")
st.caption("A calm summary of patterns across your sessions. Not a diagnosis.")

# Global chart filter (affects all charts across tabs)
global_chart_view = st.selectbox(
    "📅 Choose your view:",
    options=_view_options(),
    index=1,
    key=f"pd_global_view_{user_id}",
)
global_chart_days = _view_to_days(global_chart_view)
global_session_df = session_df.copy() if global_chart_days is None else _sessions_in_last_days(session_df, int(global_chart_days))
global_daily_df = _build_daily_df(global_session_df)

# Tabs: keep each tab compact to avoid scrolling
overview_tab, trends_tab, patterns_tab, support_tab = st.tabs([
    "Overview",
    "Trends",
    "Patterns",
    "Support & Export",
])

# -----------------------------
# OVERVIEW TAB
# -----------------------------
with overview_tab:
    # Metrics based on the selected global view
    selected_period_mood = _safe_mode(global_session_df.get("sentiment_label"), default="Neutral") if not global_session_df.empty else "N/A"
    mood_emoji = {"Positive": "😊", "Neutral": "😐", "Negative": "😔", "N/A": "⚪"}.get(selected_period_mood, "⚪")
    selected_period_level = _label_severity(float(global_session_df["bdi_total_score"].mean())) if not global_session_df.empty else "Clear"

    # First row: outlook with caption beside
    col_outlook, col_caption = st.columns([1, 3])
    with col_outlook:
        st.metric(f"{global_chart_view} emotional outlook", selected_period_level)
    with col_caption:
        cap = _severity_caption(selected_period_level)
        if cap:
            st.caption(cap)

    # Second row: mood, active days, support
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(f"{global_chart_view} mood", mood_emoji)
    with col2:
        st.metric(f"{global_chart_view} active days", int(len(global_daily_df)))
    with col3:
        st.metric("More support suggested", "Yes" if support_mode_on else "No")

    # Distress score over time (recent sessions)
    st.subheader("Distress score over time")
    if global_daily_df.empty:
        st.info("No data in the recent period.")
    else:
        fig_bdi = go.Figure()
        fig_bdi.add_trace(go.Scatter(
            x=global_daily_df["datetime"],
            y=global_daily_df["bdi_total_score"],
            mode="lines+markers",
            line=dict(color="#2E86C1", width=3, shape="spline"),
            marker=dict(size=6),
            showlegend=False,
        ))
        fig_bdi.update_layout(
            height=320,
            template="plotly_white",
            margin=dict(l=20, r=20, t=10, b=10),
            yaxis=dict(title="Distress score", range=[0, 63]),
            xaxis=dict(title=""),
        )
        st.plotly_chart(fig_bdi, width="stretch", key=f"pd_trend_line_{user_id}")

    # Next step: gentle and actionable
    if analysis_30.get("trend_direction") == "Worsening":
        st.info("Next step: Try a short check-in today (3–5 minutes). Write one thing you can do to support yourself this evening.")
    else:
        st.info("Next step: Keep your streak going. Write one small win from today (even if it’s tiny).")


# -----------------------------
# TRENDS TAB
# -----------------------------
with trends_tab:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Weekly mood mix")
        w_sent = _weekly_sentiment(global_session_df)
        if w_sent.empty:
            st.info("No mood data yet.")
        else:
            w_sent = w_sent.copy()
            w_sent["mood"] = w_sent["sentiment_label"].map(
                {
                    "Positive": "Feeling good",
                    "Neutral": "Neutral",
                    "Negative": "Feeling low",
                }
            ).fillna(w_sent["sentiment_label"].astype(str))
            # Calculate percentages for 100% stacked bar
            total_per_week = w_sent.groupby("week")["count"].sum().reset_index(name="total")
            w_sent = w_sent.merge(total_per_week, on="week")
            w_sent["percentage"] = (w_sent["count"] / w_sent["total"]) * 100
            fig_s = px.bar(
                w_sent,
                x="week",
                y="percentage",
                color="mood",
                barmode="stack",
                color_discrete_map={
                    "Feeling good": "lightblue",
                    "Neutral": "gray",
                    "Feeling low": "orange",
                },
                labels={"week": "", "percentage": "Percentage (%)", "mood": "Mood"},
            )
            fig_s.update_layout(
                height=320,
                template="plotly_white",
                margin=dict(l=20, r=20, t=10, b=10),
                legend_title_text="",
            )
            st.plotly_chart(fig_s, width="stretch", key=f"pd_weekly_sent_{user_id}")

    with col2:
        # Weekly distress trend
        w = _weekly_summary(global_daily_df)
        st.subheader("Weekly distress trend")
        if w.empty:
            st.info("No weekly data yet.")
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=w["week"],
                y=w["avg_bdi"],
                mode="lines+markers",
                line=dict(color="#2E86C1", width=3, shape="spline"),
                marker=dict(size=6),
                showlegend=False,
            ))
            fig.update_layout(
                height=280,
                template="plotly_white",
                margin=dict(l=20, r=20, t=10, b=10),
                yaxis=dict(title="Avg distress score", range=[0, 63]),
                xaxis=dict(title=""),
            )
            st.plotly_chart(fig, width="stretch", key=f"pd_weekly_{user_id}")


# -----------------------------
# PATTERNS TAB
# -----------------------------
with patterns_tab:
    st.caption("These are neutral patterns (not judgments). Use them to plan gentle support.")

    # Day-level patterns use daily averages.
    dfp = global_daily_df.copy()
    dfp["weekday"] = dfp["datetime"].dt.day_name()

    # Time-of-day patterns require session timestamps.
    dfp_time = global_session_df.copy()
    dfp_time["hour"] = dfp_time["datetime"].dt.hour

    # Time-of-day bucket
    def _bucket(h: int) -> str:
        if 5 <= h < 12:
            return "Morning"
        if 12 <= h < 17:
            return "Afternoon"
        if 17 <= h < 22:
            return "Evening"
        return "Night"

    dfp_time["tod"] = dfp_time["hour"].apply(lambda h: _bucket(int(h)) if not pd.isna(h) else "Unknown")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Day of week")
        try:
            d = dfp.groupby("weekday")["bdi_total_score"].mean().reset_index(name="avg_score")
            order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            d["weekday"] = pd.Categorical(d["weekday"], categories=order, ordered=True)
            d = d.sort_values("weekday")
            fig = px.bar(d, x="weekday", y="avg_score", labels={"weekday": "", "avg_score": "Avg distress score"}, color_discrete_sequence=["#2E86C1"])
            fig.update_layout(height=280, template="plotly_white", margin=dict(l=20, r=20, t=10, b=10))
            st.plotly_chart(fig, width="stretch", key=f"pd_wd_{user_id}")
        except Exception:
            st.info("Day-of-week chart unavailable.")

    with col_b:
        st.subheader("Time of day")
        try:
            t = dfp_time.groupby("tod")["bdi_total_score"].mean().reset_index(name="avg_score")
            order = ["Morning", "Afternoon", "Evening", "Night", "Unknown"]
            t["tod"] = pd.Categorical(t["tod"], categories=order, ordered=True)
            t = t.sort_values("tod")
            fig = px.bar(t, x="tod", y="avg_score", labels={"tod": "", "avg_score": "Avg distress score"}, color_discrete_sequence=["#2E86C1"])
            fig.update_layout(height=280, template="plotly_white", margin=dict(l=20, r=20, t=10, b=10))
            st.plotly_chart(fig, width="stretch", key=f"pd_tod_{user_id}")
        except Exception:
            st.info("Time-of-day chart unavailable.")


# -----------------------------
# SUPPORT TAB
# -----------------------------
with support_tab:
    if analysis_30.get("depression_detected", False):
        st.subheader("AI Support suggestions")
        st.caption("Not a diagnosis or medical advice.")

        if not _RECOMMENDER_AVAILABLE:
            msg = "Support suggestions are unavailable right now."
            if _RECOMMENDER_IMPORT_ERROR:
                msg += f"\n\nDetails: {_RECOMMENDER_IMPORT_ERROR}"
            st.info(msg)
        else:
            # Build a simple symptom payload: top symptoms by average score in recent window
            recent_df = _sessions_in_last_days(session_df, 30)
            symptom_sum: dict[str, float] = {}
            symptom_count: dict[str, int] = {}
            for _, r in recent_df.iterrows():
                scores = _extract_symptom_scores(r.get("assessment_data"))
                for k, v in scores.items():
                    symptom_sum[k] = symptom_sum.get(k, 0.0) + float(v)
                    symptom_count[k] = symptom_count.get(k, 0) + 1

            avgs = []
            for k in symptom_sum:
                c = symptom_count.get(k, 0)
                if c > 0:
                    symptom_name = SYMPTOM_NAMES.get(k, k)  # Use name if available, else keep code
                    avgs.append({"symptom": symptom_name, "average_score": symptom_sum[k] / c, "entries_count": c})

            avgs = sorted(avgs, key=lambda x: x["average_score"], reverse=True)[:5]
            if not avgs:
                st.info("No symptom data available to summarize.")
            else:
                symptoms_json = json.dumps(avgs, ensure_ascii=False)
                with st.spinner("Generating support suggestions..."):
                    text = _cached_self_recommendation(
                        symptoms_json,
                        str(analysis_30.get("overall_severity", "Minimal")),
                        str(analysis_30.get("trend_direction", "Stable")),
                    )
                if text:
                    ai_recommendation_text = text
                    st.write(text)

        st.info("💛 If you feel overwhelmed, consider reaching out to someone you trust or a professional.")
    else:
        st.info("🌱 You’re doing great. Small, consistent check-ins can be powerful.")

    st.divider()

    # -----------------------------
    # EXPORT (CSV + PDF)
    # -----------------------------
    st.subheader("📥 Export")
    export_col1, export_col2 = st.columns([1, 1])

    with export_col1:
        # CSV Export (message-level rows for the selected view)
        try:
            # Use entry_df for message-level export, filter to selected period
            export_df = entry_df.copy()
            if global_chart_days is not None:
                cutoff = datetime.now() - timedelta(days=global_chart_days)
                export_df = export_df[export_df["datetime"] >= cutoff].copy()
            if export_df is None or export_df.empty:
                st.info("No data available to export for the selected view.")
            else:
                # Add bdi_severity if not present
                if "bdi_severity" not in export_df.columns and "bdi_total_score" in export_df.columns:
                    export_df["bdi_severity"] = export_df["bdi_total_score"].apply(_label_severity)
                
                cols = [
                    "datetime",
                    "bdi_severity",
                    "sentiment_label",
                ]
                if "uploaded_file" in export_df.columns:
                    cols.append("uploaded_file")
                csv_df = export_df[cols].copy() if cols else export_df.copy()
                # Rename uploaded_file to file_name for clarity
                if "uploaded_file" in csv_df.columns:
                    csv_df = csv_df.rename(columns={"uploaded_file": "file_name"})
                    # Split file_name into name and uploaded datetime
                    csv_df["file_name_clean"] = csv_df["file_name"].apply(lambda x: x.rsplit('_', 2)[0] if isinstance(x, str) and '_' in x else x)
                    csv_df["file_uploaded_datetime"] = csv_df["file_name"].apply(lambda x: '_'.join(x.rsplit('_', 2)[1:]) if isinstance(x, str) and '_' in x and len(x.rsplit('_', 2)) > 2 else '')
                    # Format the datetime
                    csv_df["file_uploaded_datetime"] = csv_df["file_uploaded_datetime"].apply(lambda x: datetime.strptime(x, '%Y%m%d_%H%M%S').strftime('%d-%m-%Y %I:%M:%S %p') if x else '')
                    # Replace file_name with the clean name
                    csv_df["file_name"] = csv_df["file_name_clean"]
                    csv_df = csv_df.drop(columns=["file_name_clean"])
                if "datetime" in csv_df.columns:
                    csv_df["datetime"] = pd.to_datetime(csv_df["datetime"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")

                csv_bytes = df_to_csv_bytes(csv_df)
                if csv_bytes:
                    st.download_button(
                        label="📄 Download CSV",
                        data=csv_bytes,
                        file_name=f"personal_dashboard_{user_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        width="stretch",
                    )
        except Exception as e:
            st.error(f"CSV export error: {e}")

    with export_col2:
        # PDF Export (figures + key metrics from all tabs)
        try:
            if global_daily_df is None or global_daily_df.empty:
                st.info("No data available for PDF report.")
            else:
                collected_figs = []

                # Overview: Distress score over time
                fig_bdi_export = go.Figure()
                fig_bdi_export.add_trace(
                    go.Scatter(
                        x=global_daily_df["datetime"],
                        y=global_daily_df["bdi_total_score"],
                        mode="lines+markers",
                        line=dict(color="#2E86C1", width=3, shape="spline"),
                        marker=dict(size=6),
                        showlegend=False,
                    )
                )
                fig_bdi_export.update_layout(
                    height=320,
                    template="plotly_white",
                    margin=dict(l=20, r=20, t=10, b=10),
                    yaxis=dict(title="Distress score", range=[0, 63]),
                    xaxis=dict(title=""),
                )
                collected_figs.append({"fig": fig_bdi_export, "title": "Distress score over time"})

                # Trends: Weekly mood mix
                w_sent_export = _weekly_sentiment(global_session_df)
                if w_sent_export is not None and not w_sent_export.empty:
                    w_sent_export = w_sent_export.copy()
                    w_sent_export["mood"] = w_sent_export["sentiment_label"].map(
                        {
                            "Positive": "Feeling good",
                            "Neutral": "Neutral",
                            "Negative": "Feeling low",
                        }
                    ).fillna(w_sent_export["sentiment_label"].astype(str))
                    # Calculate percentages for 100% stacked bar
                    total_per_week_export = w_sent_export.groupby("week")["count"].sum().reset_index(name="total")
                    w_sent_export = w_sent_export.merge(total_per_week_export, on="week")
                    w_sent_export["percentage"] = (w_sent_export["count"] / w_sent_export["total"]) * 100
                    fig_mood_export = px.bar(
                        w_sent_export,
                        x="week",
                        y="percentage",
                        color="mood",
                        barmode="stack",
                        color_discrete_map={
                            "Feeling good": "lightblue",
                            "Neutral": "gray",
                            "Feeling low": "orange",
                        },
                        labels={"week": "", "percentage": "Percentage (%)", "mood": "Mood"},
                    )
                    fig_mood_export.update_layout(
                        height=320,
                        template="plotly_white",
                        margin=dict(l=20, r=20, t=10, b=10),
                        legend_title_text="",
                    )
                    collected_figs.append({"fig": fig_mood_export, "title": "Weekly mood mix"})

                # Trends: Weekly distress trend
                w_export = _weekly_summary(global_daily_df)
                if w_export is not None and not w_export.empty:
                    fig_weekly_export = go.Figure()
                    fig_weekly_export.add_trace(
                        go.Scatter(
                            x=w_export["week"],
                            y=w_export["avg_bdi"],
                            mode="lines+markers",
                            line=dict(color="#2E86C1", width=3, shape="spline"),
                            marker=dict(size=6),
                            showlegend=False,
                        )
                    )
                    fig_weekly_export.update_layout(
                        height=280,
                        template="plotly_white",
                        margin=dict(l=20, r=20, t=10, b=10),
                        yaxis=dict(title="Avg distress score", range=[0, 63]),
                        xaxis=dict(title=""),
                    )
                    collected_figs.append({"fig": fig_weekly_export, "title": "Weekly distress trend"})

                # Patterns: Day of week + Time of day
                dfp_export = global_daily_df.copy()
                dfp_export["weekday"] = dfp_export["datetime"].dt.day_name()

                dfp_time_export = global_session_df.copy()
                dfp_time_export["hour"] = dfp_time_export["datetime"].dt.hour

                def _bucket(h: int) -> str:
                    if 5 <= h < 12:
                        return "Morning"
                    if 12 <= h < 17:
                        return "Afternoon"
                    if 17 <= h < 22:
                        return "Evening"
                    return "Night"

                dfp_time_export["tod"] = dfp_time_export["hour"].apply(lambda h: _bucket(int(h)) if not pd.isna(h) else "Unknown")

                try:
                    d = dfp_export.groupby("weekday")["bdi_total_score"].mean().reset_index(name="avg_score")
                    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                    d["weekday"] = pd.Categorical(d["weekday"], categories=order, ordered=True)
                    d = d.sort_values("weekday")
                    fig_dow_export = px.bar(
                        d,
                        x="weekday",
                        y="avg_score",
                        labels={"weekday": "", "avg_score": "Avg distress score"},
                        color_discrete_sequence=["#2E86C1"],
                    )
                    fig_dow_export.update_layout(height=280, template="plotly_white", margin=dict(l=20, r=20, t=10, b=10))
                    collected_figs.append({"fig": fig_dow_export, "title": "Day of week"})
                except Exception:
                    pass

                try:
                    t = dfp_time_export.groupby("tod")["bdi_total_score"].mean().reset_index(name="avg_score")
                    order = ["Morning", "Afternoon", "Evening", "Night", "Unknown"]
                    t["tod"] = pd.Categorical(t["tod"], categories=order, ordered=True)
                    t = t.sort_values("tod")
                    fig_tod_export = px.bar(
                        t,
                        x="tod",
                        y="avg_score",
                        labels={"tod": "", "avg_score": "Avg distress score"},
                        color_discrete_sequence=["#2E86C1"],
                    )
                    fig_tod_export.update_layout(height=280, template="plotly_white", margin=dict(l=20, r=20, t=10, b=10))
                    collected_figs.append({"fig": fig_tod_export, "title": "Time of day"})
                except Exception:
                    pass

                if not collected_figs:
                    st.info("No charts available for PDF report.")
                else:
                    with st.spinner("Preparing PDF report..."):
                        generation_time = datetime.now().strftime("%B %d, %Y at %I:%M %p")
                        pdf_title = f"Personal Dashboard Report - {user_name} (Generated on {generation_time})"

                        selected_period_mood_pdf = _safe_mode(global_session_df.get("sentiment_label"), default="Neutral") if not global_session_df.empty else "N/A"
                        selected_period_level_pdf = _label_severity(float(global_session_df["bdi_total_score"].mean())) if not global_session_df.empty else "Clear"

                        metrics = {
                            "Chart range": str(global_chart_view),
                            f"{global_chart_view} outlook": str(selected_period_level_pdf),
                            f"{global_chart_view} outlook details": _severity_caption(selected_period_level_pdf),
                            f"{global_chart_view} active days": str(int(len(global_daily_df))),
                            "More support suggested": "Yes" if support_mode_on else "No",
                            f"{global_chart_view} mood": "Feeling good" if selected_period_mood_pdf == "Positive" else ("Feeling low" if selected_period_mood_pdf == "Negative" else str(selected_period_mood_pdf)),
                        }

                        status_text = "More support suggested" if support_mode_on else "No extra support suggested"
                        guidance = "If you feel overwhelmed, consider reaching out to someone you trust or a professional." if support_mode_on else "You’re doing great. Small, consistent check-ins can be powerful."

                        pdf_bytes = figs_to_pdf_bytes(
                            collected_figs,
                            title=pdf_title,
                            status_text=status_text,
                            metrics=metrics,
                            guidance=guidance,
                            ai_recommendation=ai_recommendation_text,
                        )

                    if pdf_bytes:
                        st.download_button(
                            label="📊 Download PDF Report",
                            data=pdf_bytes,
                            file_name=f"personal_dashboard_report_{user_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                            mime="application/pdf",
                            width="stretch",
                        )
        except ImportError as ie:
            st.error(str(ie))
        except Exception as e:
            st.error(f"PDF export error: {e}")
        

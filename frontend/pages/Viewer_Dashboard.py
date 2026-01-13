"""
Viewer Dashboard - For parents, friends, and staff to view linked users' scores
Does NOT show journal text, only assessments and trends
"""

import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import json
import sys
import io
from pathlib import Path

# Add wordcloud imports
try:
    from wordcloud import WordCloud
    import matplotlib.pyplot as plt
    WORDCLOUD_AVAILABLE = True
except ImportError:
    WORDCLOUD_AVAILABLE = False

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

# Add backend path for imports (same pattern as Journal/My History)
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.append(str(backend_path))

from utils.auth import init_auth_service
from utils.user_service import UserService
from utils.auth_sidebar import render_auth_sidebar
from utils.db_client import DBClient
from utils.depression_detection import analyze_depression, prepare_dashboard_data, BDI_SYMPTOM_NAMES, evaluate_recent_data_requirements
from utils.export_utils import df_to_csv_bytes, figs_to_pdf_bytes

# Backend prompt/model logic lives in backend/model
_RECOMMENDER_IMPORT_ERROR = None
try:
    from model.recommendation import generate_support_recommendation
    _RECOMMENDER_AVAILABLE = True
except Exception as e:
    generate_support_recommendation = None
    _RECOMMENDER_AVAILABLE = False
    _RECOMMENDER_IMPORT_ERROR = str(e)

# Sentiment colours: blue for positive, orange for negative, grey for neutral
POSITIVE_COLOR = '#1f77b4'
NEGATIVE_COLOR = '#ff7f0e'
NEUTRAL_COLOR = '#7f7f7f'

# Page config
st.set_page_config(
    page_title="Analysis Details",
    page_icon="🎯",
    layout="wide"
)

# Initialize services
auth_service = init_auth_service()

# Get current viewer (must be authenticated)
viewer = auth_service.get_current_user()
if not viewer:
    st.error("Authentication required")
    st.stop()

# Initialize DBClient with viewer's user_id
db_client = DBClient(user_id=viewer['id'])
user_service = UserService(db_client.supabase)

# Render auth sidebar
render_auth_sidebar(auth_service)

# Require authentication and viewer role
auth_service.require_auth()
auth_service.require_role(['viewer'])

# Get viewer profile
viewer_profile = auth_service.get_user_profile()

st.title("🎯 Analysis Details")
st.write(f"Welcome, **{viewer_profile.get('name', 'Viewer')}**")
st.caption("View detailed mental health analysis for a specific user.")

# Get linked users
with st.spinner("Loading linked users..."):
    linked_users = user_service.get_linked_users_for_viewer(viewer['id'])

if not linked_users:
    st.info("ℹ️ No users are currently linked to your account.")
    st.write("""
    **How to get access:**
    - Individual users can share their data with you through their Settings page
    """)
    st.stop()

# Cached AI recommendation function (defined at module level for reuse in PDF export)
if _RECOMMENDER_AVAILABLE:
    @st.cache_data(ttl=3600, show_spinner=False)
    def _cached_recommendation(symptoms_json: str, overall_severity: str, trend_direction: str) -> str:
        # Use the requested model name explicitly
        top_symptoms = json.loads(symptoms_json)
        return generate_support_recommendation(
            overall_severity=overall_severity,
            trend_direction=trend_direction,
            top_symptoms=top_symptoms,
            model_name='gemma-3-27b-it',
        )
else:
    def _cached_recommendation(symptoms_json: str, overall_severity: str, trend_direction: str) -> str:
        return ""


def _render_user_analysis(user: dict, user_df: pd.DataFrame) -> None:
    """Render an individual user's dashboard in the same layout as Institution_Dashboard.

    Notes:
    - Viewer dashboards must not show raw journal text.
    - Uses session-level aggregation so uploads do not overweight charts.
    """

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
        return ["Last 30 days", "Last 60 days", "Last 90 days", "All time"]

    def _view_to_days(view_label: str):
        mapping = {
            "Last 30 days": 30,
            "Last 60 days": 60,
            "Last 90 days": 90,
            "All time": None,
        }
        return mapping.get(str(view_label), 30)

    def _label_severity(score: float) -> str:
        if pd.isna(score):
            return "N/A"
        if score < 10:
            return "Minimal"
        if score < 19:
            return "Mild"
        if score < 30:
            return "Moderate"
        return "Severe"

    def _extract_symptom_scores(assessment_data: object) -> dict:
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

    def _parse_uploaded_file_timestamp(uploaded_file: object):
        if not isinstance(uploaded_file, str) or "_" not in uploaded_file:
            return None
        try:
            ts = uploaded_file[-15:]
            return datetime.strptime(ts, "%Y%m%d_%H%M%S")
        except Exception:
            return None

    def _build_session_df(entry_df: pd.DataFrame) -> pd.DataFrame:
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

        typed = work[work["entry_type"] != "by_upload"].copy()
        typed["session_type"] = "typed"
        typed["session_id"] = typed["entry_id"].astype(str)

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

            rows.append(
                {
                    "date": day,
                    "datetime": day_dt,
                    "bdi_total_score": avg_bdi,
                    "bdi_severity": sev,
                    "sentiment_label": sent,
                    "sessions": int(len(g)),
                }
            )

        out = pd.DataFrame(rows)
        out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
        out = out.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
        return out

    def _weekly_sentiment(df_sessions: pd.DataFrame) -> pd.DataFrame:
        if df_sessions is None or df_sessions.empty:
            return pd.DataFrame()
        work = df_sessions.copy()
        work["week"] = work["datetime"].dt.to_period("W").apply(lambda p: p.start_time)
        c = work.groupby(["week", "sentiment_label"]).size().reset_index(name="count")
        for lbl in ["Positive", "Neutral", "Negative"]:
            if lbl not in set(c["sentiment_label"].astype(str).tolist()):
                c = pd.concat(
                    [
                        c,
                        pd.DataFrame(
                            [
                                {
                                    "week": c["week"].min() if not c.empty else datetime.now(),
                                    "sentiment_label": lbl,
                                    "count": 0,
                                }
                            ]
                        ),
                    ],
                    ignore_index=True,
                )
        return c

    def _weekly_summary(df_daily: pd.DataFrame) -> pd.DataFrame:
        if df_daily is None or df_daily.empty:
            return pd.DataFrame()

        work = df_daily.copy()
        work["datetime"] = pd.to_datetime(work["datetime"], errors="coerce")
        work = work.dropna(subset=["datetime"]).copy()
        if work.empty:
            return pd.DataFrame()

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

    def _top_symptoms(df_sessions: pd.DataFrame, days: int = 30, top_n: int = 5) -> pd.DataFrame:
        if df_sessions is None or df_sessions.empty or "assessment_data" not in df_sessions.columns:
            return pd.DataFrame()
        cutoff = datetime.now() - timedelta(days=days)
        recent = df_sessions[df_sessions["datetime"] >= cutoff].copy()
        if recent.empty:
            return pd.DataFrame()

        symptom_totals: dict[str, float] = {}
        symptom_counts: dict[str, int] = {}
        for _, row in recent.iterrows():
            scores = _extract_symptom_scores(row.get("assessment_data"))
            for symptom_key, score in scores.items():
                name = BDI_SYMPTOM_NAMES.get(symptom_key, str(symptom_key).replace("_", " ").title())
                symptom_totals[name] = symptom_totals.get(name, 0.0) + float(score)
                symptom_counts[name] = symptom_counts.get(name, 0) + 1

        if not symptom_totals:
            return pd.DataFrame()

        rows = []
        for symptom_name, total in symptom_totals.items():
            cnt = symptom_counts.get(symptom_name, 0)
            if cnt <= 0:
                continue
            rows.append({"symptom": symptom_name, "average_score": total / cnt, "entries_count": cnt})
        out = pd.DataFrame(rows)
        out = out.sort_values("average_score", ascending=False).head(top_n)
        return out

    entry_df = user_df.copy()
    entry_df["datetime"] = pd.to_datetime(entry_df.get("datetime"), errors="coerce")
    entry_df = entry_df.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)

    session_df = _build_session_df(entry_df)
    daily_df = _build_daily_df(session_df)

    analysis_30 = analyze_depression(session_df, window_days=30)
    support_mode_on = bool(analysis_30.get("depression_detected", False))

    top_symptoms_df = _top_symptoms(session_df, days=30, top_n=5)

    global_chart_view = st.selectbox(
        "📅 Choose your view:",
        options=_view_options(),
        index=1,
        key=f"vd_view_{user['id']}",
        help="Filters all charts by time range.",
    )
    global_chart_days = _view_to_days(global_chart_view)

    if global_chart_days is None:
        global_session_df = session_df.copy()
        global_daily_df = daily_df.copy()
        export_entry_df = entry_df.copy()
    else:
        cutoff = datetime.now() - timedelta(days=int(global_chart_days))
        global_session_df = session_df[session_df["datetime"] >= cutoff].copy()
        global_daily_df = daily_df[daily_df["datetime"] >= cutoff].copy()
        export_entry_df = entry_df[entry_df["datetime"] >= cutoff].copy()

    overview_tab, trends_tab, patterns_tab, wordcloud_tab, support_tab = st.tabs([
        "Overview",
        "Trends",
        "Patterns",
        "Common words",
        "Support & Export",
    ])

    with overview_tab:
        selected_period_mood = _safe_mode(global_session_df.get("sentiment_label"), default="Neutral") if not global_session_df.empty else "N/A"
        sentiment_label = selected_period_mood

        selected_period_avg_score = (
            float(pd.to_numeric(global_session_df.get("bdi_total_score"), errors="coerce").dropna().mean())
            if global_session_df is not None and not global_session_df.empty
            else float("nan")
        )
        selected_period_distress_level = _label_severity(selected_period_avg_score)

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Depression detected", "Yes" if support_mode_on else "No")
        with m2:
            st.metric(f"{global_chart_view} distress level", str(selected_period_distress_level))
        with m3:
            st.metric(f"{global_chart_view} active days", str(int(len(global_daily_df))) if global_daily_df is not None else "0")
        with m4:
            st.metric(f"{global_chart_view} sentiment", sentiment_label)

        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("Distress score over time")
            if global_daily_df is None or global_daily_df.empty:
                st.info("No data available for the selected view.")
            else:
                fig_bdi_overview = go.Figure()
                fig_bdi_overview.add_trace(
                    go.Scatter(
                        x=global_daily_df["datetime"],
                        y=global_daily_df["bdi_total_score"],
                        mode="lines+markers",
                        line=dict(color="#2E86C1", width=3, shape="spline"),
                        marker=dict(size=6),
                    )
                )
                fig_bdi_overview.update_layout(
                    height=320,
                    template="plotly_white",
                    margin=dict(l=20, r=20, t=10, b=10),
                    yaxis=dict(title="Distress score", range=[0, 63]),
                    xaxis=dict(title=""),
                    showlegend=False,
                )
                st.plotly_chart(fig_bdi_overview, width="stretch", key=f"vd_bdi_overview_{user['id']}_{global_chart_view}")

        with col_right:
            st.subheader("Key symptoms to monitor")
            if top_symptoms_df is None or top_symptoms_df.empty:
                st.info("No symptom assessment data available for analysis.")
            else:
                fig_symptoms_overview = px.bar(
                    top_symptoms_df,
                    y="symptom",
                    x="average_score",
                    orientation="h",
                    labels={"symptom": "Symptom", "average_score": "Average severity (0-3)"},
                    color="average_score",
                    color_continuous_scale="Blues",
                    text="average_score",
                )
                fig_symptoms_overview.update_traces(texttemplate="%{text:.1f}", textposition="outside")
                fig_symptoms_overview.update_layout(
                    height=320,
                    template="plotly_white",
                    showlegend=False,
                    margin=dict(l=20, r=40, t=10, b=10),
                    xaxis=dict(range=[0, 3.2]),
                    yaxis=dict(autorange="reversed"),
                    coloraxis_showscale=False,
                )
                st.plotly_chart(fig_symptoms_overview, width="stretch", key=f"vd_symptoms_overview_{user['id']}_{global_chart_view}")

    with trends_tab:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Weekly distress trend")
            w = _weekly_summary(global_daily_df)
            if w is None or w.empty:
                st.info("No weekly data yet.")
            else:
                fig_bdi = go.Figure()
                fig_bdi.add_trace(
                    go.Scatter(
                        x=w["week"],
                        y=w["avg_bdi"],
                        mode="lines+markers",
                        line=dict(color="#2E86C1", width=3, shape="spline"),
                        marker=dict(size=6),
                    )
                )
                fig_bdi.update_layout(
                    height=320,
                    template="plotly_white",
                    margin=dict(l=20, r=20, t=10, b=10),
                    yaxis=dict(title="Avg distress score", range=[0, 63]),
                    xaxis=dict(title=""),
                    showlegend=False,
                )
                st.plotly_chart(fig_bdi, width="stretch", key=f"vd_weekly_distress_{user['id']}_{global_chart_view}")

        with col2:
            st.subheader("Weekly sentiment mix")
            w_sent = _weekly_sentiment(global_session_df)
            if w_sent.empty:
                st.info("No mood data yet.")
            else:
                w_sent = w_sent.copy()
                w_sent["sentiment"] = w_sent["sentiment_label"].astype(str)
                totals = w_sent.groupby("week")["count"].sum().reset_index(name="total")
                w_sent = w_sent.merge(totals, on="week")
                w_sent["percentage"] = (w_sent["count"] / w_sent["total"]) * 100
                fig_s = px.bar(
                    w_sent,
                    x="week",
                    y="percentage",
                    color="sentiment",
                    barmode="stack",
                    color_discrete_map={
                        "Positive": "darkblue",
                        "Neutral": "#808080",
                        "Negative": "orange",
                    },
                    labels={"week": "", "percentage": "Percentage (%)", "sentiment": "Sentiment"},
                )
                fig_s.update_layout(
                    height=320,
                    template="plotly_white",
                    margin=dict(l=20, r=20, t=10, b=10),
                    legend_title_text="",
                )
                st.plotly_chart(fig_s, width="stretch", key=f"vd_moodmix_{user['id']}_{global_chart_view}")

    with patterns_tab:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Day of week")
            if global_daily_df is None or global_daily_df.empty:
                st.info("No data available.")
            else:
                dfp = global_daily_df.copy()
                dfp["weekday"] = pd.to_datetime(dfp["datetime"]).dt.day_name()
                d = dfp.groupby("weekday")["bdi_total_score"].mean().reset_index(name="avg_score")
                order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                d["weekday"] = pd.Categorical(d["weekday"], categories=order, ordered=True)
                d = d.sort_values("weekday")
                fig_dow = px.bar(
                    d,
                    x="weekday",
                    y="avg_score",
                    labels={"weekday": "", "avg_score": "Avg distress score"},
                    color_discrete_sequence=["#2E86C1"],
                )
                fig_dow.update_layout(height=320, template="plotly_white", margin=dict(l=20, r=20, t=10, b=10))
                st.plotly_chart(fig_dow, width="stretch", key=f"vd_dow_{user['id']}_{global_chart_view}")

        with col2:
            st.subheader("Time of day")
            if global_session_df is None or global_session_df.empty:
                st.info("No data available.")
            else:
                dfp = global_session_df.copy()
                dfp["hour"] = pd.to_datetime(dfp["datetime"]).dt.hour

                def _bucket(h: int) -> str:
                    if 5 <= h < 12:
                        return "Morning"
                    if 12 <= h < 17:
                        return "Afternoon"
                    if 17 <= h < 22:
                        return "Evening"
                    return "Night"

                dfp["tod"] = dfp["hour"].apply(lambda h: _bucket(int(h)) if not pd.isna(h) else "Unknown")
                t = dfp.groupby("tod")["bdi_total_score"].mean().reset_index(name="avg_score")
                order = ["Morning", "Afternoon", "Evening", "Night", "Unknown"]
                t["tod"] = pd.Categorical(t["tod"], categories=order, ordered=True)
                t = t.sort_values("tod")
                fig_tod = px.bar(
                    t,
                    x="tod",
                    y="avg_score",
                    labels={"tod": "", "avg_score": "Avg distress score"},
                    color_discrete_sequence=["#2E86C1"],
                )
                fig_tod.update_layout(height=320, template="plotly_white", margin=dict(l=20, r=20, t=10, b=10))
                st.plotly_chart(fig_tod, width="stretch", key=f"vd_tod_{user['id']}_{global_chart_view}")

    with wordcloud_tab:
        st.subheader("☁️ Common words")
        st.caption("Most common words from recent journal entries (word cloud)")

        if WORDCLOUD_AVAILABLE:
            try:
                db_client_wordcloud = DBClient(user_id=user['id'])
                journal_entries = db_client_wordcloud.get_recent_entries(days=90, limit=100)

                if journal_entries:
                    all_text = ""
                    valid_entries = 0

                    for entry in journal_entries:
                        text = str(entry.get('text', '') or '').strip()
                        if text and len(text) > 10:
                            all_text += text + " "
                            valid_entries += 1

                    if all_text.strip() and valid_entries >= 3:
                        stop_words = set([
                            'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'an', 'a', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'shall',
                            'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours', 'yourself', 'yourselves',
                            'he', 'him', 'his', 'himself', 'she', 'her', 'hers', 'herself', 'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves',
                            'this', 'that', 'these', 'those', 'am', 'was', 'were', 'be', 'been', 'being', 'having', 'doing',
                            'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very'
                        ])

                        wordcloud = WordCloud(
                            width=800,
                            height=400,
                            background_color='white',
                            colormap='Blues',
                            max_words=100,
                            stopwords=stop_words,
                            contour_width=1,
                            contour_color='steelblue',
                            min_word_length=3,
                        ).generate(all_text)

                        fig_wordcloud, ax = plt.subplots(figsize=(10, 5))
                        ax.imshow(wordcloud, interpolation='bilinear')
                        ax.axis('off')
                        st.pyplot(fig_wordcloud)
                        st.caption(f"Based on {valid_entries} journal entries with substantial content")
                    else:
                        st.info("📝 Need more journal entries with content to generate a word cloud (at least 3 meaningful entries).")
                else:
                    st.info("No journal entries available for word cloud.")
            except Exception as e:
                st.error(f"Error generating word cloud: {str(e)}")
        else:
            st.info("📦 Word cloud requires additional packages. Install with: `pip install wordcloud matplotlib`")

    with support_tab:
        if support_mode_on:
            st.subheader("AI recommendation")
            if not _RECOMMENDER_AVAILABLE:
                msg = "AI recommendation is unavailable (backend recommender module could not be loaded)."
                if _RECOMMENDER_IMPORT_ERROR:
                    msg += f"\n\nDetails: {_RECOMMENDER_IMPORT_ERROR}"
                st.info(msg)
            else:
                rec_text = ""
                if top_symptoms_df is not None and not top_symptoms_df.empty:
                    symptoms_payload = [
                        {
                            "symptom": str(r.get("symptom", "")).strip(),
                            "average_score": float(r.get("average_score", 0.0)),
                            "entries_count": int(r.get("entries_count", 0)),
                        }
                        for _, r in top_symptoms_df.iterrows()
                    ]
                    symptoms_json = json.dumps(symptoms_payload, ensure_ascii=False)
                    with st.spinner("Generating AI recommendation..."):
                        try:
                            rec_text = _cached_recommendation(
                                symptoms_json,
                                str(analysis_30.get("overall_severity", "N/A")),
                                str(analysis_30.get("trend_direction", "Stable")),
                            )
                        except Exception as e:
                            st.warning(f"AI recommendation could not be generated: {e}")
                if rec_text:
                    st.write(rec_text)
        else:
            st.info("Current indicators suggest a balanced state of mind. No immediate intervention is needed at this time.")

        st.divider()
        st.subheader("📥 Export")
        export_col1, export_col2 = st.columns(2)

        with export_col1:
            export_df = export_entry_df.copy()
            if export_df is None or export_df.empty:
                st.info("No data available to export for the selected view.")
            else:
                cols = ["datetime", "bdi_total_score", "bdi_severity", "sentiment_label"]
                if "uploaded_file" in export_df.columns:
                    cols.append("uploaded_file")
                csv_df = export_df[cols].copy() if cols else export_df.copy()
                csv_df["datetime"] = pd.to_datetime(csv_df["datetime"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
                csv_bytes = df_to_csv_bytes(csv_df)
                if csv_bytes:
                    st.download_button(
                        label="📄 Download CSV",
                        data=csv_bytes,
                        file_name=f"viewer_personal_{user.get('name','user').replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        key=f"vd_csv_{user['id']}_{global_chart_view}",
                        width="stretch",
                    )

        with export_col2:
            try:
                collected_figs = []
                collected_images = []

                if global_daily_df is not None and not global_daily_df.empty:
                    fig_bdi_pdf = go.Figure()
                    fig_bdi_pdf.add_trace(
                        go.Scatter(
                            x=global_daily_df["datetime"],
                            y=global_daily_df["bdi_total_score"],
                            mode="lines+markers",
                            line=dict(color="#2E86C1", width=3, shape="spline"),
                            marker=dict(size=6),
                        )
                    )
                    fig_bdi_pdf.update_layout(
                        height=260,
                        template="plotly_white",
                        margin=dict(l=20, r=20, t=10, b=10),
                        yaxis=dict(title="Distress score", range=[0, 63]),
                        xaxis=dict(title=""),
                        showlegend=False,
                    )
                    collected_figs.append({"fig": fig_bdi_pdf, "title": "Distress score over time"})

                if top_symptoms_df is not None and not top_symptoms_df.empty:
                    try:
                        fig_symptoms_pdf = px.bar(
                            top_symptoms_df,
                            y="symptom",
                            x="average_score",
                            orientation="h",
                            labels={"symptom": "Symptom", "average_score": "Average severity (0-3)"},
                            color="average_score",
                            color_continuous_scale="Blues",
                            text="average_score",
                        )
                        fig_symptoms_pdf.update_traces(texttemplate="%{text:.1f}", textposition="outside")
                        fig_symptoms_pdf.update_layout(
                            height=260,
                            template="plotly_white",
                            showlegend=False,
                            margin=dict(l=20, r=40, t=10, b=10),
                            xaxis=dict(range=[0, 3.2]),
                            yaxis=dict(autorange="reversed"),
                            coloraxis_showscale=False,
                        )
                        collected_figs.append({"fig": fig_symptoms_pdf, "title": "Key symptoms to monitor"})
                    except Exception:
                        pass

                w_sent_pdf = _weekly_sentiment(global_session_df)
                if w_sent_pdf is not None and not w_sent_pdf.empty:
                    w_sent_pdf = w_sent_pdf.copy()
                    w_sent_pdf["sentiment"] = w_sent_pdf["sentiment_label"].astype(str)
                    totals_pdf = w_sent_pdf.groupby("week")["count"].sum().reset_index(name="total")
                    w_sent_pdf = w_sent_pdf.merge(totals_pdf, on="week")
                    w_sent_pdf["percentage"] = (w_sent_pdf["count"] / w_sent_pdf["total"]) * 100
                    fig_mood_pdf = px.bar(
                        w_sent_pdf,
                        x="week",
                        y="percentage",
                        color="sentiment",
                        barmode="stack",
                        color_discrete_map={
                            "Positive": "darkblue",
                            "Neutral": "#808080",
                            "Negative": "orange",
                        },
                        labels={"week": "", "percentage": "Percentage (%)", "sentiment": "Sentiment"},
                    )
                    fig_mood_pdf.update_layout(
                        height=260,
                        template="plotly_white",
                        margin=dict(l=20, r=20, t=10, b=10),
                        legend_title_text="",
                    )
                    collected_figs.append({"fig": fig_mood_pdf, "title": "Weekly sentiment mix"})

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
                        )
                    )
                    fig_weekly_export.update_layout(
                        height=260,
                        template="plotly_white",
                        margin=dict(l=20, r=20, t=10, b=10),
                        yaxis=dict(title="Avg distress score", range=[0, 63]),
                        xaxis=dict(title=""),
                        showlegend=False,
                    )
                    collected_figs.append({"fig": fig_weekly_export, "title": "Weekly distress trend"})

                # Patterns: Day of week
                try:
                    if global_daily_df is not None and not global_daily_df.empty:
                        dfp_export = global_daily_df.copy()
                        dfp_export["weekday"] = pd.to_datetime(dfp_export["datetime"], errors="coerce").dt.day_name()
                        d = dfp_export.groupby("weekday")["bdi_total_score"].mean().reset_index(name="avg_score")
                        order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                        d["weekday"] = pd.Categorical(d["weekday"], categories=order, ordered=True)
                        d = d.sort_values("weekday")
                        fig_dow_pdf = px.bar(
                            d,
                            x="weekday",
                            y="avg_score",
                            labels={"weekday": "", "avg_score": "Avg distress score"},
                            color_discrete_sequence=["#2E86C1"],
                        )
                        fig_dow_pdf.update_layout(height=260, template="plotly_white", margin=dict(l=20, r=20, t=10, b=10))
                        collected_figs.append({"fig": fig_dow_pdf, "title": "Day of week"})
                except Exception:
                    pass

                # Patterns: Time of day
                try:
                    if global_session_df is not None and not global_session_df.empty:
                        dfp_time_export = global_session_df.copy()
                        dfp_time_export["hour"] = pd.to_datetime(dfp_time_export["datetime"], errors="coerce").dt.hour

                        def _bucket(h: int) -> str:
                            if 5 <= h < 12:
                                return "Morning"
                            if 12 <= h < 17:
                                return "Afternoon"
                            if 17 <= h < 22:
                                return "Evening"
                            return "Night"

                        dfp_time_export["tod"] = dfp_time_export["hour"].apply(lambda h: _bucket(int(h)) if not pd.isna(h) else "Unknown")
                        t = dfp_time_export.groupby("tod")["bdi_total_score"].mean().reset_index(name="avg_score")
                        order = ["Morning", "Afternoon", "Evening", "Night", "Unknown"]
                        t["tod"] = pd.Categorical(t["tod"], categories=order, ordered=True)
                        t = t.sort_values("tod")
                        fig_tod_pdf = px.bar(
                            t,
                            x="tod",
                            y="avg_score",
                            labels={"tod": "", "avg_score": "Avg distress score"},
                            color_discrete_sequence=["#2E86C1"],
                        )
                        fig_tod_pdf.update_layout(height=260, template="plotly_white", margin=dict(l=20, r=20, t=10, b=10))
                        collected_figs.append({"fig": fig_tod_pdf, "title": "Time of day"})
                except Exception:
                    pass

                # Word Cloud
                try:
                    if WORDCLOUD_AVAILABLE:
                        db_client_wordcloud = DBClient(user_id=user['id'])
                        journal_entries = db_client_wordcloud.get_recent_entries(days=90, limit=100)

                        if journal_entries:
                            all_text = ""
                            valid_entries = 0

                            for entry in journal_entries:
                                text = str(entry.get('text', '') or '').strip()
                                if text and len(text) > 10:
                                    all_text += text + " "
                                    valid_entries += 1

                            if all_text.strip() and valid_entries >= 3:
                                stop_words = set([
                                    'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'an', 'a', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                                    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'shall',
                                    'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours', 'yourself', 'yourselves',
                                    'he', 'him', 'his', 'himself', 'she', 'her', 'hers', 'herself', 'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves',
                                    'this', 'that', 'these', 'those', 'am', 'was', 'were', 'be', 'been', 'being', 'having', 'doing',
                                    'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very'
                                ])

                                wordcloud = WordCloud(
                                    width=800,
                                    height=400,
                                    background_color='white',
                                    colormap='Blues',
                                    max_words=100,
                                    stopwords=stop_words,
                                    contour_width=1,
                                    contour_color='steelblue',
                                    min_word_length=3,
                                ).generate(all_text)

                                fig_wordcloud_pdf, ax = plt.subplots(figsize=(10, 5))
                                ax.imshow(wordcloud, interpolation='bilinear')
                                ax.axis('off')
                                img_buffer = io.BytesIO()
                                fig_wordcloud_pdf.savefig(img_buffer, format='png', bbox_inches='tight')
                                img_buffer.seek(0)
                                collected_images.append({"bytes": img_buffer.getvalue(), "title": "Common words"})
                except Exception:
                    pass

                if collected_figs:
                    generated_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    pdf_title = f"Report - {user.get('name','User')} (Generated on {generated_on})"

                    selected_period_mood_pdf = (
                        _safe_mode(global_session_df.get("sentiment_label"), default="Neutral") if not global_session_df.empty else "N/A"
                    )

                    sentiment_category_pdf = (
                        "Positive" if selected_period_mood_pdf == "Positive" else
                        ("Negative" if selected_period_mood_pdf == "Negative" else
                         ("Neutral" if selected_period_mood_pdf == "Neutral" else str(selected_period_mood_pdf)))
                    )

                    user_info = {
                        "User": str(user.get("name", "User")),
                        "Student ID": str(user.get("student_id", "")) if user.get("student_id") else "",
                        "Segment": str(user.get("segment_name") or user.get("segment") or user.get("institution_segment") or "") or "",
                    }

                    metrics = {
                        "Chart range": str(global_chart_view),
                        f"{global_chart_view} distress level": str(selected_period_distress_level),
                        f"{global_chart_view} active days": str(int(len(global_daily_df))) if global_daily_df is not None else "0",
                        f"{global_chart_view} sentiment": str(sentiment_category_pdf),
                    }

                    status_text = "Depression detected" if support_mode_on else "Not depressed"
                    pdf_guidance = "" if support_mode_on else "Current indicators suggest a balanced state of mind. No immediate intervention is needed at this time."

                    ai_recommendation = ""
                    if support_mode_on and _RECOMMENDER_AVAILABLE and top_symptoms_df is not None and not top_symptoms_df.empty:
                        try:
                            symptoms_payload = [
                                {
                                    "symptom": str(r.get("symptom", "")).strip(),
                                    "average_score": float(r.get("average_score", 0.0)),
                                    "entries_count": int(r.get("entries_count", 0)),
                                }
                                for _, r in top_symptoms_df.iterrows()
                            ]
                            symptoms_json = json.dumps(symptoms_payload, ensure_ascii=False)
                            ai_recommendation = _cached_recommendation(
                                symptoms_json,
                                str(analysis_30.get("overall_severity", "N/A")),
                                str(analysis_30.get("trend_direction", "Stable")),
                            )
                        except Exception:
                            ai_recommendation = ""

                    with st.spinner("Preparing PDF..."):
                        pdf_bytes = figs_to_pdf_bytes(
                            collected_figs,
                            title=pdf_title,
                            status_text=status_text,
                            user_info=user_info,
                            metrics=metrics,
                            guidance=pdf_guidance,
                            ai_recommendation=ai_recommendation,
                            images=collected_images,
                        )
                    if pdf_bytes:
                        st.download_button(
                            label="📊 Download PDF Report",
                            data=pdf_bytes,
                            file_name=f"viewer_personal_{user.get('name','user').replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                            mime="application/pdf",
                            key=f"vd_pdf_{user['id']}_{global_chart_view}",
                            width="stretch",
                        )
                else:
                    st.info("No charts available for PDF export")
            except ImportError as ie:
                st.error(str(ie))
            except Exception as e:
                st.error(f"PDF export error: {e}")

# User Selection
st.markdown("### 👤 Select User to View")
user_options = {user['name']: user for user in linked_users}
selected_user_name = st.selectbox(
    "Choose a user",
    options=list(user_options.keys()),
    help="Select which user's dashboard you want to view",
    label_visibility="collapsed"
)

user = user_options[selected_user_name]

st.divider()

# Load user's data like individual dashboard
with st.spinner("Loading insights..."):
    user_df = prepare_dashboard_data(DBClient(user_id=user['id']), window_days=90)

if user_df is None or user_df.empty:
    st.info("👋 **Dashboard coming soon!**\n\nWe need a few more journal entries to start showing insights.")
    st.stop()

# Require recent data before showing this user's dashboard
req = evaluate_recent_data_requirements(user_df, window_days=30, min_entries=10, min_distinct_days=5)
if not req.get('meets', False):
    st.warning(req.get('message', 'Dashboard hidden until minimum data requirement is met.'))
    st.stop()

_render_user_analysis(user, user_df)


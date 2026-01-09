"""
Institution Dashboard - For institution staff to view linked users' mental health data
Shows aggregated assessments and trends for users who opted-in to share with the institution
"""

import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import json
import sys
from pathlib import Path

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

# Add wordcloud imports
try:
    from wordcloud import WordCloud
    import matplotlib.pyplot as plt
    WORDCLOUD_AVAILABLE = True
except ImportError:
    WORDCLOUD_AVAILABLE = False

# Page config
st.set_page_config(
    page_title="Analysis Details",
    page_icon="🏫",
    layout="wide"
)

# Initialize services
auth_service = init_auth_service()

# Render auth sidebar
render_auth_sidebar(auth_service)

# Require authentication and institution role
auth_service.require_auth()
auth_service.require_role(['institution'])

# Get current user
current_user = auth_service.get_current_user()
if not current_user:
    st.error("Authentication required")
    st.stop()

# Initialize DB client and user service
db_client = DBClient(user_id=current_user['id'])
user_service = UserService(db_client.supabase)

# Get viewer profile
profile = auth_service.get_user_profile()

# Check if staff is approved
try:
    staff_info = db_client.supabase.table('institution_staff')\
        .select('status')\
        .eq('user_id', current_user['id'])\
        .execute()
    if staff_info.data and len(staff_info.data) > 0:
        staff_status = staff_info.data[0].get('status', 'pending')
        if staff_status != 'approved':
            st.error("🚫 Your account is pending approval by the institution administrator.")
            st.info("Please contact your institution administrator to approve your account.")
            st.stop()
    else:
        st.error("🚫 You are not registered as institution staff.")
        st.stop()
except Exception as e:
    st.error("Error checking staff status.")
    st.stop()

st.title("🏫 Analysis Details")
st.write(f"Welcome, **{profile.get('name', 'Institution Staff')}**")
st.caption("View mental health insights for users linked to your institution.")

# Get linked users
st.subheader("📊 Linked Users")

with st.spinner("Loading linked users..."):
    linked_users = user_service.get_linked_users_for_viewer(current_user['id'])

if not linked_users:
    st.info("ℹ️ No users are currently linked to your institution.")
    st.write("""
    **How users get linked:**
    - Individual users can opt-in to share their data with your institution through their Settings page
    """)
    st.stop()

st.write(f"**{len(linked_users)} user(s)** have shared their analysis with your institution:")

# NOTE: To reduce initial load time, do NOT pre-load each user's dashboard data here.
# Instead, load and analyze a user's data only when requested within that user's expander.
@st.cache_data(ttl=300, show_spinner=False)
def _load_user_dashboard_df(user_id: str, window_days: int = 90) -> pd.DataFrame:
    return prepare_dashboard_data(DBClient(user_id=user_id), window_days=window_days)

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
    # Analyze recent entries
    user_analysis = analyze_depression(user_df, window_days=30)

    # Status summary
    st.subheader("📊 Current Status")

    status_text = "Not depressed" if not user_analysis["depression_detected"] else "Signs of persistent emotional distress detected"
    status_color = "#4caf50" if not user_analysis["depression_detected"] else "#ffb74d"
    st.markdown(
        f'<div style="background-color: #f0f9f0; color: {status_color}; padding: 10px; border-radius: 5px; border-left: 5px solid {status_color}; font-size: 18px; font-weight: bold;">{status_text}</div>',
        unsafe_allow_html=True,
    )
    st.write("")
    # Recent Severity and Trend metrics (mirror Viewer)
    row2_col1, row2_col2 = st.columns(2)
    with row2_col1:
        severity_emoji = {"Minimal": "🟢", "Mild": "🟢", "Moderate": "🟡", "Severe": "🔴"}.get(user_analysis.get("overall_severity"), "⚪")
        st.metric(
            "Recent Emotional Distress Level",
            f"{user_analysis.get('overall_severity', 'N/A')} {severity_emoji}",
            help=f"Confidence: {user_analysis.get('confidence_level','N/A')}. Level based on recent entries.",
        )
    with row2_col2:
        trend_emoji = {"Improving": "↗️", "Stable": "→", "Worsening": "↘️"}.get(user_analysis.get("trend_direction"), "→")
        st.metric(
            "Recent Trend",
            f"{trend_emoji} {user_analysis.get('trend_direction','Stable')}",
            help="Whether recent entries show improvement, stability, or worsening.",
        )

    # Current streak & recent mood (mirror Viewer)
    try:
        entry_dates = pd.to_datetime(user_df['datetime']).dt.date.dropna()
        unique_dates = set(entry_dates.tolist())
        last_date = max(unique_dates) if unique_dates else None
        streak = 0
        cur = last_date
        while cur in unique_dates:
            streak += 1
            cur -= timedelta(days=1)
    except Exception:
        streak = 0

    recent_entries = user_df.tail(5)
    dominant_sentiment = recent_entries['sentiment_label'].mode()[0] if not recent_entries.empty else "N/A"
    display_sentiment_label = 'Low mood' if dominant_sentiment == 'Negative' else dominant_sentiment
    sentiment_emoji = {"Positive": "😊", "Neutral": "😐", "Negative": "😔", "N/A": "⚪"}.get(dominant_sentiment, "⚪")

    row3_col1, row3_col2 = st.columns(2)
    with row3_col1:
        st.metric("Current Streak", f"{streak} days 🔥", help="Consecutive days with at least one entry.")
    with row3_col2:
        st.metric("Recent Mood", f"{sentiment_emoji} {display_sentiment_label}", help="Tone of recent entries.")
    st.caption("*Summary is based on patterns over multiple entries, not a single entry.*")
    st.divider()

    # Timeframe selection
    timeframe_options = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90, "All time": None}
    selected_timeframe = st.selectbox(
        "📅 Choose timeframe:",
        list(timeframe_options.keys()),
        index=1,
        key=f"tf_{user['id']}",
    )
    cutoff = datetime.now() - timedelta(days=timeframe_options[selected_timeframe]) if timeframe_options[selected_timeframe] else None
    display_df = user_df[user_df['datetime'] >= cutoff].copy() if cutoff else user_df.copy()

    # BDI Score over time
    st.subheader("📈 Emotional Distress Over Time (Lower is better)")
    st.caption("Higher values indicate higher emotional distress. The green area shows low distress, which is a healthy range.")

    if not display_df.empty:
        fig_bdi = go.Figure()
        # Add colored severity bands (mirror Viewer)
        try:
            min_dt = display_df["datetime"].min()
            max_dt = display_df["datetime"].max()
        except Exception:
            min_dt = None
            max_dt = None
        bands = [(0, 9, "#d0f0c0")]
        for start, end, color in bands:
            if min_dt is not None and max_dt is not None:
                fig_bdi.add_shape(type="rect", x0=min_dt, x1=max_dt, y0=start, y1=end, fillcolor=color, opacity=0.3, line_width=0)

        fig_bdi.add_trace(
            go.Scatter(
                x=display_df["datetime"],
                y=display_df["bdi_total_score"],
                mode="lines+markers",
                line=dict(color="#2E86C1", width=3, shape="spline"),
                marker=dict(size=6),
                hovertemplate="<b>%{x|%b %d}</b><br>Score: %{y}<br>Level: %{customdata}<extra></extra>",
                customdata=display_df.get("bdi_severity"),
            )
        )
        fig_bdi.update_layout(
            yaxis=dict(title="Emotional Distress Level", range=[0, 63]),
            xaxis=dict(title="Date"),
            template="plotly_white",
            height=380,
            margin=dict(l=20, r=20, t=20, b=20),
            showlegend=False,
        )
        st.plotly_chart(fig_bdi, width='stretch', key=f"fig_bdi_{user['id']}_{selected_timeframe}")
    else:
        st.info("No data available for the selected timeframe.")

    # Mood & Severity overview
    st.subheader("😊 Mood & Distress Overview")
    if not display_df.empty:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Mood Tone")
            sentiment_counts = display_df['sentiment_label'].value_counts()
            friendly_labels = {"Positive": "😊", "Neutral": "😐", "Negative": "😔"}
            fig_sent = px.bar(
                x=[friendly_labels.get(k, k) for k in sentiment_counts.index],
                y=sentiment_counts.values,
                labels={'x': 'Mood Tone', 'y': 'Number of Entries'},
                color=[friendly_labels.get(k, k) for k in sentiment_counts.index],
                color_discrete_map={"😊": "#2E86C1", "😐": "#95A5A6", "😔": "#F39C12"},
            )
            fig_sent.update_layout(height=300, template="plotly_white", showlegend=False, margin=dict(l=20, r=20, t=20, b=20))
            fig_sent.update_xaxes(tickfont=dict(size=18))
            fig_sent.update_traces(width=0.6)  # Consistent bar width
            st.plotly_chart(fig_sent, width='stretch', key=f"fig_sent_{user['id']}_{selected_timeframe}")
        with col2:
            st.subheader("Distress Severity Distribution")
            if 'bdi_severity' in display_df.columns:
                category_counts = display_df['bdi_severity'].value_counts()
                fig_cat = px.bar(
                    x=category_counts.index,
                    y=category_counts.values,
                    labels={'x': 'Severity', 'y': 'Number of Entries'},
                    color_discrete_sequence=['#2E86C1'],
                )
                fig_cat.update_layout(height=300, template="plotly_white", showlegend=False, margin=dict(l=20, r=20, t=20, b=20))
                fig_cat.update_traces(width=0.6)  # Consistent bar width
                st.plotly_chart(fig_cat, width='stretch', key=f"fig_cat_{user['id']}_{selected_timeframe}")
            else:
                st.info("No BDI category data available.")

    # Top symptoms chart
    st.subheader("⚠️ Key Symptoms to Monitor")

    def get_top_symptoms(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
        if df is None or df.empty or 'assessment_data' not in df.columns:
            return pd.DataFrame()
        recent_cutoff = datetime.now() - timedelta(days=30)
        recent_df = df[df['datetime'] >= recent_cutoff].copy()
        if recent_df.empty:
            return pd.DataFrame()
        symptom_totals = {}
        symptom_counts = {}
        for _, row in recent_df.iterrows():
            assessment = row.get('assessment_data', {})
            if isinstance(assessment, dict):
                for symptom_key, symptom_data in assessment.items():
                    score = None
                    if isinstance(symptom_data, dict):
                        for possible_key in ['level', 'score', 'value']:
                            if possible_key in symptom_data and isinstance(symptom_data[possible_key], (int, float)):
                                score = float(symptom_data[possible_key])
                                break
                        if score is not None and 0 <= score <= 3:
                            if symptom_key in BDI_SYMPTOM_NAMES:
                                symptom_name = BDI_SYMPTOM_NAMES[symptom_key]
                            else:
                                symptom_name = symptom_data.get('symptom', symptom_key.replace('_', ' ').title())
                            symptom_totals[symptom_name] = symptom_totals.get(symptom_name, 0) + score
                            symptom_counts[symptom_name] = symptom_counts.get(symptom_name, 0) + 1
                    elif isinstance(symptom_data, (int, float)):
                        score = float(symptom_data)
                        if 0 <= score <= 3:
                            symptom_name = BDI_SYMPTOM_NAMES.get(symptom_key, symptom_key.replace('_', ' ').title())
                            symptom_totals[symptom_name] = symptom_totals.get(symptom_name, 0) + score
                            symptom_counts[symptom_name] = symptom_counts.get(symptom_name, 0) + 1
        if symptom_totals:
            symptom_avgs = []
            for symptom, total in symptom_totals.items():
                count = symptom_counts[symptom]
                if count > 0:
                    avg_score = total / count
                    symptom_avgs.append({'symptom': symptom, 'average_score': avg_score, 'entries_count': count})
            result_df = pd.DataFrame(symptom_avgs)
            result_df = result_df.sort_values('average_score', ascending=False).head(top_n)
            return result_df
        return pd.DataFrame()

    top_symptoms_df = get_top_symptoms(user_df)
    if not top_symptoms_df.empty:
        fig_symptoms = px.bar(
            top_symptoms_df,
            y='symptom',
            x='average_score',
            orientation='h',
            labels={'symptom': 'Symptom', 'average_score': 'Average Severity (0-3)'},
            color='average_score',
            color_continuous_scale='Blues',
            text='average_score',
        )
        fig_symptoms.update_traces(texttemplate='%{text:.1f}', textposition='outside', marker=dict(line=dict(width=1, color='DarkSlateGrey')))
        fig_symptoms.update_layout(
            height=max(300, len(top_symptoms_df) * 40),
            template='plotly_white',
            showlegend=False,
            margin=dict(l=20, r=40, t=20, b=20),
            xaxis=dict(range=[0, 3.2]),
            yaxis=dict(autorange='reversed'),
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig_symptoms, width='stretch', key=f"fig_symptoms_{user['id']}")

        # AI recommendation (only when signs of persistent emotional distress are detected)
        if user_analysis.get('depression_detected', False):
            st.subheader("✨ AI Recommendation")

            if not _RECOMMENDER_AVAILABLE:
                msg = "AI recommendation is unavailable (backend recommender module could not be loaded)."
                if _RECOMMENDER_IMPORT_ERROR:
                    msg += f"\n\nDetails: {_RECOMMENDER_IMPORT_ERROR}"
                st.info(msg)
            else:

                symptoms_payload = [
                    {
                        'symptom': str(r.get('symptom', '')).strip(),
                        'average_score': float(r.get('average_score', 0.0)),
                        'entries_count': int(r.get('entries_count', 0)),
                    }
                    for _, r in top_symptoms_df.iterrows()
                ]
                symptoms_json = json.dumps(symptoms_payload, ensure_ascii=False)

                with st.spinner('Generating AI recommendation...'):
                    try:
                        rec = _cached_recommendation(
                            symptoms_json,
                            str(user_analysis.get('overall_severity', 'N/A')),
                            str(user_analysis.get('trend_direction', 'Stable')),
                        )
                    except Exception as e:
                        rec = ''
                        st.warning(f"AI recommendation could not be generated: {e}")

                if rec:
                    st.write(rec)
    else:
        st.info('No symptom assessment data available for analysis.')

    st.divider()

    # Gentle guidance
    analysis = user_analysis
    if analysis['depression_detected']:
        st.info('💛 **Support and care are important.** Consider reaching out or suggesting professional support.')
        guidance_text = 'Support and care are important. Consider reaching out or suggesting professional support.'
    else:
        st.info('🌱 **Things look okay.** Continued monitoring and support can make a positive difference.')
        guidance_text = 'Things look okay. Continued monitoring and support can make a positive difference.'

    st.divider()

    # Export section at bottom of dropdown
    st.subheader("📥 Export Data")
    export_col1, export_col2 = st.columns(2)

    with export_col1:
        # CSV export
        export_df = user_df[['datetime', 'bdi_total_score', 'bdi_severity', 'sentiment_label']].copy()
        export_df['datetime'] = export_df['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
        csv_data = export_df.to_csv(index=False)

        st.download_button(
            label="📄 Download CSV",
            data=csv_data,
            file_name=f"analysis_{user['name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            help="Download this user's analysis data",
            key=f"csv_export_{user['id']}",
            use_container_width=True,
        )

    with export_col2:
        # PDF Export
        try:
            collected_figs = []
            if 'fig_bdi' in locals():
                collected_figs.append({'fig': locals()['fig_bdi'], 'title': 'Emotional Distress Over Time'})
            if 'fig_symptoms' in locals():
                collected_figs.append({'fig': locals()['fig_symptoms'], 'title': 'Key Symptoms to Monitor'})
            if 'fig_sent' in locals():
                collected_figs.append({'fig': locals()['fig_sent'], 'title': 'Mood Tone'})
            if 'fig_cat' in locals():
                collected_figs.append({'fig': locals()['fig_cat'], 'title': 'Distress Severity Distribution'})

            if collected_figs:
                generated_on = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                try:
                    latest_dt = pd.to_datetime(user_df['datetime']).max()
                except Exception:
                    latest_dt = None

                try:
                    min_dt = pd.to_datetime(display_df['datetime']).min() if display_df is not None and not display_df.empty else None
                    max_dt = pd.to_datetime(display_df['datetime']).max() if display_df is not None and not display_df.empty else None
                except Exception:
                    min_dt = None
                    max_dt = None

                # Keep Key Metrics consistent with the individual dashboard PDF
                metrics = {
                    'Recent Emotional Distress Level': f"{user_analysis.get('overall_severity', 'N/A')}",
                    'Recent Trend': f"{user_analysis.get('trend_direction', 'Stable')}",
                    'Current Streak': f"{streak} days",
                    'Recent Mood': f"{display_sentiment_label}",
                }

                pdf_title = f"Well-being Report - {user['name']} (Generated on {generated_on})"
                
                # Generate AI recommendation if depression detected and recommender available
                ai_recommendation = ""
                if user_analysis.get('depression_detected', False) and _RECOMMENDER_AVAILABLE:
                    try:
                        symptoms_payload = [
                            {
                                'symptom': str(r.get('symptom', '')).strip(),
                                'average_score': float(r.get('average_score', 0.0)),
                                'entries_count': int(r.get('entries_count', 0)),
                            }
                            for _, r in top_symptoms_df.iterrows()
                        ]
                        symptoms_json = json.dumps(symptoms_payload, ensure_ascii=False)
                        
                        # Use cached function for consistency
                        rec = _cached_recommendation(
                            symptoms_json,
                            str(user_analysis.get('overall_severity', 'N/A')),
                            str(user_analysis.get('trend_direction', 'Stable')),
                        )
                        if rec:
                            ai_recommendation = rec
                    except Exception as e:
                        # If AI recommendation fails, just skip it for PDF
                        pass
                
                with st.spinner("Preparing PDF..."):
                    pdf_bytes = figs_to_pdf_bytes(
                        collected_figs,
                        title=pdf_title,
                        status_text=status_text,
                        metrics=metrics,
                        guidance=guidance_text,
                        ai_recommendation=ai_recommendation,
                    )
                if pdf_bytes:
                    st.download_button(
                        label="📊 Download PDF Report",
                        data=pdf_bytes,
                        file_name=f"institution_analysis_{user['name'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                        mime="application/pdf",
                        key=f"pdf_download_{user['id']}",
                        use_container_width=True,
                    )
            else:
                st.info("No charts available for PDF export")
        except ImportError as ie:
            st.error(str(ie))
        except Exception as e:
            st.error(f"PDF export error: {e}")

# --- Controls: Search and Segment filter ---
inst_id = None
segments = []
try:
    staff_info = db_client.supabase.table('institution_staff')\
        .select('institution_id')\
        .eq('user_id', current_user['id'])\
        .execute()
    if getattr(staff_info, 'data', None) and len(staff_info.data) > 0:
        inst_id = staff_info.data[0].get('institution_id')
except Exception:
    inst_id = None

if inst_id:
    try:
        seg_resp = db_client.supabase.table('institution_segments')\
            .select('segment_name')\
            .eq('institution_id', inst_id)\
            .order('segment_name')\
            .execute()
        if getattr(seg_resp, 'data', None):
            segments = [s.get('segment_name') for s in seg_resp.data if s.get('segment_name')]
    except Exception:
        segments = []

col_search, col_seg = st.columns([3, 1])
with col_search:
    search_term = st.text_input("Search by name or student ID", value="", placeholder="Name or Student ID")
with col_seg:
    seg_options = ["All segments"] + segments
    selected_segment = st.selectbox("Filter by segment", options=seg_options)

# Apply search + segment filters
filtered_users = []
term = (search_term or "").strip().lower()
for user in linked_users:
    ok = True
    # segment filter
    if selected_segment and selected_segment != "All segments":
        u_seg = (user.get('segment_name') or user.get('segment') or user.get('institution_segment') or "")
        if not u_seg or selected_segment.lower() != str(u_seg).strip().lower():
            ok = False
    # search term filter (name or student id)
    if ok and term:
        name = (user.get('name') or "").lower()
        sid = str(user.get('student_id') or "").lower()
        if term.isdigit():
            # numeric -> treat as student id substring match
            if term not in sid:
                ok = False
        else:
            if term not in name and term not in sid:
                ok = False
    if ok:
        filtered_users.append(user)

st.write(f"**{len(filtered_users)} user(s) matching filters**")

if not filtered_users:
    st.info("No users match the current filters.")
    st.stop()

# Group user cards by segment to keep the list manageable
from collections import defaultdict

users_by_segment = defaultdict(list)
for user in filtered_users:
    seg = user.get('segment_name') or user.get('segment') or user.get('institution_segment') or "Unassigned"
    seg = str(seg).strip() if seg else "Unassigned"
    users_by_segment[seg].append(user)

def _segment_sort_key(seg_name: str) -> tuple:
    # Keep "Unassigned" at the end
    return (seg_name.lower() == "unassigned", seg_name.lower())

for seg_name in sorted(users_by_segment.keys(), key=_segment_sort_key):
    seg_users = users_by_segment[seg_name]
    with st.expander(f"🧩 {seg_name} ({len(seg_users)})", expanded=False):
        for user in seg_users:
            user_label = f"👤 {user.get('name', 'Unknown')} ({user.get('student_id', 'No Student ID')})"
            with st.expander(user_label, expanded=False):
                # Display basic metadata without triggering heavy loads
                col_meta1, col_meta2 = st.columns([1, 1])
                with col_meta1:
                    if user.get('student_id'):
                        st.caption(f"Student ID: {user['student_id']}")
                with col_meta2:
                    u_seg = user.get('segment_name') or user.get('segment') or user.get('institution_segment') or None
                    if u_seg:
                        st.caption(f"Segment: {u_seg}")

                show_key = f"show_analysis_{user['id']}"
                show_analysis = st.checkbox(
                    "Show analysis",
                    key=show_key,
                    help="Click to expand the user's detailed analysis (may take time to load data and charts).",
                )

                if not show_analysis:
                    st.caption("Enable 'Show analysis' to load charts and exports for this user.")
                    continue

                st.divider()

                # --- Mirror Viewer Dashboard sections (BDI trend, mood overview, top symptoms, wordcloud) ---
                with st.spinner("Loading and analyzing user data..."):
                    user_df = _load_user_dashboard_df(user['id'], window_days=90)

                if user_df is None or user_df.empty:
                    st.info("No data available for this user yet.")
                    continue

                # Optional check AFTER load (no upfront wait); skip heavy rendering if insufficient
                try:
                    req = evaluate_recent_data_requirements(user_df, window_days=30, min_entries=10, min_distinct_days=5)
                    if not req.get('meets', False):
                        st.info("ℹ️ Not enough recent data to show detailed analysis yet.")
                        st.caption("Minimum requirement: 10 entries across at least 5 different days in the last 30 days.")
                        continue
                except Exception:
                    # If requirements check fails, proceed with best-effort rendering
                    pass

                _render_user_analysis(user, user_df)

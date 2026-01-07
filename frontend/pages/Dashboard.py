"""
Mental Health Dashboard

A calm, supportive dashboard for tracking emotional well-being over time.
This is not a diagnostic tool - just a way to reflect on your entries.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from utils.db_client import DBClient
from utils.auth import init_auth_service
from utils.auth_sidebar import render_auth_sidebar
from utils.depression_detection import analyze_depression, prepare_dashboard_data, evaluate_recent_data_requirements
from utils.export_utils import df_to_csv_bytes, dashboard_to_pdf_bytes

# -----------------------------
# PAGE CONFIG
# -----------------------------
st.set_page_config(
    page_title="Well-being Overview",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------
# AUTHENTICATION
# -----------------------------
auth_service = init_auth_service()
render_auth_sidebar(auth_service)
auth_service.require_role(['individual'])

current_user = auth_service.get_current_user()
if not current_user:
    st.error("Authentication required")
    st.stop()

user_profile = auth_service.get_user_profile()
user_name = user_profile.get('name', 'User') if user_profile else 'User'
user_id = current_user['id']
db_client = DBClient(user_id=user_id)

# -----------------------------
# DATA LOADING
# -----------------------------
with st.spinner("Loading your insights..."):
    df = prepare_dashboard_data(db_client, window_days=90)

if df is None or df.empty:
    st.info("👋 **Welcome to your dashboard!**\n\nWe need a few more journal entries to start showing insights.")
    st.stop()

# Require recent data before showing the dashboard
req = evaluate_recent_data_requirements(df, window_days=30, min_entries=10, min_distinct_days=5)
if not req.get('meets', False):
    st.warning(req.get('message', 'Dashboard hidden until minimum data requirement is met.'))
    st.stop()

overall_analysis = analyze_depression(df, window_days=30)

# -----------------------------
# DASHBOARD HEADER
# -----------------------------
st.title("🌿 My Well-being Overview")
st.caption("Reflect on your emotional patterns over time. This is not a medical diagnosis.")
st.write("")

# -----------------------------
# SECTION 1: STATUS SUMMARY
# -----------------------------
st.subheader("📊 Current Status")

# Current mental well-being card
status_text = "Not depressed" if not overall_analysis["depression_detected"] else "Signs of persistent emotional distress detected"
status_color = "#4caf50" if not overall_analysis["depression_detected"] else "#ffb74d"
st.markdown(f'<div style="background-color: #f0f9f0; color: {status_color}; padding: 10px; border-radius: 5px; border-left: 5px solid {status_color}; font-size: 24px; font-weight: bold;">{status_text}</div>', unsafe_allow_html=True)
st.write("")

# Recent Severity and Trend
row2_col1, row2_col2 = st.columns(2)
with row2_col1:
    severity_emoji = {"Minimal": "🟢", "Mild": "🟢", "Moderate": "🟡", "Severe": "🔴"}.get(overall_analysis["overall_severity"], "⚪")
    st.metric(
        "Recent Emotional Distress Level",
        f"{overall_analysis['overall_severity']} {severity_emoji}",
        help=f"Confidence: {overall_analysis.get('confidence_level','N/A')}. Level based on recent entries."
    )
with row2_col2:
    trend_emoji = {"Improving":"↗️", "Stable":"→", "Worsening":"↘️"}.get(overall_analysis["trend_direction"], "→")
    st.metric(
        "Recent Trend",
        f"{trend_emoji} {overall_analysis['trend_direction']}",
        help="Whether your recent entries show improvement, stability, or worsening."
    )

# Current streak & recent mood
try:
    entry_dates = pd.to_datetime(df['datetime']).dt.date.dropna()
    unique_dates = set(entry_dates.tolist())
    last_date = max(unique_dates) if unique_dates else None
    streak = 0
    cur = last_date
    while cur in unique_dates:
        streak += 1
        cur -= timedelta(days=1)
except Exception:
    streak = 0

recent_entries = df.tail(5)
dominant_sentiment = recent_entries['sentiment_label'].mode()[0] if not recent_entries.empty else "N/A"
display_sentiment_label = 'Low mood' if dominant_sentiment=='Negative' else dominant_sentiment
sentiment_emoji = {"Positive":"😊","Neutral":"😐","Negative":"😔","N/A":"⚪"}.get(dominant_sentiment,"⚪")

row3_col1, row3_col2 = st.columns(2)
with row3_col1:
    st.metric("Current Streak", f"{streak} days 🔥", help="Consecutive days with at least one entry.")
with row3_col2:
    st.metric("Recent Mood", f"{sentiment_emoji} {display_sentiment_label}", help="Tone of your recent entries.")
st.caption("*Summary is based on patterns over multiple entries, not a single entry.*")
st.divider()



# -----------------------------
# TIMEFRAME SELECTION
# -----------------------------
timeframe_options = {"Last 7 days":7,"Last 30 days":30,"Last 90 days":90,"All time":None}
selected_timeframe = st.selectbox("📅 Choose your view:", list(timeframe_options.keys()), index=1, help="Filters all charts by time range.")
cutoff = datetime.now()-timedelta(days=timeframe_options[selected_timeframe]) if timeframe_options[selected_timeframe] else None
display_df = df[df['datetime']>=cutoff].copy() if cutoff else df.copy()
analysis = analyze_depression(display_df, window_days=30) if not display_df.empty else {"depression_detected": False, "overall_severity":"Minimal", "trend_direction":"Stable", "confidence_level":"Low", "top_symptoms":[], "explanation":"Not enough data."}

# -----------------------------
# SECTION 2: BDI SCORE OVER TIME
# -----------------------------
st.subheader("📈 Emotional Distress Over Time (Lower is better)")
st.caption("Higher values indicate higher emotional distress. The green area shows low distress, which is a healthy range.")

fig_bdi = go.Figure()
# Add colored severity bands
bands = [(0,9,"#d0f0c0")]
for start,end,color in bands:
    fig_bdi.add_shape(type="rect", x0=min(display_df["datetime"]), x1=max(display_df["datetime"]), y0=start, y1=end, fillcolor=color, opacity=0.3, line_width=0)

fig_bdi.add_trace(go.Scatter(
    x=display_df["datetime"],
    y=display_df["bdi_total_score"],
    mode="lines+markers",
    line=dict(color="#2E86C1", width=3, shape="spline"),
    marker=dict(size=6),
    hovertemplate="<b>%{x|%b %d}</b><br>Score: %{y}<br>Level: %{customdata}<extra></extra>",
    customdata=display_df["bdi_severity"]
))
fig_bdi.update_layout(yaxis=dict(title="Emotional Distress Level", range=[0,63]), xaxis=dict(title="Date"), template="plotly_white", height=380, margin=dict(l=20,r=20,t=20,b=20), showlegend=False)
st.plotly_chart(fig_bdi,width='stretch')
st.divider()

# -----------------------------
# SECTION 3: MOOD & BDI CATEGORY OVERVIEW
# -----------------------------
st.subheader("😊 Mood & Distress Overview")
if not display_df.empty:
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("Mood Tone")
        sentiment_counts = display_df['sentiment_label'].value_counts()
        friendly_labels = {"Positive":"😊","Neutral":"😐","Negative":"😔"}
        fig_sent = px.bar(
            x=[friendly_labels.get(k,k) for k in sentiment_counts.index],
            y=sentiment_counts.values,
            labels={'x':'Mood Tone','y':'Number of Entries'},
            color=[friendly_labels.get(k,k) for k in sentiment_counts.index],
            color_discrete_map={"😊":"#2E86C1","😐":"#95A5A6","😔":"#F39C12"}
        )
        fig_sent.update_layout(height=300,template="plotly_white",showlegend=False,margin=dict(l=20,r=20,t=20,b=20))
        fig_sent.update_xaxes(tickfont=dict(size=18))
        st.plotly_chart(fig_sent,width='stretch')
    with col2:
        st.subheader("Distress Severity Distribution")
        if 'bdi_severity' in display_df.columns:
            category_counts = display_df['bdi_severity'].value_counts()
            fig_cat = px.bar(
                x=category_counts.index,
                y=category_counts.values,
                labels={'x':'Severity','y':'Number of Entries'},
                color_discrete_sequence=['#2E86C1']
            )
            fig_cat.update_layout(height=300,template="plotly_white",showlegend=False,margin=dict(l=20,r=20,t=20,b=20))
            st.plotly_chart(fig_cat,width='stretch')
        else:
            st.info("No BDI category data available.")
else:
    st.info("No data available for the selected timeframe.")
st.divider()

# -----------------------------
# SECTION 4: GENTLE GUIDANCE
# -----------------------------
if analysis["depression_detected"]:
    st.info("💛 **You’re not alone.** Persistent distress can be challenging. Consider talking to someone you trust or a mental health professional.")
else:
    st.info("🌱 **You’re doing okay.** Keep journaling — reflection helps build awareness.")

st.divider()
# -----------------------------
# EXPORT CONTROLS
# -----------------------------
st.subheader("📥 Export Data")
export_col1, export_col2 = st.columns([1,1])

with export_col1:
    # CSV Export
    try:
        csv_df = display_df[['datetime','bdi_total_score','bdi_severity','sentiment_label']].copy()
        csv_df['datetime'] = csv_df['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
        csv_bytes = df_to_csv_bytes(csv_df)
        if csv_bytes:
            st.download_button(
                label="📄 Download CSV",
                data=csv_bytes,
                file_name=f"wellbeing_data_{user_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )
    except Exception as e:
        st.error(f"CSV export error: {e}")

with export_col2:
    # PDF Export - comprehensive dashboard report
    try:
        # Collect all dashboard data for comprehensive PDF
        dashboard_data = {
            'status_text': status_text,
            'metrics': {
                'Recent Emotional Distress Level': f"{overall_analysis['overall_severity']}",
                'Recent Trend': f"{overall_analysis['trend_direction']}",
                'Current Streak': f"{streak} days",
                'Recent Mood': f"{display_sentiment_label}"
            },
            'guidance': "You are not alone. Persistent distress can be challenging. Consider talking to someone you trust or a mental health professional." if not overall_analysis["depression_detected"] else "You are not alone. Persistent distress can be challenging. Consider talking to someone you trust or a mental health professional.",
            'figs': []
        }
        
        # Add available charts
        if 'fig_bdi' in locals():
            dashboard_data['figs'].append(locals()['fig_bdi'])
        if 'fig_sent' in locals():
            dashboard_data['figs'].append(locals()['fig_sent'])
        if 'fig_cat' in locals():
            dashboard_data['figs'].append(locals()['fig_cat'])
        
        if dashboard_data['figs']:
            with st.spinner("Preparing comprehensive PDF report..."):
                generation_time = datetime.now().strftime('%B %d, %Y at %I:%M %p')
                pdf_title = f"MindCare Well-being Report - {user_name} (Generated on {generation_time})"
                pdf_bytes = dashboard_to_pdf_bytes(dashboard_data, title=pdf_title)
            if pdf_bytes:
                st.download_button(
                    label="📊 Download PDF Report",
                    data=pdf_bytes,
                    file_name=f"wellbeing_report_{user_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
        else:
            st.info("No data available for PDF report")
    except ImportError as ie:
        st.error(str(ie))
    except Exception as e:
        st.error(f"PDF export error: {e}")


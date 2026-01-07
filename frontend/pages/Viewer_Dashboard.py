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
    page_icon="💖",
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

st.title("💖 Analysis Details")
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

user_overall_analysis = analyze_depression(user_df, window_days=30)

# Export functionality
col_title, col_export = st.columns([3, 1])
with col_title:
    st.subheader("📊 Current Status")
with col_export:
    # CSV export only (PDF export moved to bottom after figures are created)
    export_df = user_df[['datetime', 'bdi_total_score', 'bdi_severity', 'sentiment_label']].copy()
    export_df['datetime'] = export_df['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
    csv_data = export_df.to_csv(index=False)

# SECTION 1: STATUS SUMMARY

# Current mental well-being card
status_text = "Not depressed" if not user_overall_analysis["depression_detected"] else "Signs of persistent emotional distress detected"
status_color = "#4caf50" if not user_overall_analysis["depression_detected"] else "#ffb74d"
st.markdown(f'<div style="background-color: #f0f9f0; color: {status_color}; padding: 10px; border-radius: 5px; border-left: 5px solid {status_color}; font-size: 24px; font-weight: bold;">{status_text}</div>', unsafe_allow_html=True)
st.write("")

# Recent Severity and Trend
row2_col1, row2_col2 = st.columns(2)
with row2_col1:
    severity_emoji = {"Minimal": "🟢", "Mild": "🟢", "Moderate": "🟡", "Severe": "🔴"}.get(user_overall_analysis["overall_severity"], "⚪")
    st.metric(
        "Recent Emotional Distress Level",
        f"{user_overall_analysis['overall_severity']} {severity_emoji}",
        help=f"Confidence: {user_overall_analysis.get('confidence_level','N/A')}. Level based on recent entries."
    )
with row2_col2:
    trend_emoji = {"Improving":"↗️", "Stable":"→", "Worsening":"↘️"}.get(user_overall_analysis["trend_direction"], "→")
    st.metric(
        "Recent Trend",
        f"{trend_emoji} {user_overall_analysis['trend_direction']}",
        help="Whether recent entries show improvement, stability, or worsening."
    )

# Current streak & recent mood
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
display_sentiment_label = 'Low mood' if dominant_sentiment=='Negative' else dominant_sentiment
sentiment_emoji = {"Positive":"😊","Neutral":"😐","Negative":"😔","N/A":"⚪"}.get(dominant_sentiment,"⚪")

row3_col1, row3_col2 = st.columns(2)
with row3_col1:
    st.metric("Current Streak", f"{streak} days 🔥", help="Consecutive days with at least one entry.")
with row3_col2:
    st.metric("Recent Mood", f"{sentiment_emoji} {display_sentiment_label}", help="Tone of recent entries.")
st.caption("*Summary is based on patterns over multiple entries, not a single entry.*")
st.divider()

# TIMEFRAME SELECTION
timeframe_options = {"Last 7 days":7,"Last 30 days":30,"Last 90 days":90,"All time":None}
selected_timeframe = st.selectbox("📅 Choose your view:", list(timeframe_options.keys()), index=1, help="Filters all charts by time range.")
cutoff = datetime.now()-timedelta(days=timeframe_options[selected_timeframe]) if timeframe_options[selected_timeframe] else None
display_df = user_df[user_df['datetime']>=cutoff].copy() if cutoff else user_df.copy()

# SECTION 2: BDI SCORE OVER TIME
st.subheader("📈 Emotional Distress Over Time (Lower is better)")
st.caption("Higher values indicate higher emotional distress. The green area shows low distress, which is a healthy range.")

if not display_df.empty:
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
else:
    st.info("No data available for the selected timeframe.")
st.divider()

# SECTION 3: MOOD & BDI CATEGORY OVERVIEW
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
        fig_sent.update_traces(width=0.6)  # Consistent bar width
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
            fig_cat.update_traces(width=0.6)  # Consistent bar width
            st.plotly_chart(fig_cat,width='stretch')
        else:
            st.info("No BDI category data available.")
else:
    st.info("No data available for the selected timeframe.")
st.divider()

# SECTION 4: TOP SYMPTOMS OF CONCERN
st.subheader("⚠️ Key Symptoms to Monitor")
st.caption("5 Most prominent symptoms based on recent assessments (higher scores indicate greater concern)")

def get_top_symptoms(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    """Extract top N symptoms by average score from recent entries."""
    if df is None or df.empty or 'assessment_data' not in df.columns:
        return pd.DataFrame()
    
    # Use recent entries (same window as analysis)
    recent_cutoff = datetime.now() - timedelta(days=30)
    recent_df = df[df['datetime'] >= recent_cutoff].copy()
    
    if recent_df.empty:
        return pd.DataFrame()
    
    # Aggregate symptom scores
    symptom_totals = {}
    symptom_counts = {}
    
    for _, row in recent_df.iterrows():
        assessment = row.get('assessment_data', {})
        if isinstance(assessment, dict):
            for symptom_key, symptom_data in assessment.items():
                if isinstance(symptom_data, dict):
                    # Try different possible keys for the score
                    score = None
                    for possible_key in ['level', 'score', 'value']:
                        if possible_key in symptom_data and isinstance(symptom_data[possible_key], (int, float)):
                            score = float(symptom_data[possible_key])
                            break
                    
                    if score is not None and 0 <= score <= 3:
                        # Get symptom name - prioritize BDI_SYMPTOM_NAMES
                        if symptom_key in BDI_SYMPTOM_NAMES:
                            symptom_name = BDI_SYMPTOM_NAMES[symptom_key]
                        else:
                            symptom_name = symptom_data.get('symptom', symptom_key.replace('_', ' ').title())
                        
                        if symptom_name not in symptom_totals:
                            symptom_totals[symptom_name] = 0
                            symptom_counts[symptom_name] = 0
                        
                        symptom_totals[symptom_name] += score
                        symptom_counts[symptom_name] += 1
    
    # Calculate averages and create DataFrame
    if symptom_totals:
        symptom_avgs = []
        for symptom, total in symptom_totals.items():
            count = symptom_counts[symptom]
            if count > 0:
                avg_score = total / count
                symptom_avgs.append({
                    'symptom': symptom,
                    'average_score': avg_score,
                    'entries_count': count
                })
        
        result_df = pd.DataFrame(symptom_avgs)
        result_df = result_df.sort_values('average_score', ascending=False).head(top_n)
        return result_df
    
    return pd.DataFrame()

# Get top 5 symptoms
top_symptoms_df = get_top_symptoms(user_df)

if not top_symptoms_df.empty:
    # Create horizontal bar chart
    fig_symptoms = px.bar(
        top_symptoms_df,
        y='symptom',
        x='average_score',
        orientation='h',
        labels={'symptom': 'Symptom', 'average_score': 'Average Severity (0-3)'},
        color='average_score',
        color_continuous_scale='Blues',
        text='average_score'
    )
    
    fig_symptoms.update_traces(
        texttemplate='%{text:.1f}',
        textposition='outside',
        marker=dict(line=dict(width=1, color='DarkSlateGrey'))
    )
    
    fig_symptoms.update_layout(
        height=max(300, len(top_symptoms_df) * 40),
        template="plotly_white",
        showlegend=False,
        coloraxis_showscale=False,
        margin=dict(l=20, r=40, t=20, b=20),
        xaxis=dict(range=[0, 3.2]),  # BDI scale is 0-3
        yaxis=dict(autorange="reversed")  # Highest score at top
    )
    
    st.plotly_chart(fig_symptoms, width='stretch')
else:
    st.info("No symptom assessment data available for analysis.")

st.divider()

# AI recommendation (only when signs of persistent emotional distress are detected)
if user_overall_analysis.get('depression_detected', False):
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
                    str(user_overall_analysis.get('overall_severity', 'N/A')),
                    str(user_overall_analysis.get('trend_direction', 'Stable')),
                )
            except Exception as e:
                rec = ''
                st.warning(f"AI recommendation could not be generated: {e}")

        if rec:
            st.write(rec)

st.divider()

# SECTION 5: Word Cloud
st.subheader("☁️ Common words")
st.caption("Most common words from recent journal entries")

if WORDCLOUD_AVAILABLE:
    try:
        # Get journal entries for wordcloud
        db_client_wordcloud = DBClient(user_id=user['id'])
        journal_entries = db_client_wordcloud.get_recent_entries(days=90, limit=100)
        
        if journal_entries:
            # Extract text content from entries
            all_text = ""
            valid_entries = 0
            
            for entry in journal_entries:
                text = entry.get('text', '').strip()
                if text and len(text) > 10:  # Only include entries with substantial content
                    all_text += text + " "
                    valid_entries += 1
            
            if all_text.strip() and valid_entries >= 3:  # Need at least 3 entries with content
                # Create wordcloud with stop words
                stop_words = set([
                    'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'an', 'a', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'shall',
                    'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours', 'yourself', 'yourselves',
                    'he', 'him', 'his', 'himself', 'she', 'her', 'hers', 'herself', 'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves',
                    'this', 'that', 'these', 'those', 'am', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing',
                    'will', 'would', 'should', 'could', 'ought', 'i\'m', 'you\'re', 'he\'s', 'she\'s', 'it\'s', 'we\'re', 'they\'re', 'i\'ve', 'you\'ve', 'we\'ve', 'they\'ve',
                    'i\'d', 'you\'d', 'he\'d', 'she\'d', 'we\'d', 'they\'d', 'i\'ll', 'you\'ll', 'he\'ll', 'she\'ll', 'we\'ll', 'they\'ll',
                    'isn\'t', 'aren\'t', 'wasn\'t', 'weren\'t', 'hasn\'t', 'haven\'t', 'hadn\'t', 'doesn\'t', 'don\'t', 'didn\'t', 'won\'t', 'wouldn\'t', 'shan\'t', 'shouldn\'t', 'can\'t', 'cannot', 'couldn\'t',
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
                    min_word_length=3
                ).generate(all_text)
                
                # Display wordcloud
                fig_wordcloud, ax = plt.subplots(figsize=(10, 5))
                ax.imshow(wordcloud, interpolation='bilinear')
                ax.axis('off')
                
                st.pyplot(fig_wordcloud)
                st.caption(f"Based on {valid_entries} journal entries with substantial content")
            else:
                st.info("📝 Need more journal entries with content to generate word cloud. At least 3 entries with meaningful text are required.")
    except Exception as e:
        st.error(f"Error generating word cloud: {str(e)}")
else:
    st.info("📦 Word cloud feature requires additional packages. Install with: `pip install wordcloud matplotlib`")

st.divider()

# SECTION 5: GENTLE GUIDANCE
analysis = analyze_depression(display_df, window_days=30) if not display_df.empty else {"depression_detected": False}
if analysis["depression_detected"]:
    st.info("💛 **Support and care are important.** If you're concerned about this person's well-being, consider reaching out or suggesting professional support.")
    guidance_text = "Support and care are important. If you're concerned about this person's well-being, consider reaching out or suggesting professional support."
else:
    st.info("🌱 **Things look okay.** Continued monitoring and support can make a positive difference.")
    guidance_text = "Things look okay. Continued monitoring and support can make a positive difference."

st.divider()

# EXPORT SECTION - CSV and PDF at bottom
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
        file_name=f"viewer_analysis_{user['name'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        help="Download this user's analysis data",
        use_container_width=True
    )

with export_col2:
    # PDF export
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
        
        # Handle word cloud separately (matplotlib figure)
        wordcloud_img_bytes = None
        if 'fig_wordcloud' in locals():
            try:
                import io
                buf = io.BytesIO()
                fig_wordcloud.savefig(buf, format='png', dpi=100, bbox_inches='tight')
                buf.seek(0)
                wordcloud_img_bytes = buf.getvalue()
            except Exception as e:
                st.warning(f"Could not prepare word cloud for PDF: {e}")

        if collected_figs or wordcloud_img_bytes:
            generated_on = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Keep Key Metrics consistent with the institution dashboard PDF
            metrics = {
                'Recent Emotional Distress Level': f"{user_overall_analysis.get('overall_severity', 'N/A')}",
                'Recent Trend': f"{user_overall_analysis.get('trend_direction', 'Stable')}",
                'Current Streak': f"{streak} days",
                'Recent Mood': f"{display_sentiment_label}",
            }

            pdf_title = f"Well-being Report - {user['name']} (Generated on {generated_on})"

            # Generate AI recommendation if depression detected and recommender available
            ai_recommendation = ""
            if user_overall_analysis.get('depression_detected', False) and _RECOMMENDER_AVAILABLE:
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
                        str(user_overall_analysis.get('overall_severity', 'N/A')),
                        str(user_overall_analysis.get('trend_direction', 'Stable')),
                    )
                    if rec:
                        ai_recommendation = rec
                except Exception as e:
                    # If AI recommendation fails, just skip it for PDF
                    pass

            with st.spinner("Preparing PDF report..."):
                # Prepare images list for matplotlib figures
                images = []
                if wordcloud_img_bytes:
                    images.append({
                        'bytes': wordcloud_img_bytes,
                        'title': 'Common Words in Journal Entries'
                    })
                
                pdf_bytes = figs_to_pdf_bytes(
                    collected_figs,
                    title=pdf_title,
                    status_text=status_text,
                    metrics=metrics,
                    guidance=guidance_text,
                    ai_recommendation=ai_recommendation,
                    images=images,
                )
            if pdf_bytes:
                st.download_button(
                    label="📊 Download PDF Report",
                    data=pdf_bytes,
                    file_name=f"viewer_analysis_{user['name'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
        else:
            st.info("No charts available for PDF export")
    except ImportError as ie:
        st.error(str(ie))
    except Exception as e:
        st.error(f"PDF export error: {e}")

"""
History page - Browse all journal entries and their assessments
"""

import streamlit as st
from datetime import datetime, timedelta
import sys
from pathlib import Path
import time
import hashlib

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from utils.db_client import DBClient
from utils.auth import init_auth_service
from utils.auth_sidebar import render_auth_sidebar

# Add backend path for imports
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.append(str(backend_path))

from model.preprocess import validate_and_clean_entry, clean_entry

# Import backend modules for immediate BDI analysis
from model.llm_model import BDIAssessmentModel
from utils.score_bdi import calculate_total_score, get_depression_category
from model.sentiment_model import SentimentAnalyzer

# Page config
st.set_page_config(
    page_title="My History",
    page_icon="📜",
    layout="wide"
)

# Initialize auth and render auth-aware sidebar
auth_service = init_auth_service()
render_auth_sidebar(auth_service)

# Enforce only individual users can access history
auth_service.require_role(['individual'])

# Initialize client with authenticated user id
current_user = auth_service.get_current_user()
if not current_user:
    st.error("Authentication required")
    st.stop()

user_id = current_user['id']
db_client = DBClient(user_id=user_id)

# Dialog functions for edit and delete operations
@st.dialog("Edit Entry - Please stay on the page while analysis completes.")
def edit_entry_dialog(entry):
    """Dialog for editing a journal entry"""
    # Edit text area (following Journal page format)
    edited_text = st.text_area(
        "💡 Tip: Aim for 200-400 words for meaningful insights",
        value=entry['text'],
        height=200,
        placeholder="Write about your day, your thoughts, feelings, or anything on your mind...",
        help="Your entries are private and will be analyzed to help understand your mood patterns.",
        key=f"edit_text_{entry['id']}"
    )

    # Real-time word counter (following Journal page format)
    if edited_text:
        word_count = len(edited_text.split())
        max_words = 400

        if word_count > max_words:
            st.write(f"⚠️ **{word_count} / {max_words} words** - Please keep your entry under {max_words} words")
        elif word_count > max_words * 0.9:  # Warning at 90%
            st.write(f"📝 **{word_count} / {max_words} words** - Approaching word limit")
        else:
            st.write(f"📝 **{word_count} / {max_words} words**")
    
    # Action buttons
    edit_action_col1, edit_action_col2 = st.columns(2)

    with edit_action_col1:
        if st.button("🕵️‍♂️ Save & Analyse", type="primary", width='stretch'):
            # Validate using centralized validator
            res = validate_and_clean_entry(edited_text)
            proceed_save = False
            cleaned = None

            if isinstance(res, tuple):
                ok, out = res
                if not ok:
                    st.error(out)
                    return  # Stop execution, keep dialog open to show error
                else:
                    cleaned = out
                    proceed_save = True
            else:
                if not getattr(res, 'success', False):
                    st.error(getattr(res, 'message', 'Invalid entry'))
                    return  # Stop execution, keep dialog open to show error
                else:
                    cleaned = res.cleaned_text
                    proceed_save = True
            
            if proceed_save:
                # Store validated text and set flag to start analysis on main page
                st.session_state[f'pending_save_text_{entry["id"]}'] = edited_text
                st.session_state['start_analysis_for_entry'] = entry["id"]
                st.session_state['operation_in_progress'] = True
                st.rerun()

    with edit_action_col2:
        if st.button("❌ Cancel", width='stretch'):
            st.rerun()

@st.dialog("Confirm Deletion")
def delete_entry_dialog(entry):
    """Dialog for confirming entry deletion"""
    st.warning("⚠️ **Confirm Deletion**")
    st.write(f"Are you sure you want to delete the entry from **{entry['date']}**? This action cannot be undone.")

    conf_col1, conf_col2 = st.columns(2)
    with conf_col1:
        if st.button("✅ Yes, Delete", type="primary", width='stretch', disabled=st.session_state.get('operation_in_progress', False)):
            st.session_state['operation_in_progress'] = True
            try:
                # Delete from database
                result = db_client.supabase.table('journal_entries').delete().eq('id', entry['id']).execute()
                # Clear confirmation flag if it exists
                if f"confirm_delete_history_{entry['id']}" in st.session_state:
                    del st.session_state[f"confirm_delete_history_{entry['id']}"]
                # Set success flag and rerun to close dialog and show success message
                st.session_state['delete_success'] = True
                st.rerun()
            except Exception as e:
                st.error(f"Error deleting entry: {str(e)}")
                st.session_state['operation_in_progress'] = False

    with conf_col2:
        if st.button("❌ Cancel", width='stretch', disabled=st.session_state.get('operation_in_progress', False)):
            st.rerun()


@st.dialog("Confirm File Deletion")
def delete_uploaded_file_dialog(uploaded_file: str, entry_ids: list, display_name: str):
    st.warning("⚠️ **Confirm File Deletion**")
    st.write(
        f"Are you sure you want to delete **all {len(entry_ids)} messages** from **{display_name}**? "
        "This action cannot be undone."
    )

    conf_col1, conf_col2 = st.columns(2)
    with conf_col1:
        if st.button(
            "✅ Yes, Delete All",
            type="primary",
            width='stretch',
            disabled=st.session_state.get('operation_in_progress', False),
        ):
            st.session_state['operation_in_progress'] = True
            try:
                # Best-effort cleanup of related tables first
                for entry_id in entry_ids:
                    try:
                        db_client.supabase.table('bdi_assessments').delete().eq('entry_id', entry_id).execute()
                    except Exception:
                        pass
                    try:
                        db_client.supabase.table('sentiment_analysis').delete().eq('entry_id', entry_id).execute()
                    except Exception:
                        pass

                # Delete all journal_entries for this uploaded_file
                db_client.supabase.table('journal_entries')\
                    .delete()\
                    .eq('user_id', db_client.user_id)\
                    .eq('uploaded_file', uploaded_file)\
                    .execute()

                st.session_state['delete_success'] = True
                st.session_state['operation_in_progress'] = False
                st.rerun()
            except Exception as e:
                st.error(f"Error deleting file messages: {str(e)}")
                st.session_state['operation_in_progress'] = False

    with conf_col2:
        if st.button(
            "❌ Cancel",
            width='stretch',
            disabled=st.session_state.get('operation_in_progress', False),
        ):
            st.rerun()

st.title("📜 My History")
st.write("Browse and review all your journal entries and their BDI assessments.")

# Check if any operation is in progress (early check for filters)
is_operation_in_progress = st.session_state.get('operation_in_progress', False) or 'start_analysis_for_entry' in st.session_state

# Filters
col1, col2, col3 = st.columns(3)

with col1:
    date_filter = st.date_input(
        "Filter by Date",
        value=None,
        help="Select a specific date to show entries from that day only",
        disabled=is_operation_in_progress
    )

with col2:
    # Auto-set to "All time" and disable when date is selected
    if date_filter is not None:
        days_filter = "All time"
        st.selectbox(
            "Time Period",
            options=["All time", "Last 30 days", "Last 60 days", "Last 90 days"],
            index=0,  
            help="Disabled when specific date is selected",
            disabled=True
        )
    else:
        days_filter = st.selectbox(
            "Time Period",
            options=["All time", "Last 30 days", "Last 60 days", "Last 90 days"],
            help="Filter entries by date range",
            disabled=is_operation_in_progress
        )

with col3:
    sort_order = st.selectbox(
        "Sort By",
        options=["Newest First", "Oldest First"],
        help="Sort order for entries",
        disabled=is_operation_in_progress
    )

# Fetch entries
try:
    # Map filter to days
    days_map = {
        "Last 30 days": 30,
        "Last 60 days": 60,
        "Last 90 days": 90,
        "All time": None
    }
    days = days_map[days_filter]
    
    # Get entries
    all_entries = db_client.get_recent_entries(days=days, limit=1000)  # Get many entries
    
    # Apply filters
    filtered_entries = all_entries
    
    # Date filter (takes priority)
    if date_filter:
        date_str = date_filter.strftime('%Y-%m-%d')
        filtered_entries = [e for e in filtered_entries if e['date'] == date_str]
    # Time period filter (only when no specific date selected)
    elif days:
        cutoff_date = (datetime.now() - timedelta(days=days)).date()
        filtered_entries = [e for e in filtered_entries if datetime.strptime(e['date'], '%Y-%m-%d').date() >= cutoff_date]
    
    # Sort
    filtered_entries = sorted(
        filtered_entries,
        key=lambda x: (x['date'], x.get('time', '00:00:00')),
        reverse=(sort_order == "Newest First")
    )

    # Filter for entries
    uploaded_entries = [e for e in filtered_entries if e.get('uploaded_file')]
    typed_entries = [e for e in filtered_entries if not e.get('uploaded_file')]

    st.divider()
    
    # Handle pending analysis from edit dialog BEFORE displaying entries
    if 'start_analysis_for_entry' in st.session_state:
        entry_id = st.session_state['start_analysis_for_entry']
        
        # Find the entry in current filtered entries
        entry = next((e for e in filtered_entries if e['id'] == entry_id), None)
        
        if entry:
            with st.spinner("🔄 Updating and analyzing your entry... Please stay on the page while analysis completes."):
                time.sleep(0.5)  # Ensure spinner is visible
                # Perform the analysis
                pending_text = st.session_state.get(f'pending_save_text_{entry_id}')
                if pending_text:
                    try:
                        # Update the entry text in database and set status to pending
                        result = db_client.supabase.table('journal_entries').update({
                            'entry_text': pending_text,
                            'analysis_status': 'pending'
                        }).eq('id', entry_id).execute()
                        
                        if result.data and len(result.data) > 0:
                            # Delete old assessments and sentiments
                            db_client.supabase.table('bdi_assessments').delete().eq('entry_id', entry_id).execute()
                            db_client.supabase.table('sentiment_analysis').delete().eq('entry_id', entry_id).execute()
                            
                            # Clean the text for analysis
                            cleaned_text = clean_entry(pending_text)
                            texts = [cleaned_text] if cleaned_text else [pending_text]
                            
                            # Initialize BDI model and assess
                            bdi_model = BDIAssessmentModel()
                            assessment_results = bdi_model.assess_all_symptoms(texts)
                            
                            # Calculate scores
                            total_score = calculate_total_score(assessment_results)
                            category = get_depression_category(total_score)
                            
                            # Save assessment to database
                            assessment_saved = db_client.save_assessment(
                                entry_id=entry_id,
                                assessment_data=assessment_results,
                                total_score=total_score,
                                category=category
                            )
                            
                            # Perform sentiment analysis
                            try:
                                sentiment_analyzer = SentimentAnalyzer()
                                sentiment_result = sentiment_analyzer.analyze(cleaned_text)
                                
                                if sentiment_result:
                                    # Save sentiment to database
                                    scores = sentiment_result.get('scores', {})
                                    sentiment_data = {
                                        'entry_id': entry_id,
                                        'user_id': db_client.user_id,
                                        'top_label': sentiment_result.get('label'),
                                        'positive_score': float(scores.get('Positive', 0.0)),
                                        'neutral_score': float(scores.get('Neutral', 0.0)),
                                        'negative_score': float(scores.get('Negative', 0.0))
                                    }
                                    
                                    db_client.supabase.table('sentiment_analysis').insert(sentiment_data).execute()
                                    
                            except Exception as e:
                                print(f"Sentiment analysis failed: {e}")
                            
                            # Update entry status to completed
                            db_client.supabase.table('journal_entries').update({
                                'analysis_status': 'completed'
                            }).eq('id', entry_id).execute()
                            
                            # Keep the expander open after analysis
                            st.session_state[f'keep_expanded_{entry_id}'] = True
                        
                    except Exception as e:
                        print(f"Update failed: {e}")
        
        # Clear the analysis flags
        if 'start_analysis_for_entry' in st.session_state:
            del st.session_state['start_analysis_for_entry']
        if f'pending_save_text_{entry_id}' in st.session_state:
            del st.session_state[f'pending_save_text_{entry_id}']
        st.session_state['operation_in_progress'] = False
        
        # Rerun to refresh the page and show updated entries
        st.rerun()
    
    # Create tabs
    tab1, tab2 = st.tabs(["Upload for Analysis", "Quick Entry"])

    with tab1:
        st.subheader("📊 Recent Analyses")
        st.write("Filtered by the date or time of the messages.")

        if uploaded_entries:
            from collections import defaultdict

            # Group by uploaded_file
            grouped = defaultdict(list)
            for entry in uploaded_entries:
                file_key = entry.get('uploaded_file', 'Unknown')
                grouped[file_key].append(entry)

            # Sort files by upload timestamp (extracted from filename)
            def get_file_timestamp(file_name):
                """Extract timestamp from filename for sorting"""
                if '_' in file_name and len(file_name) > 16:
                    timestamp_part = file_name[-15:]  # Last 15 chars should be timestamp
                    try:
                        # Parse YYYYMMDD_HHMMSS format
                        year = int(timestamp_part[:4])
                        month = int(timestamp_part[4:6])
                        day = int(timestamp_part[6:8])
                        hour = int(timestamp_part[9:11])
                        minute = int(timestamp_part[11:13])
                        second = int(timestamp_part[13:])
                        return (year, month, day, hour, minute, second)
                    except (ValueError, IndexError):
                        return (0, 0, 0, 0, 0, 0)  # Default for unparseable
                return (0, 0, 0, 0, 0, 0)  # Default for files without timestamp

            # Sort files by timestamp (newest first or oldest first based on sort_order)
            sorted_files = sorted(
                grouped.keys(),
                key=get_file_timestamp,
                reverse=(sort_order == "Newest First")
            )

            for file_name in sorted_files:
                entries = grouped[file_name]

                # Sort entries within each file by date and time
                entries = sorted(
                    entries,
                    key=lambda x: (x['date'], x.get('time', '00:00:00')),
                    reverse=(sort_order == "Newest First")
                )
                # Extract original file name and timestamp
                if '_' in file_name and len(file_name) > 16:
                    file_base = file_name[:-16]
                    timestamp = file_name[-15:]
                    try:
                        year = timestamp[:4]
                        month = timestamp[4:6]
                        day = timestamp[6:8]
                        hour = timestamp[9:11]
                        minute = timestamp[11:13]
                        second = timestamp[13:]
                        formatted_datetime = f"{year}-{month}-{day} {hour}:{minute}:{second}"
                        display_name = f"{file_base} (uploaded by {formatted_datetime})"
                    except:
                        display_name = file_name
                else:
                    display_name = file_name

                with st.expander(f"📁 {display_name}"):
                    # Collect data for averages and table
                    table_data = []
                    total_scores = []
                    pos_scores = []
                    neu_scores = []
                    neg_scores = []

                    for entry in entries:
                        assessment = db_client.get_assessment_by_entry(entry['id'])
                        sentiment = db_client.get_sentiment_by_entry(entry['id'])

                        dep_cat = assessment['category'] if assessment else 'N/A'
                        sent_label = sentiment['top_label'] if sentiment else 'N/A'

                        # Format time as HH:MM
                        entry_time = entry.get('time', '00:00:00')
                        if entry_time and ':' in entry_time:
                            time_parts = entry_time.split(':')
                            entry_time_formatted = f"{time_parts[0]}:{time_parts[1]}"
                        else:
                            entry_time_formatted = "N/A"

                        table_data.append({
                            'Date': entry['date'],
                            'Time': entry_time_formatted,
                            'Message': entry['text'][:50] + '...' if len(entry['text']) > 50 else entry['text'],
                            'Depression Level': dep_cat,
                            'Sentiment': sent_label
                        })

                        if assessment:
                            total_scores.append(assessment['total_score'])
                        if sentiment:
                            pos_scores.append(sentiment['positive_score'])
                            neu_scores.append(sentiment['neutral_score'])
                            neg_scores.append(sentiment['negative_score'])

                    # Average results
                    if total_scores:
                        avg_score = sum(total_scores) / len(total_scores)
                        avg_category = get_depression_category(avg_score)
                    else:
                        avg_category = 'N/A'

                    if pos_scores:
                        avg_pos = sum(pos_scores) / len(pos_scores)
                        avg_neu = sum(neu_scores) / len(neu_scores)
                        avg_neg = sum(neg_scores) / len(neg_scores)

                        # Determine top sentiment
                        if avg_pos > avg_neu and avg_pos > avg_neg:
                            avg_sentiment = 'Positive'
                        elif avg_neu > avg_pos and avg_neu > avg_neg:
                            avg_sentiment = 'Neutral'
                        else:
                            avg_sentiment = 'Negative'
                    else:
                        avg_sentiment = 'N/A'

                    # Conclusion like Tab 2
                    sentiment_messages = {
                        "Positive": "<strong>Positive</strong> mood 😊",
                        "Neutral": "<strong>Neutral</strong> mood 😐",
                        "Negative": "<strong>Low</strong> mood 😔"
                    }
                    sentiment_text = sentiment_messages.get(avg_sentiment, "Mood analysis unavailable 💭")

                    category_messages = {
                        "Minimal": "<strong>No signs</strong> of depressive symptoms",
                        "Mild": "<strong>Mild</strong> depressive symptoms detected",
                        "Moderate": "<strong>Moderate</strong> depressive symptoms detected",
                        "Severe": "<strong>Severe</strong> depressive symptoms detected"
                    }
                    category_message = category_messages.get(avg_category, avg_category)

                    result_text = f"""{category_message}
{sentiment_text}"""

                    # Color-coded conclusion box
                    if avg_category == "Minimal":
                        st.markdown(f'<div style="background-color: #f0f9f0; color: #2d5a2d; padding: 10px; border-radius: 5px; border-left: 5px solid #4caf50;">{result_text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                    elif avg_category == "Mild":
                        st.markdown(f'<div style="background-color: #fefde7; color: #bf360c; padding: 10px; border-radius: 5px; border-left: 5px solid #ffb74d;">{result_text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                    elif avg_category == "Moderate":
                        st.markdown(f'<div style="background-color: #fff4e6; color: #c62828; padding: 10px; border-radius: 5px; border-left: 5px solid #ff7043;">{result_text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                    elif avg_category == "Severe":
                        st.markdown(f'<div style="background-color: #fef2f2; color: #ad1457; padding: 10px; border-radius: 5px; border-left: 5px solid #e91e63;">{result_text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div style="background-color: #f0f8ff; color: #1565c0; padding: 10px; border-radius: 5px; border-left: 5px solid #42a5f5;">{result_text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)

                    # Table: Message, Depression, Sentiment
                    st.write("")
                    st.dataframe(table_data, width='stretch', hide_index=True)

                    st.write("")
                    key_suffix = hashlib.md5(file_name.encode('utf-8')).hexdigest()[:10]
                    if st.button(
                        "🗑️ Delete this file",
                        key=f"delete_uploaded_file_{key_suffix}",
                        type="secondary",
                        width='stretch',
                        disabled=is_operation_in_progress,
                    ):
                        delete_uploaded_file_dialog(
                            uploaded_file=file_name,
                            entry_ids=[e['id'] for e in entries],
                            display_name=display_name,
                        )
        else:
            st.info("No recent analyses. Upload and analyze a file to see results here!")

    with tab2:
        if typed_entries:
            st.subheader(f"{len(typed_entries)} Entries Found 📋")
            
            for entry in typed_entries:
                # Format time as HH:MM
                entry_time = entry.get('time', '00:00:00')
                if entry_time and ':' in entry_time:
                    time_parts = entry_time.split(':')
                    entry_time_formatted = f"{time_parts[0]}:{time_parts[1]}"
                else:
                    entry_time_formatted = "N/A"
                
                # Make the entry clickable - navigate to detail page
                display_title = f"📅 {entry['date']}  \n⏰ {entry_time_formatted}"
                
                with st.expander(display_title, expanded=(st.session_state.get(f'keep_expanded_{entry["id"]}', False))):
                    # Always show the entry text
                    st.write(entry['text'])
                    
                    # Show BDI score if available
                    assessment = db_client.get_assessment_by_entry(entry['id'])
                    sentiment = db_client.get_sentiment_by_entry(entry['id'])
                    
                    if assessment:
                        category = assessment['category']
                        
                        # Prepare sentiment text
                        if sentiment:
                            sentiment_label = sentiment.get('top_label', 'Unknown')
                            sentiment_score = sentiment.get('positive_score', 0) if sentiment_label == 'Positive' else \
                                            sentiment.get('neutral_score', 0) if sentiment_label == 'Neutral' else \
                                            sentiment.get('negative_score', 0)
                            
                            sentiment_messages = {
                                "Positive": "<strong>Positive</strong> mood 😊",
                                "Neutral": "<strong>Neutral</strong> mood 😐",
                                "Negative": "<strong>Low</strong> mood 😔"
                            }
                            
                            sentiment_text = sentiment_messages.get(sentiment_label, sentiment_label)
                        else:
                            sentiment_text = "Mood analysis unavailable 💭"
                        
                        # Format the result text
                        category_messages = {
                            "Minimal": "<strong>No signs</strong> of depressive symptoms",
                            "Mild": "<strong>Mild</strong> depressive symptoms detected",
                            "Moderate": "<strong>Moderate</strong> depressive symptoms detected",
                            "Severe": "<strong>Severe</strong> depressive symptoms detected"
                        }
                        
                        category_message = category_messages.get(category, category)
                        
                        result_text = f"""{category_message}
{sentiment_text}"""
                        
                        # Display with same color coding as main analysis
                        if category == "Minimal":
                            st.markdown(f'<div style="background-color: #f0f9f0; color: #2d5a2d; padding: 10px; border-radius: 5px; border-left: 5px solid #4caf50;">{result_text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                        elif category == "Mild":
                            st.markdown(f'<div style="background-color: #fefde7; color: #bf360c; padding: 10px; border-radius: 5px; border-left: 5px solid #ffb74d;">{result_text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                        elif category == "Moderate":
                            st.markdown(f'<div style="background-color: #fff4e6; color: #c62828; padding: 10px; border-radius: 5px; border-left: 5px solid #ff7043;">{result_text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                        elif category == "Severe":
                            st.markdown(f'<div style="background-color: #fef2f2; color: #ad1457; padding: 10px; border-radius: 5px; border-left: 5px solid #e91e63;">{result_text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                        else:
                            st.markdown(f'<div style="background-color: #f0f8ff; color: #1565c0; padding: 10px; border-radius: 5px; border-left: 5px solid #42a5f5;">{result_text.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                        
                        st.write("")  # Add space after result
                    
                    # Action buttons - only show if analysis is completed
                    analysis_status = entry.get('analysis_status', 'pending')
                    if analysis_status == 'completed':
                        action_col1, action_col2 = st.columns(2)
                        
                        with action_col1:
                            if st.button("✏️ Edit", key=f"edit_{entry['id']}", type="secondary", width='stretch', disabled=is_operation_in_progress):
                                edit_entry_dialog(entry)
                        
                        with action_col2:
                            if st.button("🗑️ Delete", key=f"delete_{entry['id']}", type="secondary", width='stretch', disabled=is_operation_in_progress):
                                delete_entry_dialog(entry)
                    else:
                        st.info("⏳ Analysis in progress... Come back later to see the results.")
        
        else:
            st.info("📭 No entries found matching your filters. Try adjusting the filters above.")
    
    # Handle delete success message
    if st.session_state.get('delete_success', False):
        st.success("✅ Entry deleted successfully!")
        st.session_state['delete_success'] = False
        st.session_state['operation_in_progress'] = False
        st.rerun()

except Exception as e:
    st.error(f"Error loading entries: {str(e)}")# Sidebar tips
# with st.sidebar:
#     st.subheader("💡 History Tips")
#     st.write("""
#     - Use date filter to find entries from specific days
#     - Use time period to browse recent entries
#     - Click "View Details" to see full entry and analysis
#     - Track your progress over time
#     - Review patterns in your mood scores
#     """)
    
#     st.divider()
    
#     st.subheader("📊 Understanding BDI Scores")
#     st.write("""
#     **Score Ranges:**
#     - 0-9: Minimal depression
#     - 10-18: Mild depression
#     - 19-29: Moderate depression
#     - 30-63: Severe depression
    
#     **Severity Levels:**
#     - 🟢 None (0)
#     - 🟡 Mild (1)
#     - 🟠 Moderate (2)
#     - 🔴 Severe (3)
#     """)


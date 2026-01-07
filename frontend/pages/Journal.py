"""
Journal page - User input for daily reflections
"""

import streamlit as st
from datetime import datetime
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from utils.db_client import DBClient
from utils.auth import init_auth_service
from utils.auth_sidebar import render_auth_sidebar

# Add backend path for imports
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.append(str(backend_path))

from model.preprocess import validate_and_clean_entry

# Import backend modules for immediate BDI analysis
from model.llm_model import BDIAssessmentModel
from model.preprocess import clean_entry
from utils.score_bdi import calculate_total_score, get_depression_category
from model.sentiment_model import SentimentAnalyzer

# Page config
st.set_page_config(
    page_title="Daily Journal",
    page_icon="📝",
    layout="wide"
)

# Initialize auth and render auth-aware sidebar
auth_service = init_auth_service()
render_auth_sidebar(auth_service)

# Enforce only individual users can access Journal
auth_service.require_role(['individual'])

# Initialize client with authenticated user id
current_user = auth_service.get_current_user()
if not current_user:
    st.error("Authentication required")
    st.stop()

user_id = current_user['id']
db_client = DBClient(user_id=user_id)

st.title("📝 Daily Journal")
st.write("Share your thoughts and feelings. Your entries help track your mental well-being over time.")

# Main journal input
st.subheader("How are you feeling today?")

journal_text = st.text_area(
    "💡 Tip: Aim for 200-400 words for meaningful insights",
    height=200,
    placeholder="Write about your day, your thoughts, feelings, or anything on your mind...",
    help="Your entries are private and will be analyzed to help understand your mood patterns.",
    key="journal_input"
)

# Real-time word counter
if journal_text:
    word_count = len(journal_text.split())
    max_words = 400
    
    if word_count > max_words:
        st.write(f"⚠️ **{word_count} / {max_words} words** - Please keep your entry under {max_words} words")
    elif word_count > max_words * 0.9:  # Warning at 90%
        st.write(f"📝 **{word_count} / {max_words} words** - Approaching word limit")
    else:
        st.write(f"📝 **{word_count} / {max_words} words**")
else:
    pass

# Create placeholder immediately below text box for loading and results
result_placeholder = st.empty()

# Clear analysis results if text has changed
if 'last_analyzed_text' in st.session_state and 'latest_analysis_result' in st.session_state:
    if st.session_state['last_analyzed_text'] != journal_text:
        # Text has changed, clear the results
        del st.session_state['latest_analysis_result']
        del st.session_state['last_analyzed_text']

# Display stored analysis results if they exist
if 'latest_analysis_result' in st.session_state and st.session_state['latest_analysis_result']:
    result_data = st.session_state['latest_analysis_result']
    
    # Display the stored result
    category = result_data.get('category')
    sentiment_label = result_data.get('sentiment_label')
    
    # Prepare sentiment text
    if sentiment_label:
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
    
    # Display with color based on BDI category
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
    
    st.write("")

# Save button appears here
save_button_container = st.container()

# # Entry metadata
# col1, col2 = st.columns(2)

# with col1:
#     entry_date = st.date_input(
#         "Date",
#         value=datetime.now(),
#         help="Date of this journal entry"
#     )

# with col2:
#     entry_time = st.time_input(
#         "Time",
#         value=datetime.now().time(),
#         help="Time of this journal entry"
#     )
# # Entry metadata (generated fresh on each save to ensure unique IDs)
# entry_date = datetime.now()
# entry_time = datetime.now().time()
# entry_datetime = datetime.combine(entry_date, entry_time).replace(microsecond=0)


def validate_entry(text: str):
    """
    Validate journal entry via backend `validate_and_clean_entry`.

    Returns a `ValidationResult` (preferred) or the legacy (bool, str) tuple.
    """
    return validate_and_clean_entry(text)


# Only one button now - Save button (placed in container after results area)
with save_button_container:
    save_clicked = st.button("🕵️‍♂️ Save & Analyse", type="secondary", width='stretch')

if save_clicked:
    # Generate completely fresh datetime for each save to ensure unique ID generation
    entry_datetime = datetime.combine(datetime.now(), datetime.now().time()).replace(microsecond=0)
    
    result_placeholder.empty()  # Clear previous results when saving again
    res = validate_entry(journal_text)

    # Handle old tuple-based result or new ValidationResult
    if isinstance(res, tuple):
        is_valid, result = res
        if not is_valid:
            st.error(result)
            # stop here
            pass
        else:
            cleaned_text = result
            proceed_save = True
    else:
        # assume ValidationResult
        if not getattr(res, 'success', False):
            st.error(getattr(res, 'message', 'Invalid entry'))
            proceed_save = False
            cleaned_text = None
        else:
            cleaned_text = res.cleaned_text
            proceed_save = True

    if not cleaned_text or not proceed_save:
        # nothing to do
        pass
    else:
        # Show spinning loading when user saves entry successfully
        with result_placeholder:
            with st.spinner("Saving your entry..."):
                # Save the original user text to the DB
                entry_id = db_client.save_journal_entry(
                    text=journal_text,
                    entry_date=entry_datetime
                )

        if entry_id:
            # Show spinning loading for analysis
            # Initialize result variables
            assessment_saved = False
            category = None
            sentiment_result = None
            
            with result_placeholder:
                with st.spinner("🔍 Analyzing your entry... Please stay on the page while analysis completes."):
                    try:
                        # Clean the text for analysis
                        cleaned_text = clean_entry(journal_text)
                        texts = [cleaned_text] if cleaned_text else [journal_text]
                        
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
                                print(f"✅ Sentiment saved: {sentiment_result.get('label')}")
                        except Exception as e:
                            print(f"⚠️ Sentiment analysis error: {e}")
                            sentiment_result = None
                        
                        # Update entry status to completed
                        db_client.supabase.table('journal_entries').update({
                            'analysis_status': 'completed'
                        }).eq('id', entry_id).execute()
                        
                    except Exception as e:
                        print(f"❌ Immediate analysis error: {e}")
                        assessment_saved = False
                        category = None
                        sentiment_result = None
            
            # Store the result in session state for persistent display
            if assessment_saved and category:
                # Store results in session state
                st.session_state['latest_analysis_result'] = {
                    'category': category,
                    'sentiment_label': sentiment_result.get('label') if sentiment_result else None
                }
                # Store the analyzed text to track changes
                st.session_state['last_analyzed_text'] = journal_text
                # Rerun to display the results
                st.rerun()
                # Note: Cannot clear input here due to Streamlit session state restrictions
                # User can manually clear the input or we can implement a different approach
            else:
                with result_placeholder:
                    st.warning("Entry saved but analysis couldn't be completed. Results will be available soon.")
        else:
            with result_placeholder:
                st.error("Failed to save entry. Please try again.")

# Display recent entries
st.divider()
st.subheader("📖 Recent Entries")

recent_entries = db_client.get_recent_entries(days=None, limit=5)

if recent_entries:
    for entry in recent_entries:
        # Format date and time for display
        entry_time = entry.get('time', 'N/A')
        # Format time to show only HH:MM (remove seconds)
        if entry_time != 'N/A' and ':' in entry_time:
            time_parts = entry_time.split(':')
            entry_time = f"{time_parts[0]}:{time_parts[1]}"  # HH:MM
        
        # Simple title with date and time
        display_title = f"📅 {entry['date']}  \n⏰ {entry_time}"
        
        with st.expander(display_title):
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
                
                # Format the result text (same as main analysis)
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
                
                st.write("")  
else:
    st.info("No recent entries. Start writing to track your well-being!")

# Helpful tips
# with st.sidebar:
#     st.subheader("💡 Journaling Tips")
#     st.write("""
#     - Write regularly for better insights
#     - Be honest about your feelings
#     - Include specific events or thoughts
#     - Note physical sensations
#     - Mention sleep and appetite changes
#     - Track what helps you feel better
#     """)
    
#     st.subheader("� Analysis Options")
#     st.write("""
#     **Save Only:**
#     - Quick save, analyze later
#     - Can navigate away immediately
#     - Analyze anytime from Report page
    
#     **Save & Analyze Now:**
#     - Analyzes immediately
#     - ⚠️ Takes about 1 minute
#     - ⚠️ Must stay on this page
#     - Shows results right away
#     """)
    
#     st.subheader("�🔒 Privacy")
#     st.write("""
#     Your journal entries are:
#     - Stored securely
#     - Never shared with others
#     - Used only for your personal insights
#     - Analyzed by AI to help you understand patterns
#     """)

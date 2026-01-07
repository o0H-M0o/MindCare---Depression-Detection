import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def _get_secret(key: str) -> str | None:
    """Read config from env first, then Streamlit secrets if available."""
    val = os.getenv(key)
    if val:
        return val
    try:
        import streamlit as st

        # st.secrets behaves like a dict
        return st.secrets.get(key)  # type: ignore[attr-defined]
    except Exception:
        return None

class Config:
    """Application configuration"""
    
    # Gemini API Configuration
    GOOGLE_API_KEY = _get_secret('GOOGLE_API_KEY')
    GEMINI_MODEL = 'gemma-3-27b-it'  
    
    # Model Generation Config
    TEMPERATURE = 0.1
    TOP_P = 0.7
    TOP_K = 10
    
    # Supabase Configuration
    SUPABASE_URL = _get_secret('SUPABASE_URL')
    SUPABASE_KEY = _get_secret('SUPABASE_KEY')
    
    # BDI Configuration
    BDI_QUESTIONS = 21
    MAX_SCORE_PER_QUESTION = 3
    MAX_TOTAL_SCORE = BDI_QUESTIONS * MAX_SCORE_PER_QUESTION  
    
    # Depression Categories
    CATEGORIES = {
        'Minimal': (0, 9),
        'Mild': (10, 18),
        'Moderate': (19, 29),
        'Severe': (30, 63)
    }

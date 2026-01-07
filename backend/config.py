import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Application configuration"""
    
    # Gemini API Configuration
    GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
    GEMINI_MODEL = 'gemma-3-27b-it'  
    
    # Model Generation Config
    TEMPERATURE = 0.1
    TOP_P = 0.7
    TOP_K = 10
    
    # Supabase Configuration
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')
    
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

"""
Utilities for BDI scoring and depression categorization
"""

from typing import Dict, List
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from config import Config


def calculate_total_score(assessment_results: Dict[str, Dict]) -> int:
    """
    Calculate total BDI score from assessment results
    
    Args:
        assessment_results: Dictionary with question IDs and their levels
        
    Returns:
        Total score (0-63)
    """
    total = 0
    for qid, data in assessment_results.items():
        if isinstance(data, dict):
            level = data.get('level', 0)
        else:
            level = data if data is not None else 0
        total += level
        
    return min(total, Config.MAX_TOTAL_SCORE)  # Cap at 63


def get_depression_category(score: int) -> str:
    """
    Determine depression category based on BDI score
    
    Args:
        score: Total BDI score (0-63)
        
    Returns:
        Category name: 'Minimal', 'Mild', 'Moderate', or 'Severe'
    """
    for category, (min_score, max_score) in Config.CATEGORIES.items():
        if min_score <= score <= max_score:
            return category
    return 'Unknown'


def get_category_info(category: str) -> Dict:
    """
    Get detailed information about a depression category
    
    Args:
        category: Category name
        
    Returns:
        Dictionary with category details
    """
    category_descriptions = {
        'Minimal': {
            'description': 'These ups and downs are considered normal.',
            'color': '#28a745',  # Green
            'recommendation': 'Continue maintaining healthy habits and self-care.'
        },
        'Mild': {
            'description': 'Mild mood disturbance. Consider monitoring your mood.',
            'color': '#ffc107',  # Yellow
            'recommendation': 'Consider speaking with a mental health professional if symptoms persist.'
        },
        'Moderate': {
            'description': 'Moderate depression. Professional support recommended.',
            'color': '#ff9800',  # Orange
            'recommendation': 'We recommend seeking professional help from a therapist or counselor.'
        },
        'Severe': {
            'description': 'Severe depression. Please seek professional help.',
            'color': '#dc3545',  # Red
            'recommendation': 'Please contact a mental health professional immediately. You don\'t have to face this alone.'
        }
    }
    
    return category_descriptions.get(category, {
        'description': 'Unable to determine category',
        'color': '#6c757d',
        'recommendation': 'Please consult with a healthcare professional.'
    })


def analyze_symptom_breakdown(assessment_results: Dict[str, Dict]) -> Dict:
    """
    Analyze which symptoms are most severe
    
    Args:
        assessment_results: Dictionary with question IDs and their levels
        
    Returns:
        Dictionary with symptom analysis
    """
    severe_symptoms = []  # Level 3
    moderate_symptoms = []  # Level 2
    mild_symptoms = []  # Level 1
    
    for qid, data in assessment_results.items():
        level = data.get('level', 0)
        symptom = data.get('symptom', qid)
        
        if level == 3:
            severe_symptoms.append(symptom)
        elif level == 2:
            moderate_symptoms.append(symptom)
        elif level == 1:
            mild_symptoms.append(symptom)
    
    return {
        'severe': severe_symptoms,
        'moderate': moderate_symptoms,
        'mild': mild_symptoms,
        'total_symptoms_present': len(severe_symptoms) + len(moderate_symptoms) + len(mild_symptoms)
    }


def calculate_trend(scores: List[Dict]) -> Dict:
    """
    Calculate trend from historical scores
    
    Args:
        scores: List of score dictionaries with 'date' and 'score' keys
        
    Returns:
        Dictionary with trend information
    """
    if len(scores) < 2:
        return {
            'trend': 'insufficient_data',
            'change': 0,
            'percentage_change': 0
        }
    
    # Sort by date
    sorted_scores = sorted(scores, key=lambda x: x['date'])
    
    # Compare most recent with previous
    latest_score = sorted_scores[-1]['score']
    previous_score = sorted_scores[-2]['score']
    
    change = latest_score - previous_score
    percentage_change = (change / previous_score * 100) if previous_score > 0 else 0
    
    if change > 5:
        trend = 'increasing'
    elif change < -5:
        trend = 'decreasing'
    else:
        trend = 'stable'
    
    return {
        'trend': trend,
        'change': change,
        'percentage_change': round(percentage_change, 1)
    }

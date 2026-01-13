"""
Text preprocessing utilities for journal entries
"""

import re
from typing import Optional
from dataclasses import dataclass


@dataclass
class ValidationResult:
    success: bool
    cleaned_text: Optional[str] = None
    message: Optional[str] = None
    code: Optional[str] = None
    word_count: Optional[int] = None


def clean_entry(text: str) -> Optional[str]:
    """
    Clean and validate a journal entry text
    
    Args:
        text: Raw journal entry text
        
    Returns:
        Cleaned text or None if invalid
    """
    # 1. Check if text exists and is not empty
    if not text or not text.strip():
        return None
    
    text = text.strip()
    
    # 2. Remove very short texts (likely accidental submissions)
    if len(text) < 5:  # More lenient than 15 for journal entries
        return None
    
    # 3. Remove URLs (not needed in journal entries)
    text = re.sub(r'https?://\S+|www\.\S+', '', text)
    text = re.sub(r'\[.*?\]\(.*?\)', '', text)  # Markdown links
    
    # 4. Remove excessive punctuation (but keep emotional expressions)
    text = re.sub(r'[!?]{4,}', '!!!', text)  # Keep some emphasis, limit to 3
    text = re.sub(r'\.{4,}', '...', text)
    
    # 5. Check for only symbols/numbers (likely not a valid entry)
    if re.match(r'^[\s\W]*$', text) or re.match(r'^[0-9\s\.]+$', text):
        return None
    
    # 6. Clean up whitespace (preserve paragraph breaks if any)
    text = re.sub(r'[ \t]+', ' ', text)  # Multiple spaces/tabs to single space
    text = re.sub(r'\n{3,}', '\n', text)  # Limit line breaks 
    text = text.strip()
    
    # 7. Final validation - must have actual content
    words = text.split()
    if len(words) < 2:  # At least 2 words
        return None
    
    return text


def validate_and_clean_entry(text: str, *, min_chars: int = 5, min_words: int = 2, max_words: int = 400) -> ValidationResult:
    """
    Validate and clean a journal entry in one place.

    Returns:
        (True, cleaned_text) on success
        (False, error_message) on failure
    """
    # Run the core cleaner which handles emptiness, urls, punctuation and short texts
    cleaned = clean_entry(text)
    if not cleaned:
        return ValidationResult(success=False, message="⚠️ Please write a meaningful entry (at least a few words, not only symbols or URLs).", code="NO_CONTENT")

    # Additional UI-level checks
    if len(cleaned) < min_chars:
        return ValidationResult(success=False, message=f"⚠️ Entry too short. Please write at least {min_chars} characters.", code="TOO_SHORT")

    words = cleaned.split()
    if len(words) < min_words:
        return ValidationResult(success=False, message=f"⚠️ Entry too short. Please write at least {min_words} words.", code="TOO_FEW_WORDS")

    if len(words) > max_words:
        return ValidationResult(success=False, message=f"⚠️ Entry too long ({len(words)} words). Please keep it under {max_words} words.", code="TOO_LONG", word_count=len(words))

    return ValidationResult(success=True, cleaned_text=cleaned, word_count=len(words))





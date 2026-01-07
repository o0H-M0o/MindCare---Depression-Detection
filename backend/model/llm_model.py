"""
LLM-based BDI assessment model using Google Gemini API
"""

import google.generativeai as genai
from typing import Tuple, List, Dict, Optional
import re
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from config import Config
from model.prompt_template import build_messages, build_batch_messages, REPHRASED_BDI


class BDIAssessmentModel:
    """Model for assessing BDI levels using Gemini LLM"""
    
    def __init__(self):
        """Initialize the Gemini model with API key"""
        genai.configure(api_key=Config.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel(Config.GEMINI_MODEL)
        
    def predict_level(self, symptom: str, texts: List[str], max_retries: int = 5) -> Tuple[Optional[int], Optional[str]]:
        """
        Predict the depression level for a specific symptom with retry logic
        
        Args:
            symptom: The BDI symptom description
            texts: List of user's journal entries or posts
            max_retries: Maximum number of retries on rate limit error
            
        Returns:
            Tuple of (level, reason) where level is 0-3 and reason is explanation
        """
        # Build the message for the model
        messages = build_messages(symptom, texts)
        
        for attempt in range(max_retries):
            try:
                # Generate response from Gemini
                response = self.model.generate_content(
                    messages,
                    generation_config=genai.GenerationConfig(
                        temperature=Config.TEMPERATURE,
                        top_p=Config.TOP_P,
                        top_k=Config.TOP_K
                    )
                )
                
                # Parse the response
                level, reason = self._parse_response(response.text)
                
                # Validate level is in range 0-3
                if level is not None and (level < 0 or level > 3):
                    level = None
                    
                return level, reason
                
            except Exception as e:
                error_msg = str(e).lower()
                
                # Check if it's a 429 rate limit error or 504 Deadline Exceeded error
                if '429' in error_msg or '504' in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 5  # 5s, 10s, 15s
                        print(f"Rate limit hit. Waiting {wait_time}s before retry {attempt + 1}/{max_retries}...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"Max retries reached. Error: {e}")
                        return None, f"Rate limit exceeded: {str(e)}"
                else:
                    # Other error, don't retry
                    print(f"Error in predict_level: {str(e)}")
                    return None, f"Error: {str(e)}"
        
        return None, "Max retries exceeded"
    
    def _parse_batch_response(self, response_text: str) -> Dict[str, Dict]:
        """
        Parse the batch LLM response to extract all symptom assessments
        
        Args:
            response_text: Raw batch response from the model
            
        Returns:
            Dictionary with question IDs as keys and {level, reason} as values
        """
        results = {}
        
        for line in response_text.splitlines():
            line = line.strip()
            
            # Look for Q{N}_LEVEL and Q{N}_REASON patterns
            for i in range(1, 22):  # Q1 to Q21
                qid = f"Q{i}"
                level_key = f"{qid}_LEVEL:"
                reason_key = f"{qid}_REASON:"
                
                if line.startswith(level_key):
                    try:
                        level_str = line.split(":", 1)[1].strip()
                        level = int(level_str)
                        # Validate level is in range 0-3
                        if level < 0 or level > 3:
                            level = 0
                        results[qid] = results.get(qid, {})
                        results[qid]['level'] = level
                    except (ValueError, IndexError):
                        results[qid] = results.get(qid, {})
                        results[qid]['level'] = 0
                        
                elif line.startswith(reason_key):
                    try:
                        reason = line.split(":", 1)[1].strip()
                        results[qid] = results.get(qid, {})
                        results[qid]['reason'] = reason
                    except IndexError:
                        results[qid] = results.get(qid, {})
                        results[qid]['reason'] = "Unable to assess"
        
        # Fill in any missing entries with defaults
        for qid in REPHRASED_BDI.keys():
            if qid not in results:
                results[qid] = {
                    'level': 0,
                    'reason': 'Unable to assess'
                }
            else:
                # Ensure both level and reason exist
                if 'level' not in results[qid]:
                    results[qid]['level'] = 0
                if 'reason' not in results[qid]:
                    results[qid]['reason'] = 'Unable to assess'
        
        return results
    
    def assess_all_symptoms_batch(self, texts: List[str], max_retries: int = 3) -> Dict[str, Dict]:
        """
        Assess all 21 BDI symptoms in a single LLM request with retry logic
        
        Args:
            texts: List of user's journal entries
            max_retries: Maximum number of retries on rate limit error
            
        Returns:
            Dictionary with question IDs as keys and {level, reason} as values
        """
        messages = build_batch_messages(texts)
        
        for attempt in range(max_retries):
            try:
                # Generate response from Gemini
                response = self.model.generate_content(
                    messages,
                    generation_config=genai.GenerationConfig(
                        temperature=Config.TEMPERATURE,
                        top_p=Config.TOP_P,
                        top_k=Config.TOP_K,
                        max_output_tokens=4096  # Increased for batch response
                    )
                )
                
                # Parse the batch response
                results = self._parse_batch_response(response.text)
                
                print(f"   Batch assessment completed: {len(results)} symptoms processed")
                print(f"   Raw LLM response (first 500 chars): {response.text[:500]}...")
                return results
                
            except Exception as e:
                error_msg = str(e).lower()
                
                # Check if it's a 429 rate limit error or 504 Deadline Exceeded error
                if '429' in error_msg or '504' in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 5  # 5s, 10s, 15s
                        print(f"   Batch request rate limit hit. Waiting {wait_time}s before retry {attempt + 1}/{max_retries}...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"   Batch request max retries reached. Error: {e}")
                        # Fall back to individual assessments
                        print("   Falling back to individual symptom assessments...")
                        return self._assess_all_symptoms_fallback(texts)
                else:
                    # Other error, don't retry
                    print(f"   Batch assessment error: {str(e)}")
                    # Fall back to individual assessments
                    print("   Falling back to individual symptom assessments...")
                    return self._assess_all_symptoms_fallback(texts)
        
        # If all retries failed, fall back to individual assessments
        print("   All batch retries failed, falling back to individual assessments...")
        return self._assess_all_symptoms_fallback(texts)
    
    def _assess_all_symptoms_fallback(self, texts: List[str]) -> Dict[str, Dict]:
        """
        Fallback method using individual symptom assessments
        
        Args:
            texts: List of user's journal entries
            
        Returns:
            Dictionary with question IDs as keys and {level, reason} as values
        """
        results = {}
        
        for i, (qid, symptom) in enumerate(REPHRASED_BDI.items()):
            level, reason = self.predict_level(symptom, texts)
            results[qid] = {
                "level": level if level is not None else 0,
                "reason": reason or "Unable to assess",
                "symptom": symptom
            }
            
            # Add delay to avoid rate limit
            # Skip delay on last item
            if i < len(REPHRASED_BDI) - 1:
                time.sleep(2.5)  
            
        return results
    
    def assess_all_symptoms(self, texts: List[str]) -> Dict[str, Dict]:
        """
        Assess all 21 BDI symptoms for given texts using batch processing
        
        Args:
            texts: List of user's journal entries
            
        Returns:
            Dictionary with question IDs as keys and {level, reason, symptom} as values
        """
        # Use batch processing for efficiency
        results = self.assess_all_symptoms_batch(texts)
        
        # Add symptom descriptions to results for compatibility
        for qid in results:
            if qid in REPHRASED_BDI:
                results[qid]['symptom'] = REPHRASED_BDI[qid]
        
        return results
    
    def assess_recent_entries(self, texts: List[str], question_ids: Optional[List[str]] = None) -> Dict[str, Dict]:
        """
        Assess specific BDI symptoms (useful for incremental assessment)
        
        Args:
            texts: List of user's recent journal entries
            question_ids: List of question IDs to assess (e.g., ['Q1', 'Q2'])
                         If None, assesses all questions
            
        Returns:
            Dictionary with question IDs as keys and {level, reason} as values
        """
        results = {}
        
        # Determine which questions to assess
        qids_to_assess = question_ids if question_ids else REPHRASED_BDI.keys()
        
        for i, qid in enumerate(qids_to_assess):
            if qid in REPHRASED_BDI:
                symptom = REPHRASED_BDI[qid]
                level, reason = self.predict_level(symptom, texts)
                results[qid] = {
                    "level": level if level is not None else 0,
                    "reason": reason or "Unable to assess",
                    "symptom": symptom
                }
                
                # Add delay to avoid rate limit
                if i < len(list(qids_to_assess)) - 1:
                    time.sleep(2.5)
                
        return results

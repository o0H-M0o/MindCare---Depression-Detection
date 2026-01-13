"""
Sentiment analysis using cardiffnlp/twitter-roberta-base-sentiment-latest
"""

from transformers import AutoTokenizer, AutoModelForSequenceClassification, AutoConfig
import numpy as np
from scipy.special import softmax
from typing import Dict, Optional
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.append(str(Path(__file__).parent.parent))


class SentimentAnalyzer:
    """Sentiment analysis model for journal entries"""
    
    MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment-latest"
    
    def __init__(self):
        """Initialize sentiment model and tokenizer"""
        print(f"📥 Loading sentiment model: {self.MODEL_NAME}")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.MODEL_NAME)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.MODEL_NAME)
            self.config = AutoConfig.from_pretrained(self.MODEL_NAME)
            print("✅ Sentiment model loaded")
        except Exception as e:
            print(f"❌ Failed to load sentiment model: {e}")
            raise
    
    def _preprocess_text(self, text: str) -> str:
        """
        Preprocess text for Twitter-RoBERTa model
        Replaces usernames and URLs with placeholders
        
        Args:
            text: Raw text
            
        Returns:
            Preprocessed text
        """
        new_text = []
        for token in text.split():
            # Replace @mentions with @user
            if token.startswith('@') and len(token) > 1:
                token = '@user'
            # Replace URLs with 'http'
            elif token.startswith('http'):
                token = 'http'
            new_text.append(token)
        return " ".join(new_text)
    
    def analyze(self, text: str) -> Optional[Dict]:
        
        if not text or not text.strip():
            return None
        
        try:
            import torch
            
            # Preprocess for Twitter-RoBERTa
            preprocessed = self._preprocess_text(text)
            
            # Tokenize to check length
            tokens = self.tokenizer.encode(preprocessed, add_special_tokens=True)
            max_length = 512  # RoBERTa's max sequence length
            
            # If text fits in one chunk, process normally
            if len(tokens) <= max_length:
                encoded = self.tokenizer(
                    preprocessed,
                    return_tensors='pt',
                    truncation=True,
                    max_length=max_length
                )
                
                with torch.no_grad():
                    output = self.model(**encoded)
                
                scores = output[0][0].detach().numpy()
                scores = softmax(scores)
            
            else:
                # Split into chunks and average sentiment scores
                print(f"   ℹ️ Long text ({len(tokens)} tokens), splitting into chunks")
                
                # Split text by sentences or words to create chunks
                words = preprocessed.split()
                chunk_size = 400  # Leave room for special tokens
                chunks = []
                
                for i in range(0, len(words), chunk_size):
                    chunk = " ".join(words[i:i + chunk_size])
                    chunks.append(chunk)
                
                # Analyze each chunk
                all_scores = []
                for chunk in chunks:
                    encoded = self.tokenizer(
                        chunk,
                        return_tensors='pt',
                        truncation=True,
                        max_length=max_length
                    )
                    
                    with torch.no_grad():
                        output = self.model(**encoded)
                    
                    chunk_scores = output[0][0].detach().numpy()
                    chunk_scores = softmax(chunk_scores)
                    all_scores.append(chunk_scores)
                
                # Average scores across chunks
                scores = np.mean(all_scores, axis=0)
            
            # Map to labels (capitalize to match DB constraint)
            label_scores = {}
            for i, score in enumerate(scores):
                label = self.config.id2label[i]
                label_scores[label.capitalize()] = float(score)
            
            # Get top prediction
            top_idx = int(np.argmax(scores))
            top_label = self.config.id2label[top_idx]
            top_score = float(scores[top_idx])
            
            # Capitalize label to match DB constraint (Positive, Neutral, Negative)
            top_label_capitalized = top_label.capitalize()
            
            return {
                'label': top_label_capitalized,
                'score': top_score,
                'scores': label_scores,
                'model': self.MODEL_NAME
            }
            
        except Exception as e:
            print(f"❌ Sentiment analysis error: {e}")
            return None


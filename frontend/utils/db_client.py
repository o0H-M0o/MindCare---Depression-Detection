"""
Database client for Supabase operations
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

# Import Supabase
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    print("Warning: Supabase not installed. Using mock data.")


class DBClient:
    """Client for database operations with Supabase"""
    
    def __init__(self, user_id: Optional[str] = None):
        """
        Initialize Supabase client
        
        Args:
            user_id: User ID (UUID string) for authenticated operations.
                     Must be provided for production use.
        """
        if not user_id:
            raise ValueError("user_id is required. DBClient must be initialized with authenticated user ID.")
        
        self.user_id = user_id
        
        # Try to connect to Supabase
        if SUPABASE_AVAILABLE:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_KEY")
            
            if url and key:
                try:
                    self.supabase: Client = create_client(url, key)
                    self.use_supabase = True
                    print("✅ Connected to Supabase")
                    
                except Exception as e:
                    print(f"⚠️ Supabase connection failed: {e}")
                    self.use_supabase = False
            else:
                print("⚠️ SUPABASE_URL or SUPABASE_KEY not found in environment")
                self.use_supabase = False
        else:
            self.use_supabase = False
        
        # Fallback: Use in-memory storage for development
        if not self.use_supabase:
            print("Using in-memory storage (data will be lost on restart)")
            self._mock_data = {
                'entries': [],
                'assessments': []
            }
    
    def save_journal_entry(
        self, 
        text: str, 
        entry_date: datetime,
        mood_rating: Optional[int] = None
    ) -> Optional[str]:
        """
        Save a journal entry to the database
        
        Args:
            text: Journal entry text
            entry_date: Datetime of the entry (includes both date and time)
            mood_rating: User's mood rating (1-10) - optional (deprecated)
            
        Returns:
            Entry ID if successful, None otherwise
        """
        if self.use_supabase:
            try:
                date_part = entry_date.date() if isinstance(entry_date, datetime) else entry_date
                time_part = entry_date.time() if isinstance(entry_date, datetime) else datetime.now().time()
                
                entry = self.supabase.table('journal_entries').insert({
                    'user_id': self.user_id,
                    'entry_text': text,
                    'entry_date': date_part.isoformat(),
                    'entry_time': time_part.isoformat(),
                    'analysis_status': 'pending'  # Will be processed by background worker
                }).execute()
                
                if entry.data and len(entry.data) > 0:
                    return entry.data[0]['id']
                return None
            except Exception as e:
                print(f"Error saving to Supabase: {e}")
                return None
        else:
            # Mock implementation (fallback)
            entry_id = f"entry_{len(self._mock_data['entries']) + 1}"
            entry_data = {
                'id': entry_id,
                'text': text,
                'date': entry_date,
                'created_at': datetime.now()
            }
            
            self._mock_data['entries'].append(entry_data)
            return entry_id
    
    def get_recent_entries(
        self, 
        days: Optional[int] = 7, 
        limit: int = 10
    ) -> List[Dict]:
        """
        Get recent journal entries
        
        Args:
            days: Number of days to look back (None for all entries)
            limit: Maximum number of entries to return
            
        Returns:
            List of journal entries
        """
        if self.use_supabase:
            try:
                # Build query
                query = self.supabase.table('journal_entries')\
                    .select('*')\
                    .eq('user_id', self.user_id)
                
                # Apply date filter only if days is specified
                if days is not None:
                    cutoff_date = (datetime.now() - timedelta(days=days)).date()
                    query = query.gte('entry_date', str(cutoff_date))
                
                entries = query\
                    .order('entry_date', desc=True)\
                    .order('entry_time', desc=True)\
                    .limit(limit)\
                    .execute()
                
                # Transform to match expected format
                # Build created_at from entry_date + entry_time (schema doesn't include created_at)
                raw_entries = [{
                    'id': e['id'],
                    'text': e['entry_text'],
                    'date': e['entry_date'],
                    'time': e.get('entry_time', '00:00:00'), 
                    'datetime': f"{e['entry_date']} {e.get('entry_time', '00:00:00')}",  # Combined for display
                    'created_at': f"{e['entry_date']} {e.get('entry_time', '00:00:00')}",
                    'analysis_status': e.get('analysis_status', 'pending'),  
                    'analysis_error': e.get('analysis_error')  
                } for e in entries.data] if entries.data else []
                
                # Sort by datetime descending to ensure correct order
                return sorted(raw_entries, key=lambda x: x['datetime'], reverse=True)
            except Exception as e:
                print(f"Error fetching from Supabase: {e}")
                return []
        else:
            # Mock implementation (fallback)
            if days is not None:
                cutoff = datetime.now() - timedelta(days=days)
                filtered = [
                    e for e in self._mock_data['entries'] 
                    if e['date'] >= cutoff.date()
                ]
            else:
                # Return all entries when days is None
                filtered = self._mock_data['entries']
            
            return sorted(filtered, key=lambda x: x['date'], reverse=True)[:limit]
    
    def save_assessment(
        self,
        entry_id: str,
        assessment_data: Dict,
        total_score: int,
        category: str
    ) -> Optional[str]:
        """
        Save assessment results
        
        Args:
            entry_id: ID of the journal entry
            assessment_data: Full assessment results (JSON with all 21 symptoms)
            total_score: Total BDI score
            category: Depression category
            
        Returns:
            Assessment ID if successful, None otherwise
        """
        if self.use_supabase:
            try:
                assessment = self.supabase.table('bdi_assessments').insert({
                    'entry_id': entry_id,
                    'user_id': self.user_id,
                    'assessment_data': assessment_data,
                    'total_score': total_score,
                    'category': category,
                }).execute()
                
                if assessment.data and len(assessment.data) > 0:
                    return assessment.data[0]['id']
                return None
            except Exception as e:
                print(f"Error saving assessment to Supabase: {e}")
                return None
        else:
            # Mock implementation (fallback)
            assessment_id = f"assess_{len(self._mock_data['assessments']) + 1}"
            self._mock_data['assessments'].append({
                'id': assessment_id,
                'entry_id': entry_id,
                'total_score': total_score,
                'category': category,
                'date': datetime.now(),
                'assessment_data': assessment_data
            })
            return assessment_id
    
    def get_assessment_by_entry(self, entry_id: str) -> Optional[Dict]:
        """
        Get assessment results for a specific entry
        
        Args:
            entry_id: ID of the journal entry
            
        Returns:
            Assessment data or None if not found
        """
        if self.use_supabase:
            try:
                result = self.supabase.table('bdi_assessments')\
                    .select('*')\
                    .eq('entry_id', entry_id)\
                    .execute()
                
                if result.data and len(result.data) > 0:
                    return result.data[0]
                return None
            except Exception as e:
                print(f"Error fetching assessment: {e}")
                return None
        else:
            # Mock implementation
            for assessment in self._mock_data['assessments']:
                if assessment['entry_id'] == entry_id:
                    return assessment
            return None
    
    def get_assessment_history(
        self, 
        days: Optional[int] = None
    ) -> List[Dict]:
        """
        Get assessment history
        
        Args:
            days: Number of days to look back (None for all)
            
        Returns:
            List of assessments with scores and categories
        """
        if self.use_supabase:
            try:
                # Select assessments and join journal_entries to obtain entry date/time
                query = self.supabase.table('bdi_assessments')\
                    .select('*, journal_entries(entry_date, entry_time)')\
                    .eq('user_id', self.user_id)

                if days:
                    cutoff_date = (datetime.now() - timedelta(days=days)).date()
                    # Filter by the related journal_entries.entry_date
                    query = query.gte('journal_entries.entry_date', str(cutoff_date))

                res = query.execute()

                if not res.data:
                    return []

                # Transform results and compute a date from the joined journal_entries (if present)
                out = []
                for a in res.data:
                    jd = None
                    # Related journal entry may be returned as a list under 'journal_entries'
                    if 'journal_entries' in a and a['journal_entries']:
                        # Expect single related row
                        try:
                            jd = a['journal_entries'][0]
                        except Exception:
                            jd = None

                    if jd:
                        date_str = f"{jd.get('entry_date')} {jd.get('entry_time', '00:00:00')}"
                    else:
                        date_str = None

                    out.append({
                        'id': a['id'],
                        'total_score': a['total_score'],
                        'category': a['category'],
                        'date': date_str,
                        'assessment_data': a['assessment_data']
                    })

                # Sort by date (None values go last)
                out.sort(key=lambda x: x['date'] or '', reverse=False)
                return out
            except Exception as e:
                print(f"Error fetching assessments from Supabase: {e}")
                return []
        else:
            # Mock implementation (fallback)
            assessments = self._mock_data['assessments']
            if days:
                cutoff = datetime.now() - timedelta(days=days)
                assessments = [a for a in assessments if a['date'] >= cutoff]
            
            return assessments

    def get_sentiment_by_entry(self, entry_id: str) -> Optional[Dict]:
        """
        Get sentiment analysis results for a specific entry
        
        Args:
            entry_id: ID of the journal entry
            
        Returns:
            Sentiment data or None if not found
        """
        if self.use_supabase:
            try:
                result = self.supabase.table('sentiment_analysis')\
                    .select('*')\
                    .eq('entry_id', entry_id)\
                    .execute()
                
                if result.data and len(result.data) > 0:
                    return result.data[0]
                return None
            except Exception as e:
                print(f"Error fetching sentiment: {e}")
                return None
        else:
            return None

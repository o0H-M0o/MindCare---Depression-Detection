"""
User service for fetching user relationships and permissions
Handles role-based data access for viewers and individuals
"""

from typing import List, Dict
from supabase import Client


class UserService:
    """Service for user relationship and permission queries"""
    
    def __init__(self, supabase_client: Client):
        """
        Initialize user service
        
        Args:
            supabase_client: Initialized Supabase client
        """
        self.supabase = supabase_client
    
    def get_linked_users_for_viewer(self, viewer_id: str) -> List[Dict]:
        """
        Get all users that a viewer has access to view
        Checks both direct relationships and institution-based access
        
        Args:
            viewer_id: UUID of the viewer user
            
        Returns:
            List of user profiles the viewer can access
        """
        linked_users = []
        
        # 1. Get users from direct relationships (parents/friends)
        try:
            relationships = self.supabase.table('user_relationships')\
                .select('owner_id, view_analysis, user_profile!user_relationships_owner_id_fkey(id, name, account_type, student_id)')\
                .eq('viewer_id', viewer_id)\
                .eq('view_analysis', True)\
                .execute()
            
            if relationships.data:
                for rel in relationships.data:
                    if rel.get('user_profile'):
                        linked_users.append({
                            'id': rel['user_profile']['id'],
                            'name': rel['user_profile'].get('name', 'Anonymous'),
                            'account_type': rel['user_profile'].get('account_type'),
                            'student_id': rel['user_profile'].get('student_id'),
                            'access_type': 'direct_relationship'
                        })
        except Exception as e:
            print(f"Error fetching direct relationships: {e}")
        
        # 2. Get users from institution staff access
        try:
            # Check if viewer is staff at any institution
            staff_records = self.supabase.table('institution_staff')\
                .select('institution_id, institution(name)')\
                .eq('user_id', viewer_id)\
                .eq('status', 'approved')\
                .execute()
            
            if staff_records.data:
                for staff in staff_records.data:
                    institution_id = staff['institution_id']
                    institution_name = staff.get('institution', {}).get('name', 'Unknown')
                    
                    # Get all users linked to this institution who share analysis and are approved
                    institution_links = self.supabase.table('user_institution_link')\
                        .select('user_id, student_consent, segment_id, link_status, verification_status, user_profile!user_institution_link_user_fkey(id, name, account_type, student_id), institution_segments!user_institution_link_segment_id_fkey(segment_name)')\
                        .eq('institution_id', institution_id)\
                        .eq('student_consent', True)\
                        .eq('link_status', 'active')\
                        .eq('verification_status', 'verified')\
                        .execute()
                    
                    if institution_links.data:
                        for link in institution_links.data:
                            if link.get('user_profile'):
                                seg_obj = link.get('institution_segments') or {}
                                seg_name = seg_obj.get('segment_name') if isinstance(seg_obj, dict) else None
                                linked_users.append({
                                    'id': link['user_profile']['id'],
                                    'name': link['user_profile'].get('name', 'User'),
                                    'account_type': link['user_profile'].get('account_type'),
                                    'student_id': link['user_profile'].get('student_id'),
                                    'access_type': 'institution',
                                    'institution_name': institution_name,
                                    'segment_name': seg_name,
                                    'segment_id': link.get('segment_id')
                                })
        except Exception as e:
            print(f"Error fetching institution-based access: {e}")
        
        # Remove duplicates (user might be accessible through multiple paths)
        unique_users = {user['id']: user for user in linked_users}
        return list(unique_users.values())
    
    def get_assessments_for_user(self, user_id: str, days: int = 30) -> List[Dict]:
        """
        Get BDI assessments for a specific user
        
        Args:
            user_id: UUID of the user
            days: Number of days to look back
            
        Returns:
            List of assessment records with scores and categories
        """
        try:
            from datetime import datetime, timedelta
            cutoff_date = (datetime.now() - timedelta(days=days)).date()
            
            # Query assessments with joined journal entry for dates
            result = self.supabase.table('bdi_assessments')\
                .select('id, total_score, category, analyzed_at, entry_id, journal_entries!bdi_assessments_entry_id_fkey(entry_date, entry_time)')\
                .eq('user_id', user_id)\
                .gte('journal_entries.entry_date', str(cutoff_date))\
                .order('analyzed_at', desc=True)\
                .execute()
            
            if result.data:
                assessments = []
                for item in result.data:
                    entry_data = item.get('journal_entries')
                    if entry_data:
                        # Handle case where journal_entries might be a list
                        if isinstance(entry_data, list) and len(entry_data) > 0:
                            entry_data = entry_data[0]
                        
                        assessments.append({
                            'id': item['id'],
                            'total_score': item['total_score'],
                            'category': item['category'],
                            'analyzed_at': item.get('analyzed_at'),
                            'entry_date': entry_data.get('entry_date'),
                            'entry_time': entry_data.get('entry_time')
                        })
                return assessments
            return []
        except Exception as e:
            print(f"Error fetching assessments for user {user_id}: {e}")
            return []
    
    def get_sentiment_for_user(self, user_id: str, days: int = 30) -> List[Dict]:
        """
        Get sentiment analysis for a specific user
        
        Args:
            user_id: UUID of the user
            days: Number of days to look back
            
        Returns:
            List of sentiment records
        """
        try:
            from datetime import datetime, timedelta
            cutoff_date = (datetime.now() - timedelta(days=days)).date()
            
            result = self.supabase.table('sentiment_analysis')\
                .select('id, top_label, positive_score, neutral_score, negative_score, analyzed_at, entry_id, journal_entries!sentiment_analysis_entry_id_fkey(entry_date, entry_time)')\
                .eq('user_id', user_id)\
                .gte('journal_entries.entry_date', str(cutoff_date))\
                .order('analyzed_at', desc=True)\
                .execute()
            
            if result.data:
                sentiments = []
                for item in result.data:
                    entry_data = item.get('journal_entries')
                    if entry_data:
                        if isinstance(entry_data, list) and len(entry_data) > 0:
                            entry_data = entry_data[0]
                        
                        sentiments.append({
                            'id': item['id'],
                            'top_label': item['top_label'],
                            'positive_score': item.get('positive_score', 0.0),
                            'neutral_score': item.get('neutral_score', 0.0),
                            'negative_score': item.get('negative_score', 0.0),
                            'analyzed_at': item.get('analyzed_at'),
                            'entry_date': entry_data.get('entry_date'),
                            'entry_time': entry_data.get('entry_time')
                        })
                return sentiments
            return []
        except Exception as e:
            print(f"Error fetching sentiment for user {user_id}: {e}")
            return []
    
    def get_user_summary(self, user_id: str) -> Dict:
        """
        Get summary statistics for a user (for viewer dashboard)
        
        Args:
            user_id: UUID of the user
            
        Returns:
            Dict with latest score, average, trend, etc.
        """
        assessments = self.get_assessments_for_user(user_id, days=30)
        
        if not assessments:
            return {
                'user_id': user_id,
                'total_entries': 0,
                'latest_score': None,
                'latest_category': None,
                'average_score': None,
                'latest_date': None
            }
        
        scores = [a['total_score'] for a in assessments]
        
        return {
            'user_id': user_id,
            'total_entries': len(assessments),
            'latest_score': assessments[0]['total_score'] if assessments else None,
            'latest_category': assessments[0]['category'] if assessments else None,
            'average_score': sum(scores) / len(scores) if scores else None,
            'latest_date': assessments[0].get('entry_date') if assessments else None,
            'min_score': min(scores) if scores else None,
            'max_score': max(scores) if scores else None
        }
    
    def can_view_user_data(self, viewer_id: str, target_user_id: str) -> bool:
        """
        Check if viewer has permission to view target user's data
        
        Args:
            viewer_id: UUID of the viewer
            target_user_id: UUID of the user whose data is being accessed
            
        Returns:
            True if viewer has access, False otherwise
        """
        # Self-access always allowed
        if viewer_id == target_user_id:
            return True
        
        # Check if target user is in viewer's linked users
        linked = self.get_linked_users_for_viewer(viewer_id)
        linked_ids = [u['id'] for u in linked]
        
        return target_user_id in linked_ids

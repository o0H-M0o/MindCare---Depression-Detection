"""
Authentication utilities for Supabase integration
Handles login, logout, and session management
"""

import streamlit as st
from typing import Optional, Dict, Any
from supabase import Client
import os
from dotenv import load_dotenv

load_dotenv()


class AuthService:
    """Handle authentication with Supabase"""
    
    def __init__(self, supabase_client: Client):
        """
        Initialize auth service
        
        Args:
            supabase_client: Initialized Supabase client
        """
        self.supabase = supabase_client
        
        # Initialize session state keys if not present
        if 'authenticated' not in st.session_state:
            st.session_state.authenticated = False
        if 'user' not in st.session_state:
            st.session_state.user = None
        if 'user_profile' not in st.session_state:
            st.session_state.user_profile = None
        if 'show_forgot_password' not in st.session_state:
            st.session_state.show_forgot_password = False
    
    def login(self, email: str, password: str) -> tuple[bool, Optional[str]]:
        """
        Authenticate user with email and password
        
        Args:
            email: User email
            password: User password
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            # Authenticate with Supabase
            response = self.supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            
            if response.user:
                # Store user in session
                st.session_state.authenticated = True
                st.session_state.user = {
                    'id': response.user.id,
                    'email': response.user.email,
                    'access_token': response.session.access_token if response.session else None
                }
                
                # Fetch and store user profile
                profile = self._fetch_user_profile(response.user.id)
                st.session_state.user_profile = profile
                
                # Check if institution staff is approved
                if profile and profile.get('account_type') == 'institution':
                    try:
                        staff_info = self.supabase.table('institution_staff')\
                            .select('status')\
                            .eq('user_id', response.user.id)\
                            .execute()
                        
                        if staff_info.data and len(staff_info.data) > 0:
                            staff_status = staff_info.data[0].get('status', 'pending')
                            if staff_status == 'rejected':
                                # Clear session state
                                st.session_state.authenticated = False
                                st.session_state.user = None
                                st.session_state.user_profile = None
                                return False, "Your institution staff application has been rejected. You can reapply by contacting your institution administrator."
                            elif staff_status != 'approved':
                                # Clear session state
                                st.session_state.authenticated = False
                                st.session_state.user = None
                                st.session_state.user_profile = None
                                return False, "Your institution staff account is pending approval. Please contact your institution administrator."
                        else:
                            # Clear session state
                            st.session_state.authenticated = False
                            st.session_state.user = None
                            st.session_state.user_profile = None
                            return False, "Institution staff registration not found. Please contact your institution administrator."
                    except Exception as e:
                        # Clear session state
                        st.session_state.authenticated = False
                        st.session_state.user = None
                        st.session_state.user_profile = None
                        return False, f"Error verifying staff status: {str(e)}"
                
                return True, None
            else:
                return False, "Authentication failed"
                
        except Exception as e:
            error_msg = str(e)
            if 'Invalid login credentials' in error_msg:
                return False, "Invalid email or password"
            return False, f"Login error: {error_msg}"
    
    def signup(self, email: str, password: str, name: str, account_type: str = 'individual', 
               institution_id: Optional[str] = None, access_code: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """
        Register a new user
        
        Args:
            email: User email
            password: User password
            name: User's display name
            account_type: 'individual', 'viewer', or 'institution'
            institution_id: Institution UUID (required for institution accounts)
            access_code: Institution access code (required for institution accounts)
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            # Validate institution access code if signing up as institution staff
            if account_type == 'institution':
                if not institution_id or not access_code:
                    return False, "Institution and access code are required for institution accounts"
                
                # Verify access code
                inst_result = self.supabase.table('institution')\
                    .select('id, access_code')\
                    .eq('id', institution_id)\
                    .execute()
                
                if not inst_result.data:
                    return False, "Institution not found"
                
                if inst_result.data[0]['access_code'] != access_code:
                    return False, "Invalid access code"
            
            # Create auth user
            response = self.supabase.auth.sign_up({
                "email": email,
                "password": password
            })
            
            if response.user:
                # Create user profile
                profile_data = {
                    'id': response.user.id,
                    'name': name,
                    'account_type': account_type,
                    'email': response.user.email,
                }
                
                self.supabase.table('user_profile').insert(profile_data).execute()
                
                # If institution account, create institution_staff link
                if account_type == 'institution' and institution_id:
                    # Check if user already has a rejected application for this institution
                    existing_rejected = self.supabase.table('institution_staff')\
                        .select('id, status')\
                        .eq('user_id', response.user.id)\
                        .eq('institution_id', institution_id)\
                        .eq('status', 'rejected')\
                        .execute()
                    
                    if existing_rejected.data and len(existing_rejected.data) > 0:
                        # Reactivate the rejected application
                        self.supabase.table('institution_staff')\
                            .update({'status': 'pending'})\
                            .eq('id', existing_rejected.data[0]['id'])\
                            .execute()
                        
                        status_msg = "Account created! Please check your email to verify."
                        status_msg += " Your previous institution staff application has been reactivated and is now pending approval."
                        return True, status_msg
                    
                    # Check if institution already has approved staff
                    existing_staff = self.supabase.table('institution_staff')\
                        .select('id')\
                        .eq('institution_id', institution_id)\
                        .eq('status', 'approved')\
                        .execute()
                    
                    # First staff member becomes admin, others become viewer
                    staff_role = 'admin' if not existing_staff.data else 'viewer'
                    staff_status = 'approved' if not existing_staff.data else 'pending'
                    
                    staff_data = {
                        'institution_id': institution_id,
                        'user_id': response.user.id,
                        'role': staff_role,
                        'status': staff_status
                    }
                    self.supabase.table('institution_staff').insert(staff_data).execute()
                
                status_msg = "Account created! Please check your email to verify."
                if account_type == 'institution' and institution_id:
                    if existing_rejected.data and len(existing_rejected.data) > 0:
                        status_msg += " Your previous institution staff application has been reactivated and is now pending approval."
                    elif not existing_staff.data:
                        status_msg += " You are the first staff member and have been automatically approved as an administrator."
                    else:
                        status_msg += " Your institution staff account is pending approval by an administrator."
                
                return True, status_msg
            else:
                return False, "Signup failed"
                
        except Exception as e:
            return False, f"Signup error: {str(e)}"
    
    def send_password_reset_email(self, email: str, redirect_url: str) -> tuple[bool, Optional[str]]:
        """
        Send password reset email
        
        Args:
            email: User email
            redirect_url: URL to redirect to after clicking the link
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            self.supabase.auth.reset_password_email(email, options={'redirect_to': redirect_url})
            return True, None
        except Exception as e:
            return False, str(e)

    def update_password(self, new_password: str) -> tuple[bool, Optional[str]]:
        """
        Update user password (requires active session)
        
        Args:
            new_password: New password
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            self.supabase.auth.update_user({"password": new_password})
            return True, None
        except Exception as e:
            return False, str(e)

    def set_session(self, access_token: str, refresh_token: str) -> bool:
        """
        Set the session from tokens (e.g. from recovery link)
        
        Args:
            access_token: Access token
            refresh_token: Refresh token
            
        Returns:
            bool: True if session set successfully
        """
        try:
            self.supabase.auth.set_session(access_token, refresh_token)
            
            # Update local session state
            user_response = self.supabase.auth.get_user()
            if user_response and user_response.user:
                # Check if institution staff is approved before allowing session
                profile = self._fetch_user_profile(user_response.user.id)
                if profile and profile.get('account_type') == 'institution':
                    try:
                        staff_info = self.supabase.table('institution_staff')\
                            .select('status')\
                            .eq('user_id', user_response.user.id)\
                            .execute()
                        
                        if staff_info.data and len(staff_info.data) > 0:
                            staff_status = staff_info.data[0].get('status', 'pending')
                            if staff_status != 'approved':
                                return False  # Block session for unapproved staff
                        else:
                            return False  # Block session if staff registration not found
                    except Exception as e:
                        return False  # Block session on error
                
                st.session_state.authenticated = True
                st.session_state.user = {
                    'id': user_response.user.id,
                    'email': user_response.user.email,
                    'access_token': access_token
                }
                
                # Store user profile
                st.session_state.user_profile = profile
                
                return True
            return False
        except Exception as e:
            print(f"Error setting session: {e}")
            return False

    def logout(self):
        """Sign out current user and clear session"""
        try:
            self.supabase.auth.sign_out()
        except Exception as e:
            print(f"Logout error: {e}")
        finally:
            # Clear session state
            st.session_state.authenticated = False
            st.session_state.user = None
            st.session_state.user_profile = None
    
    def _fetch_user_profile(self, user_id: str) -> Optional[Dict[Any, Any]]:
        """
        Fetch user profile from database
        
        Args:
            user_id: User UUID
            
        Returns:
            User profile dict or None
        """
        try:
            result = self.supabase.table('user_profile')\
                .select('*')\
                .eq('id', user_id)\
                .execute()
            
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            print(f"Error fetching user profile: {e}")
            return None
    
    def is_authenticated(self) -> bool:
        """Check if user is currently authenticated"""
        return st.session_state.get('authenticated', False)
    
    def get_current_user(self) -> Optional[Dict]:
        """Get current authenticated user"""
        return st.session_state.get('user')
    
    def get_user_profile(self) -> Optional[Dict]:
        """Get current user's profile"""
        return st.session_state.get('user_profile')
    
    def get_user_role(self) -> str:
        """
        Get current user's role/account type
        
        Returns:
            'individual', 'viewer', or 'unknown'
        """
        profile = self.get_user_profile()
        if profile:
            return profile.get('account_type', 'unknown')
        return 'unknown'
    
    def require_auth(self):
        """
        Enforce authentication - redirect to home if not authenticated
        Call this at the top of protected pages
        """
        if not self.is_authenticated():
            st.error("🔒 Please log in to access this page")
            st.stop()
    
    def require_role(self, allowed_roles: list):
        """
        Enforce role-based access control
        
        Args:
            allowed_roles: List of allowed account_type values
        """
        self.require_auth()
        
        role = self.get_user_role()
        if role not in allowed_roles:
            st.error(f"🚫 Access denied. This page requires one of: {', '.join(allowed_roles)}")
            st.stop()
    
    def get_institutions(self) -> list:
        """
        Get list of all available institutions for signup
        
        Returns:
            List of institution dicts with id, name
        """
        try:
            result = self.supabase.table('institution')\
                .select('id, name')\
                .order('name')\
                .execute()
            return result.data if result.data else []
        except Exception as e:
            print(f"Error fetching institutions: {e}")
            return []
    
    def reactivate_rejected_staff(self, email: str, name: str, institution_id: str, access_code: str) -> tuple[bool, Optional[str]]:
        """
        Reactivate a rejected institution staff application
        
        Args:
            email: User's email
            name: Updated full name
            institution_id: Institution UUID
            access_code: Institution access code
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            # Get user by email
            user_profile = self.get_user_by_email(email)
            if not user_profile:
                return False, "User account not found"
            
            user_id = user_profile['id']
            
            # Verify access code
            inst_result = self.supabase.table('institution')\
                .select('id, access_code')\
                .eq('id', institution_id)\
                .execute()
            
            if not inst_result.data:
                return False, "Institution not found"
            
            if inst_result.data[0]['access_code'] != access_code:
                return False, "Invalid access code"
            
            # Check if user has a rejected application for this institution
            staff_result = self.supabase.table('institution_staff')\
                .select('id, status, institution_id')\
                .eq('user_id', user_id)\
                .eq('institution_id', institution_id)\
                .eq('status', 'rejected')\
                .execute()
            
            if not staff_result.data:
                return False, "No rejected application found for this institution. Please sign up as a new staff member."
            
            # Reactivate the application
            self.supabase.table('institution_staff')\
                .update({'status': 'pending'})\
                .eq('id', staff_result.data[0]['id'])\
                .execute()
            
            # Update user profile name if changed
            if user_profile['name'] != name:
                self.supabase.table('user_profile')\
                    .update({'name': name})\
                    .eq('id', user_id)\
                    .execute()
            
            return True, "Your previous institution staff application has been reactivated and is now pending approval."
            
        except Exception as e:
            return False, f"Reapplication error: {str(e)}"
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """
        Get user profile by email address
        
        Args:
            email: User's email address
            
        Returns:
            User profile dict with id, name, account_type or None if not found
        """
        try:
            # Use RPC function to get user_id from auth.users by email
            result = self.supabase.rpc('get_user_id_by_email', {'email_input': email}).execute()
            
            if result.data and len(result.data) > 0:
                user_id = result.data[0].get('user_id')
                if user_id:
                    # Fetch user profile
                    profile = self.supabase.table('user_profile')\
                        .select('id, name, account_type')\
                        .eq('id', user_id)\
                        .execute()
                    
                    if profile.data and len(profile.data) > 0:
                        return profile.data[0]
            
            return None
        except Exception as e:
            print(f"Error fetching user by email: {e}")
            return None

    


def init_auth_service() -> AuthService:
    """
    Initialize and return AuthService instance
    Uses Supabase client from environment variables
    
    Returns:
        AuthService instance
    """
    from supabase import create_client
    
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    
    if not url or not key:
        st.error("⚠️ Supabase configuration missing. Please set SUPABASE_URL and SUPABASE_KEY.")
        st.stop()
    
    supabase = create_client(url, key)
    return AuthService(supabase)

"""
Sidebar authentication component
Renders login/logout UI and manages authentication state
"""

import streamlit as st
from utils.auth import AuthService


def render_auth_sidebar(auth_service: AuthService):
    """
    Render login/logout UI in sidebar
    
    Args:
        auth_service: Initialized AuthService instance
    """
    if not auth_service.is_authenticated():
        with st.sidebar:
            st.subheader("🔐 Account")
            
            # Check if user clicked forgot password
            if st.session_state.get('show_forgot_password', False):
                render_forgot_password_form(auth_service)
                if st.button("← Back to Login"):
                    st.session_state.show_forgot_password = False
                    st.rerun()
            else:
                tab1, tab2 = st.tabs(["Login", "Sign Up"])
                
                with tab1:
                    render_login_form(auth_service)
                
                with tab2:
                    render_signup_form(auth_service)


def render_login_form(auth_service: AuthService):
    """
    Render login form
    
    Args:
        auth_service: Initialized AuthService instance
    """
    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        
        submitted = st.form_submit_button("Login", width='stretch')
        
        if submitted:
            if not email or not password:
                st.error("Please enter both email and password")
            else:
                with st.spinner("Logging in..."):
                    success, error = auth_service.login(email, password)
                    
                    if success:
                        st.success("Login successful!")
                        st.rerun()
                    else:
                        if "rejected" in error.lower():
                            # Store rejection info for reapplication
                            st.session_state.rejected_email = email
                            st.session_state.show_reapplication = True
                        st.error(error)
    
    # Show reapplication section if rejected
    if st.session_state.get('show_reapplication', False):
        render_reapplication_section(auth_service)
    
    # Forgot password button below the login form
    if st.button("Forgot Password?", key="forgot_password_button"):
        st.session_state.show_forgot_password = True
        st.rerun()


def render_signup_form(auth_service: AuthService):
    """
    Render signup form
    
    Args:
        auth_service: Initialized AuthService instance
    """
    with st.form("signup_form", clear_on_submit=False):
        name = st.text_input("Full Name", key="signup_name")
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_password")
        password_confirm = st.text_input("Confirm Password", type="password", key="signup_password_confirm")
        
        account_type = st.selectbox(
            "How will you use this app?",
            options=["individual", "viewer", "institution"],
            format_func=lambda x: (
                "Individual"
                if x == "individual"
                else ("Support Person" if x == "viewer" else "Institution Staff")
            ),
            key="signup_account_type"
        )
        
        # Show institution fields only when institution is selected
        institution_id = None
        access_code = None
        
        if account_type == "institution":
            st.info("🏫 Join your institution by selecting it and entering the access code.")
            
            # Fetch available institutions
            institutions = auth_service.get_institutions()
            
            if not institutions:
                st.warning("No institutions available. Please contact your administrator.")
            else:
                institution_options = {inst['name']: inst['id'] for inst in institutions}
                selected_institution = st.selectbox(
                    "Institution",
                    options=list(institution_options.keys()),
                    key="signup_institution"
                )
                institution_id = institution_options.get(selected_institution)
                
                access_code = st.text_input(
                    "Institution Access Code",
                    type="password",
                    key="signup_access_code",
                    help="Enter the access code provided by your institution"
                )
        
        submitted = st.form_submit_button("Create Account", width='stretch')
        
        if submitted:
            if not all([name, email, password, password_confirm]):
                st.error("Please fill in all fields")
            elif password != password_confirm:
                st.error("Passwords do not match")
            elif len(password) < 8:
                st.error("Password must be at least 8 characters")
            elif account_type == "institution" and (not institution_id or not access_code):
                st.error("Please select an institution and enter the access code")
            else:
                with st.spinner("Creating account..."):
                    success, message = auth_service.signup(
                        email, password, name, account_type,
                        institution_id=institution_id,
                        access_code=access_code
                    )
                    
                    if success:
                        st.success(message)
                    else:
                        st.error(message)


def render_reapplication_section(auth_service: AuthService):
    """
    Render reapplication section for rejected institution staff

    Args:
        auth_service: Initialized AuthService instance
    """
    st.divider()
    st.subheader("🔄 Reapply for Institution Staff Access")
    st.warning("Your previous application was rejected. You can reapply below by signing up again with the same institution.")

    with st.form("reapplication_form", clear_on_submit=False):
        name = st.text_input("Full Name", key="reapply_name")
        email = st.text_input(
            "Email",
            value=st.session_state.get('rejected_email', ''),
            key="reapply_email",
            disabled=True,
            help="This is the email from your rejected application"
        )

        # Fetch available institutions
        institutions = auth_service.get_institutions()

        if not institutions:
            st.error("No institutions available. Please contact your administrator.")
        else:
            institution_options = {inst['name']: inst['id'] for inst in institutions}
            selected_institution = st.selectbox(
                "Institution",
                options=list(institution_options.keys()),
                key="reapply_institution"
            )
            institution_id = institution_options.get(selected_institution)

            access_code = st.text_input(
                "Institution Access Code",
                type="password",
                key="reapply_access_code",
                help="Enter the access code provided by your institution"
            )

            submitted = st.form_submit_button("Submit Reapplication", width='stretch')

            if submitted:
                if not all([name, institution_id, access_code]):
                    st.error("Please fill in all fields")
                else:
                    with st.spinner("Submitting reapplication..."):
                        # Use the reactivation method for existing rejected users
                        success, message = auth_service.reactivate_rejected_staff(
                            email, name, institution_id, access_code
                        )

                        if success:
                            st.success("Reapplication submitted successfully!")
                            st.info("Your previous institution staff application has been reactivated and is now pending approval.")
                            # Clear reapplication state
                            st.session_state.show_reapplication = False
                            if 'rejected_email' in st.session_state:
                                del st.session_state.rejected_email
                            st.rerun()
                        else:
                            st.error(message)

def render_forgot_password_form(auth_service: AuthService):
    """
    Render forgot password form
    
    Args:
        auth_service: Initialized AuthService instance
    """
    st.write("Enter your email to receive a password reset link.")
    with st.form("forgot_password_form"):
        email = st.text_input("Email", key="forgot_password_email")
        submitted = st.form_submit_button("Send Reset Link", width='stretch')
        
        if submitted:
            if not email:
                st.error("Please enter your email")
            else:
                with st.spinner("Sending reset link..."):
                    import os
                    # Default to localhost if not set
                    site_url = os.getenv("SITE_URL", "http://localhost:8501")
                    
                    success, error = auth_service.send_password_reset_email(email, site_url)
                    
                    if success:
                        st.success("Check your email for the reset link!")
                        st.info("Click the link in the email to reset your password.")
                    else:
                        st.error(f"Error: {error}")


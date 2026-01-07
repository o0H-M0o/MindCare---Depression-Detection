"""
MindCare Streamlit app launcher and navigation.

Roles and capabilities (short):
- individual: personal journaling, view personal BDI-based analysis and trends, share opt-in with viewers/institutions.
- viewer: read-only access to analytics for users who granted access; cannot view journal text or change data.
- institution: aggregated monitoring for opted-in users; cannot access private journal text or modify individual data.

This module wires authentication, sidebar controls, and role-based navigation.
BDI-based analysis here refers to using the Beck Depression Inventory approach
applied to user journal text for self-monitoring (not a clinical diagnosis).
"""

import streamlit as st
import streamlit.components.v1 as components
import sys
from pathlib import Path

# Ensure utils are importable
sys.path.append(str(Path(__file__).parent))

from utils.auth import init_auth_service
from utils.auth_sidebar import render_auth_sidebar
from dotenv import load_dotenv

load_dotenv()

# Page config
st.set_page_config(
    page_title="MindCare",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize auth
auth_service = init_auth_service()

# --- Password Reset Handling ---

# 1. Handle Query Parameters (Post-Redirect)
# Check if we have query params indicating a reset (from our JS redirect)
query_params = st.query_params

def _qp_first(key: str, default: str = "") -> str:
    val = query_params.get(key, default)
    if isinstance(val, (list, tuple)):
        return val[0] if len(val) > 0 else default
    return val or default

type_param = _qp_first("type", "")
access_token = _qp_first("access_token", "")
refresh_token = _qp_first("refresh_token", "")

if type_param == "recovery" and access_token:
    
    if auth_service.set_session(access_token, refresh_token):
        st.success("Password reset verified! Please set your new password.")
        
        with st.form("reset_password_form"):
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")
            submitted = st.form_submit_button("Update Password")
            
        if submitted:
            if new_password != confirm_password:
                st.error("Passwords do not match")
            elif len(new_password) < 8:
                st.error("Password must be at least 8 characters")
            else:
                success, error = auth_service.update_password(new_password)
                if success:
                    st.success("Password updated successfully! Redirecting...")
                    st.query_params.clear()
                    import time
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error(f"Error updating password: {error}")
        st.stop() # Stop execution of the rest of the app
    else:
        st.error("Invalid or expired password reset link.")
        st.stop()

# 2. Handle Hash Fragment (Pre-Redirect)
# Inject JS to handle hash fragment from Supabase and redirect to query params
components.html(
    """
    <script>
    (function() {
        function processHash() {
            try {
                // Streamlit components run in an iframe. Supabase recovery tokens
                // are placed on the TOP window URL (after '#'), so read/redirect
                // using the top/parent location.
                var topWindow = window.top || window.parent || window;
                var topLocation = topWindow.location || window.location;

                // Check if we have a hash
                if (topLocation.hash) {
                    var hash = topLocation.hash.substring(1);
                    
                    // Check for recovery params in the hash
                    if (hash.includes('type=recovery') && hash.includes('access_token')) {
                        console.log("MindCare: Recovery hash detected, processing...");
                        
                        var params = new URLSearchParams(hash);
                        var accessToken = params.get('access_token');
                        var type = params.get('type');
                        var refreshToken = params.get('refresh_token');
                        
                        if (accessToken && type === 'recovery') {
                            // Construct new URL with query params instead of hash
                            var newUrl = topLocation.origin + topLocation.pathname + '?access_token=' + encodeURIComponent(accessToken) + '&type=' + encodeURIComponent(type);
                            if (refreshToken) {
                                newUrl += '&refresh_token=' + encodeURIComponent(refreshToken);
                            }

                            // Try to force redirect/reload with new params.
                            // Some browsers block top-level navigation initiated from a sandboxed iframe.
                            // If blocked, we inject a small overlay into the top document with a user-click
                            // button to continue (no manual URL edits needed).
                            try {
                                topLocation.href = newUrl;
                            } catch (e) {
                                // ignore and fall back to overlay
                            }

                            // If we are still on the hash URL after a short delay, show a button.
                            setTimeout(function() {
                                try {
                                    if (topLocation.hash && topLocation.hash.indexOf('type=recovery') !== -1) {
                                        var doc = topWindow.document;
                                        if (!doc) return;

                                        var existing = doc.getElementById('mindcare-recovery-overlay');
                                        if (existing) return;

                                        var overlay = doc.createElement('div');
                                        overlay.id = 'mindcare-recovery-overlay';
                                        overlay.style.position = 'fixed';
                                        overlay.style.left = '0';
                                        overlay.style.right = '0';
                                        overlay.style.top = '0';
                                        overlay.style.zIndex = '2147483647';
                                        overlay.style.padding = '12px';
                                        overlay.style.background = 'rgba(0,0,0,0.75)';
                                        overlay.style.color = '#fff';
                                        overlay.style.fontFamily = 'system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif';
                                        overlay.style.textAlign = 'center';
                                        overlay.innerHTML =
                                            '<div style="max-width: 900px; margin: 0 auto;">'
                                            + '<div style="font-weight: 600; margin-bottom: 8px;">Password recovery detected</div>'
                                            + '<button id="mindcare-recovery-continue" style="padding: 8px 14px; border-radius: 6px; border: 0; cursor: pointer;">Continue to reset password</button>'
                                            + '</div>';

                                        doc.body.appendChild(overlay);
                                        var btn = doc.getElementById('mindcare-recovery-continue');
                                        if (btn) {
                                            btn.addEventListener('click', function() {
                                                try {
                                                    topLocation.href = newUrl;
                                                } catch (e2) {
                                                    try { topWindow.open(newUrl, '_top'); } catch (e3) {}
                                                }
                                            });
                                        }
                                    }
                                } catch (e4) {
                                    // ignore overlay failures
                                }
                            }, 250);
                            return true;
                        }
                    }
                }
            } catch (e) {
                console.error("MindCare Auth Redirect Error:", e);
            }
            return false;
        }

        // Attempt to process immediately
        if (!processHash()) {
            // If not found immediately, poll for a few seconds
            // This helps if the hash is populated slightly after component mount
            var attempts = 0;
            var interval = setInterval(function() {
                attempts++;
                if (processHash() || attempts > 20) { // Stop after ~2 seconds
                    clearInterval(interval);
                }
            }, 100);
        }
    })();
    </script>
    """,
    height=0,
    width=0
)

# Render auth sidebar (login/logout UI)
render_auth_sidebar(auth_service)

# Define landing page function for unauthenticated users
def landing_page():
    st.title("🧠 Welcome to MindCare")
    st.write("### Journaling + AI insights for self-monitoring")
    st.caption("MindCare is not a medical diagnosis.")
    
    st.divider()
    
    st.subheader("How will you use this app?")
    st.markdown("""
    - **Individual**: For anyone who wants to write, track, and view their own analysis. You control your data and decide who can see it.
    - **Support Person**: For parents, mentors, counselors, or trusted supporters who are invited to view dashboards shared by an individual.
    - **Institution Staff**: For universities or organizations that view dashboards for multiple users with their consent.
    """)
    
    st.info("👈 Please log in or sign up from the sidebar to get started")
    st.divider()

    st.write("**Write privately. Share insights when you choose.**")
    st.write("**Support persons and institutions view only what is shared with them.**")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📝 Private Journaling")
        st.write("Write daily reflections in a private space")

    with col2:
        st.subheader("✨ AI-Powered Analysis")
        st.write("Get BDI-based (Beck Depression Inventory) depression analysis and sentiment insights from your entries")

    col1, col2 = st.columns(2)   
    with col1:
        st.subheader("📈 Track Your Well-being")
        st.write("Visualize mood trends and well-being over time")
    
    with col2:
        st.subheader("🔗 Secure Sharing")
        st.write("Share analysis results securely with trusted support person or your institution")
    
def home_page():
    profile = auth_service.get_user_profile()
    role = auth_service.get_user_role()
    
    st.title(f"Welcome back, {profile.get('name', 'User')}! 🌟")
    
    if role == "individual":
        st.write("**Your Mental Health Companion**")
        st.write("Track your well-being through journaling, BDI-based depression analysis (Beck Depression Inventory), sentiment insights, and trends over time.")
        
        st.divider()
        
        col1, col2, col3 = st.columns(3)

        with col1:
            st.info("**📝 My Journal**")
            st.write("Write daily reflections in a private space.")
            if st.button("Open Journal", key="home_open_journal"):
                st.switch_page("pages/Journal.py")

        with col2:
            st.info("**📈 My History**")
            st.write("Browse your past entries.")
            if st.button("Open History", key="home_open_history"):
                st.switch_page("pages/My History.py")

        with col3:
            st.info("**🌿 My Well-being Overview**")
            st.write("Charts and trends of your well-being built from your entries.")
            if st.button("Open Dashboard", key="home_open_dashboard"):
                st.switch_page("pages/Dashboard.py")
        
        st.divider()
        
        st.subheader("🧠 About BDI-based Analysis")
        st.write("""
        We apply the Beck Depression Inventory (BDI) approach with AI analysis
        of your journal entries to estimate symptom severity and surface mood
        patterns. Results are intended for awareness and to encourage seeking
        professional help when appropriate.
        """)
        st.caption("Note: This is for self-monitoring and reflection, not diagnosis.")
    
    elif role == "viewer":
        st.write("**Mental Health Viewer Dashboard**")
        st.write("Monitor the well-being of users who have shared access with you.")
        
        st.divider()
        
        col1, col2 = st.columns(2)

        with col1:
            st.info("**📊 Monitoring Overview**")
            st.write("Overview of linked users' mood trends.")
            if st.button("Open Monitoring", key="home_open_monitoring"):
                st.switch_page("pages/Monitoring_Overview.py")

        with col2:
            st.info("**💖 Analysis Details**")
            st.write("Open detailed analytics for a selected user.")
            if st.button("Open Analysis", key="home_open_viewer_dashboard"):
                st.switch_page("pages/Viewer_Dashboard.py")
        
        st.divider()
        
        st.subheader("ℹ️ Your Viewer Role")
        st.write("""
        As a viewer, you can:
        - See assessment scores and trends for users who grant you access
        - Monitor indicators without viewing personal journal text
        - Support users while respecting privacy
        - You cannot read journal text or modify another user's private data.
        """)
    
    elif role == "institution":
        st.write("**Institution Dashboard**")
        st.write("Monitor mental health trends for students who opted in to share analysis with your institution.")
        
        st.divider()
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.info("**📊 Monitoring Overview**")
            st.write("Overview of linked users' mood trends and aggregated indicators.")
            if st.button("Open Monitoring", key="inst_open_monitoring"):
                st.switch_page("pages/Monitoring_Overview.py")
        
        with col2:
            st.info("**🏫 Analysis Details**")
            st.write("Open detailed analytics and institution-level reports.")
            if st.button("Open Analysis", key="inst_open_analysis"):
                st.switch_page("pages/Institution_Dashboard.py")
        
        st.divider()
        
        st.subheader("ℹ️ Institution Access")
        st.write("""
        As institution staff, you can:
        - View assessment scores and trends for users who opted in to share with your institution
        - Monitor indicators without viewing personal journal content
        - Support students/clients while maintaining privacy standards
        - You cannot read personal journal entries or modify individual user data.
        """)

# Configure navigation based on authentication status
if not auth_service.is_authenticated():
    # Show only landing page for unauthenticated users
    pages = [
        st.Page(landing_page, title="Home", icon="🏠", default=True)
    ]
    pg = st.navigation(pages)
else:
    # Get user role
    role = auth_service.get_user_role()
    
    # Define pages based on role
    if role == "individual":
        pages = {
            "": [
                st.Page(home_page, title="About MindCare", icon="🏠", default=True),
            ],
            "Journal": [
                st.Page("pages/Journal.py", title="My Journal", icon="📝"),
                st.Page("pages/My History.py", title="My History", icon="📈"),
            ],
            "Analytics": [
                st.Page("pages/Dashboard.py", title="My Well-being Overview", icon="🌿"),
            ],
            "Account": [
                st.Page("pages/Settings.py", title="Settings", icon="⚙️"),
            ],
        }
    elif role == "viewer":
        pages = {
            "": [
                st.Page(home_page, title="About MindCare", icon="🏠", default=True),
            ],
            "Monitoring": [
                st.Page("pages/Monitoring_Overview.py", title="Monitoring Overview", icon="📊"),
                st.Page("pages/Viewer_Dashboard.py", title="Analysis Details", icon="💖"),
            ],
            "Account": [
                st.Page("pages/Settings.py", title="Settings", icon="⚙️"),
            ],
        }
    elif role == "institution":
        # Institution accounts: view and manage linked users across the institution
        pages = {
            "": [
                st.Page(home_page, title="About MindCare", icon="🏠", default=True),
            ],
            "Monitoring": [
                st.Page("pages/Monitoring_Overview.py", title="Monitoring Overview", icon="📊"),
                st.Page("pages/Institution_Dashboard.py", title="Analysis Details", icon="🏫"),
            ],
            "Account": [
                st.Page("pages/Settings.py", title="Settings", icon="⚙️"),
            ],
        }
    else:
        # Fallback for unknown roles
        pages = [
            st.Page(home_page, title="About MindCare", icon="🏠", default=True),
            st.Page("pages/Settings.py", title="Settings", icon="⚙️"),
        ]
    
    pg = st.navigation(pages, position="sidebar")

# Run the selected page
pg.run()

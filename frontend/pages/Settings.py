"""
Settings page - Manage account preferences and data sharing
Individual users can link viewers and institutions to share their analysis
"""

import streamlit as st
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from utils.auth import init_auth_service
from utils.auth_sidebar import render_auth_sidebar
from utils.db_client import DBClient

st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")

# Initialize auth and render sidebar
auth_service = init_auth_service()
render_auth_sidebar(auth_service)

# Require any authenticated user
auth_service.require_auth()

# Get current user
current_user = auth_service.get_current_user()
profile = auth_service.get_user_profile()

if not current_user:
    st.error("Authentication required")
    st.stop()

# Initialize DB client
db_client = DBClient(user_id=current_user['id'])

# Dialog functions for delete operations
@st.dialog("Confirm Deletion")
def delete_viewer_dialog(rel):
    """Dialog for confirming viewer deletion"""
    viewer_profile = rel.get('user_profile')
    viewer_name = viewer_profile.get('name', 'Unknown') if viewer_profile else 'Unknown'
    
    st.warning("⚠️ **Confirm Deletion**")
    st.write(f"Are you sure you want to remove **{viewer_name}** from your viewers? This action cannot be undone.")

    conf_col1, conf_col2 = st.columns(2)
    with conf_col1:
        if st.button("✅ Yes, Remove", type="primary", width='stretch'):
            try:
                # Delete from database
                db_client.supabase.table('user_relationships')\
                    .delete()\
                    .eq('id', rel['id'])\
                    .execute()
                st.success("Viewer removed")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    with conf_col2:
        if st.button("❌ Cancel", width='stretch'):
            st.rerun()

@st.dialog("Confirm Rejection")
def reject_staff_dialog(staff):
    """Dialog for confirming staff rejection"""
    staff_profile = staff.get('user_profile')
    staff_name = staff_profile.get('name', 'Unknown') if staff_profile else 'Unknown'
    
    st.warning("⚠️ **Confirm Rejection**")
    st.write(f"Are you sure you want to reject **{staff_name}**'s institution staff application?")
    st.write("The staff member will be marked as rejected and can reapply later.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("❌ Yes, Reject", type="primary", width='stretch'):
            try:
                # Update status to rejected instead of deleting
                db_client.supabase.table('institution_staff')\
                    .update({'status': 'rejected'})\
                    .eq('id', staff['id'])\
                    .execute()
                st.success(f"Rejected {staff_name}'s application")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    with col2:
        if st.button("Cancel", width='stretch'):
            st.rerun()

@st.dialog("Confirm Approval")
def approve_staff_dialog(staff, role):
    """Dialog for confirming staff approval"""
    staff_profile = staff.get('user_profile')
    staff_name = staff_profile.get('name', 'Unknown') if staff_profile else 'Unknown'
    role_display = "Administrator" if role == "admin" else "Viewer"
    
    st.success("✅ **Confirm Approval**")
    st.write(f"Are you sure you want to approve **{staff_name}** as an **{role_display}**?")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button(f"✅ Yes, Approve as {role_display}", type="primary", width='stretch'):
            try:
                db_client.supabase.table('institution_staff')\
                    .update({'status': 'approved', 'role': role})\
                    .eq('id', staff['id'])\
                    .execute()
                st.success(f"Approved {staff_name} as {role_display}")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    with col2:
        if st.button("Cancel", width='stretch'):
            st.rerun()

@st.dialog("Approve Data Sharing Request")
def approve_link_dialog(link):
    """Dialog for approving data sharing requests"""
    user_profile = link.get('user_profile', {})
    student_name = user_profile.get('name', 'Unknown')
    student_id = user_profile.get('student_id', 'Not set')
    
    st.write(f"Approve **{student_name}**'s request to share their analysis data?")
    
    # Get segments for optional editing
    try:
        segments = db_client.supabase.table('institution_segments')\
            .select('id, segment_name')\
            .eq('institution_id', link.get('institution_id'))\
            .order('segment_name')\
            .execute()
        
        segment_options = {seg['segment_name']: seg['id'] for seg in segments.data} if segments.data else {}
        
        current_segment = link.get('institution_segments', {})
        current_segment_name = current_segment.get('segment_name') if current_segment else None
        
        if segment_options:
            new_segment_name = st.selectbox(
                "Segment (Optional)",
                options=list(segment_options.keys()),
                index=list(segment_options.keys()).index(current_segment_name) if current_segment_name in segment_options else 0,
                help="Update the student's segment if needed"
            )
            new_segment_id = segment_options.get(new_segment_name, link.get('segment_id'))
        else:
            new_segment_id = link.get('segment_id')
            st.info("No segments available for editing")
        
        new_student_id = st.text_input(
            "Student ID (Optional)", 
            value=student_id if student_id != 'Not set' else '',
            help="Update the student's ID if needed"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Approve", type="primary", width='stretch'):
                try:
                    # Update the link
                    update_data = {
                        'verification_status': 'verified',
                        'link_status': 'active'
                    }
                    
                    if new_segment_id != link.get('segment_id'):
                        update_data['segment_id'] = new_segment_id
                    
                    db_client.supabase.table('user_institution_link')\
                        .update(update_data)\
                        .eq('id', link['id'])\
                        .execute()
                    
                    # Update student ID in user profile if changed
                    if new_student_id and new_student_id.strip() != student_id:
                        db_client.supabase.table('user_profile')\
                            .update({'student_id': new_student_id.strip()})\
                            .eq('id', link['user_id'])\
                            .execute()
                    
                    st.success(f"Approved {student_name}'s data sharing request")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        with col2:
            if st.button("Cancel", width='stretch'):
                st.rerun()
                
    except Exception as e:
        st.error(f"Error loading segments: {e}")

@st.dialog("Reject Data Sharing Request")
def reject_link_dialog(link):
    """Dialog for rejecting data sharing requests"""
    user_profile = link.get('user_profile', {})
    student_name = user_profile.get('name', 'Unknown')
    
    st.warning("❌ **Reject Data Sharing Request**")
    st.write(f"Are you sure you want to reject **{student_name}**'s request to share their analysis data?")
    st.write("This action cannot be undone.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("❌ Yes, Reject", type="primary", width='stretch'):
            try:
                db_client.supabase.table('user_institution_link')\
                    .update({
                        'verification_status': 'rejected',
                        'link_status': 'rejected'
                    })\
                    .eq('id', link['id'])\
                    .execute()
                st.success(f"Rejected {student_name}'s data sharing request")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    with col2:
        if st.button("Cancel", width='stretch'):
            st.rerun()

@st.dialog("Confirm Institution Link Removal")
def delete_institution_dialog(link):
    """Dialog for confirming institution link deletion"""
    institution = link.get('institution')
    inst_name = institution.get('name', 'Unknown') if institution else 'Unknown'
    
    st.warning("⚠️ **Confirm Removal**")
    st.write(f"Are you sure you want to remove your link to **{inst_name}**? This action cannot be undone.")
    st.write("You will need to request access again if you want to share data with this institution in the future.")

    conf_col1, conf_col2 = st.columns(2)
    with conf_col1:
        if st.button("✅ Yes, Remove", type="primary", width='stretch'):
            try:
                # Delete from database
                db_client.supabase.table('user_institution_link')\
                    .delete()\
                    .eq('id', link['id'])\
                    .execute()
                st.success("Institution link removed")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    with conf_col2:
        if st.button("❌ Cancel", width='stretch'):
            st.rerun()

@st.dialog("Confirm Segment Deletion")
def delete_segment_dialog(segment):
    """Dialog for confirming segment deletion"""
    segment_name = segment.get('segment_name', 'Unknown')
    
    st.warning("⚠️ **Confirm Deletion**")
    st.write(f"Are you sure you want to delete the segment **{segment_name}**? This action cannot be undone.")
    st.write("All users currently assigned to this segment will need to be reassigned.")

    conf_col1, conf_col2 = st.columns(2)
    with conf_col1:
        if st.button("✅ Yes, Delete", type="primary", width='stretch'):
            try:
                # Delete from database
                db_client.supabase.table('institution_segments')\
                    .delete()\
                    .eq('id', segment['id'])\
                    .execute()
                st.success(f"Segment '{segment_name}' deleted successfully")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

@st.dialog("Confirm Add Segment")
def add_segment_dialog(segment_name, institution_id):
    """Dialog for confirming segment addition"""
    
    st.write("**Add New Segment**")
    st.write(f"Are you sure you want to add the segment: **{segment_name}**?")
    
    conf_col1, conf_col2 = st.columns(2)
    with conf_col1:
        if st.button("✅ Yes, Add", type="primary", width='stretch'):
            try:
                # Check if segment already exists
                existing = db_client.supabase.table('institution_segments')\
                    .select('id')\
                    .eq('institution_id', institution_id)\
                    .eq('segment_name', segment_name.strip())\
                    .execute()
                
                if existing.data and len(existing.data) > 0:
                    st.error("A segment with this name already exists")
                else:
                    # Insert new segment
                    segment_data = {
                        'institution_id': institution_id,
                        'segment_name': segment_name.strip()
                    }
                    db_client.supabase.table('institution_segments').insert(segment_data).execute()
                    st.success(f"✅ Segment **{segment_name}** added successfully!")
                    st.rerun()
            except Exception as e:
                st.error(f"Error adding segment: {e}")

    with conf_col2:
        if st.button("❌ Cancel", width='stretch'):
            st.rerun()

@st.dialog("Edit Segment")
def edit_segment_dialog(segment):
    """Dialog for editing segment name"""
    segment_name = segment.get('segment_name', 'Unknown')
    
    st.write(f"**Edit Segment: {segment_name}**")
    
    new_segment_name = st.text_input(
        "Segment Name",
        value=segment_name,
        help="Update the segment name"
    )
    
    col_cancel, col_save = st.columns(2)
    
    with col_cancel:
        if st.button("❌ Cancel", width='stretch'):
            st.rerun()
    
    with col_save:
        if st.button("💾 Save", width='stretch', type="primary"):
            if not new_segment_name or not new_segment_name.strip():
                st.error("Segment name cannot be empty")
            elif new_segment_name.strip() == segment_name:
                st.error("No changes detected")
            else:
                try:
                    # Update segment name
                    db_client.supabase.table('institution_segments')\
                        .update({'segment_name': new_segment_name.strip()})\
                        .eq('id', segment['id'])\
                        .execute()
                    
                    st.success(f"✅ Segment updated to: {new_segment_name.strip()}")
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Error updating segment: {e}")

@st.dialog("Edit Student Data")
def edit_student_dialog(student, inst_id):
    """Dialog for editing student data"""
    user_profile = student.get('user_profile', {})
    student_name = user_profile.get('name', 'Unknown')
    current_student_id = user_profile.get('student_id', '')
    
    st.write(f"**Editing: {student_name}**")
    
    # Edit Student ID
    new_student_id = st.text_input(
        "Student ID",
        value=current_student_id or "",
        key=f"dialog_student_id_input_{student['id']}"
    )
    
    # Edit Segment
    # Get available segments for this institution
    try:
        available_segments = db_client.supabase.table('institution_segments')\
            .select('id, segment_name')\
            .eq('institution_id', inst_id)\
            .execute()
        
        if available_segments.data and len(available_segments.data) > 0:
            segment_options = [seg['segment_name'] for seg in available_segments.data]
            segment_ids = [seg['id'] for seg in available_segments.data]
            
            # Find current segment index
            current_segment_id = student.get('segment_id')
            current_index = 0
            if current_segment_id:
                for i, seg in enumerate(available_segments.data):
                    if seg['id'] == current_segment_id:
                        current_index = i
                        break
            
            selected_segment = st.selectbox(
                "Segment",
                options=segment_options,
                index=current_index,
                key=f"dialog_segment_select_{student['id']}"
            )
            
            selected_segment_id = segment_ids[segment_options.index(selected_segment)]
        else:
            st.error("No segments available. Please create segments first.")
            selected_segment_id = student.get('segment_id')
        
    except Exception as e:
        st.error(f"Error loading segments: {e}")
        selected_segment_id = student.get('segment_id')
    
    col_cancel, col_save = st.columns(2)
    
    with col_cancel:
        if st.button("❌ Cancel", width='stretch'):
            st.rerun()
    
    with col_save:
        if st.button("💾 Save Changes", width='stretch', type="primary"):
            try:
                # Update student ID in user_profile
                if new_student_id != current_student_id:
                    db_client.supabase.table('user_profile')\
                        .update({'student_id': new_student_id})\
                        .eq('id', student['user_id'])\
                        .execute()
                
                # Update segment in user_institution_link
                current_segment = student.get('segment_id')
                if selected_segment_id != current_segment:
                    db_client.supabase.table('user_institution_link')\
                        .update({'segment_id': selected_segment_id})\
                        .eq('id', student['id'])\
                        .execute()
                
                st.success("✅ Student information updated successfully!")
                st.rerun()
                
            except Exception as e:
                st.error(f"Error updating student information: {e}")

@st.dialog("Edit Staff Role")
def edit_staff_role_dialog(staff, admin_count):
    """Dialog for editing staff role"""
    staff_profile = staff.get('user_profile')
    staff_name = staff_profile.get('name', 'Unknown') if staff_profile else 'Unknown'
    current_role = staff.get('role', 'unknown')
    
    st.write(f"**Editing role for: {staff_name}**")
    st.write(f"Current role: **{current_role}**")
    
    # Check if this is the last admin
    is_last_admin = (admin_count == 1 and current_role == 'admin')
    
    if is_last_admin:
        st.warning("⚠️ **Cannot change role:** This is the only admin. Changing their role would leave the institution without an admin.")
        st.info("To change this admin's role, first approve another staff member as an admin.")
        
        col_cancel = st.columns(1)[0]
        with col_cancel:
            if st.button("❌ Close", width='stretch'):
                st.rerun()
    else:
        # Only show the role that is NOT the current role
        if current_role == "admin":
            available_roles = ["viewer"]
        elif current_role == "viewer":
            available_roles = ["admin"]
        else:
            # Fallback for unknown roles
            available_roles = ["admin", "viewer"]
        
        new_role = st.selectbox(
            "Select new role:",
            options=available_roles,
            key=f"dialog_role_select_{staff['id']}"
        )
        
        col_cancel, col_update = st.columns(2)
        
        with col_cancel:
            if st.button("❌ Cancel", width='stretch'):
                st.rerun()
        
        with col_update:
            if st.button("💾 Update Role", width='stretch', type="primary"):
                try:
                    # Update staff role
                    db_client.supabase.table('institution_staff')\
                        .update({'role': new_role})\
                        .eq('id', staff['id'])\
                        .execute()
                    
                    st.success(f"✅ Staff role updated to {new_role} successfully!")
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Error updating staff role: {e}")

@st.dialog("Remove Staff Member")
def remove_staff_dialog(staff, admin_count):
    """Dialog for removing staff member"""
    staff_profile = staff.get('user_profile')
    staff_name = staff_profile.get('name', 'Unknown') if staff_profile else 'Unknown'
    current_role = staff.get('role', 'unknown')
    
    st.write(f"**Remove Staff Member: {staff_name}**")
    
    # Check if this is the last admin
    is_last_admin = (admin_count == 1 and current_role == 'admin')
    
    if is_last_admin:
        st.error("🚫 **Cannot remove the last admin:** This institution must have at least one admin at all times.")
        st.info("To remove this admin, first approve another staff member as an admin.")
        
        col_close = st.columns(1)[0]
        with col_close:
            if st.button("❌ Close", width='stretch'):
                st.rerun()
    else:
        st.warning("⚠️ This action cannot be undone. The staff member will lose access to this institution.")
        
        confirm_remove = st.checkbox(
            f"I confirm I want to remove {staff_name} from this institution",
            key=f"dialog_confirm_remove_{staff['id']}"
        )
        
        col_cancel, col_remove = st.columns(2)
        
        with col_cancel:
            if st.button("❌ Cancel", width='stretch'):
                st.rerun()
        
        with col_remove:
            if st.button("🗑️ Remove Staff", width='stretch', type="secondary"):
                if confirm_remove:
                    try:
                        # Remove staff member by updating status to 'rejected'
                        db_client.supabase.table('institution_staff')\
                            .update({'status': 'rejected'})\
                            .eq('id', staff['id'])\
                            .execute()
                        
                        st.success(f"✅ Staff member {staff_name} has been removed successfully!")
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Error removing staff member: {e}")
                else:
                    st.error("Please confirm the removal by checking the checkbox above.")

st.title("⚙️ Settings")

# Display institution access code for institution admins
if profile.get('account_type') == 'institution':
    try:
        staff_info = db_client.supabase.table('institution_staff')\
            .select('institution_id, role, institution!institution_staff_institution_fkey(access_code)')\
            .eq('user_id', current_user['id'])\
            .eq('status', 'approved')\
            .eq('role', 'admin')\
            .execute()
        
        if staff_info.data and len(staff_info.data) > 0:
            institution = staff_info.data[0]['institution']
            access_code = institution.get('access_code')
            if access_code:
                st.info(f"🔑 **Institution Access Code:** `{access_code}`\n\nShare this code with new staff members to allow them to sign up.")
    except Exception as e:
        st.warning("Could not retrieve access code")

st.subheader("📋 Account Details")
# Name editing section
col_name, col_edit = st.columns([3, 1])

# Display name in a card similar to Email / Account Type
current_name = profile.get('name', '')
with col_name:
    st.markdown("""
    <div style="background-color: #e3f2fd; padding: 15px; border-radius: 8px; text-align: left;">
        <h4 style="color: #1976d2; margin: 0;">👤 Name</h4>
        <h5 style="margin: 5px 0; font-size: 18px;">{}</h5>
    </div>
    """.format(current_name or 'Not set'), unsafe_allow_html=True)

with col_edit:
    if st.button("✏️ Edit Name", key="edit_name_btn"):
        st.session_state.editing_name = True

# Name editing form (only show when editing)
if st.session_state.get('editing_name', False):
    st.markdown("---")
    with st.form("edit_name_form", clear_on_submit=True):
        new_name = st.text_input(
            "New Name",
            value=current_name,
            placeholder="Enter your full name",
            help="This name will be visible to linked viewers and institutions"
        )

        col_cancel, col_save = st.columns(2)
        with col_cancel:
            if st.form_submit_button("❌ Cancel", width='stretch'):
                st.session_state.editing_name = False
                st.rerun()

        with col_save:
            if st.form_submit_button("💾 Save Name", width='stretch', type="primary"):
                if new_name.strip():
                    try:
                        # Update the profile name and check response
                        resp = db_client.supabase.table('user_profile')\
                            .update({'name': new_name.strip()})\
                            .eq('id', current_user['id'])\
                            .execute()

                        # resp is expected to have .data and .error
                        if getattr(resp, 'error', None):
                            st.error(f"❌ Error updating name: {resp.error}")
                        elif not getattr(resp, 'data', None):
                            st.error("❌ Name update did not return updated data. Please try again.")
                        else:
                            # Refresh local profile from DB if possible
                            try:
                                fresh = db_client.supabase.table('user_profile')\
                                    .select('name')\
                                    .eq('id', current_user['id'])\
                                    .execute()
                                if getattr(fresh, 'data', None) and len(fresh.data) > 0:
                                    profile['name'] = fresh.data[0].get('name')
                            except Exception:
                                pass

                            st.success("✅ Name updated successfully!")
                            st.session_state.editing_name = False
                            time.sleep(1)
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error updating name: {e}")
                else:
                    st.error("❌ Name cannot be empty")

st.write("")
# Determine which columns to show based on account type and institution links
account_type = profile.get('account_type')
show_student_id = False

if account_type == 'individual':
    try:
        institution_links = db_client.supabase.table('user_institution_link')\
            .select('id')\
            .eq('user_id', current_user['id'])\
            .execute()
        show_student_id = institution_links.data and len(institution_links.data) > 0
    except Exception:
        show_student_id = False

# Create dynamic column layout
if show_student_id:
    # Show all three columns
    col1, col2, col3 = st.columns(3)
else:
    # Show only two columns, centered
    col1, col2 = st.columns(2)
    col3 = None  # Not used

with col1:
    with st.container():
        st.markdown("""
        <div style="background-color: #e3f2fd; padding: 15px; border-radius: 8px; text-align: center;">
            <h4 style="color: #1976d2; margin: 0;">📧 Email</h4>
            <p style="margin: 5px 0; font-size: 14px;">{}</p>
        </div>
        """.format(current_user.get('email', 'N/A')), unsafe_allow_html=True)

with col2:
    with st.container():
        account_type_display = profile.get('account_type', 'unknown').capitalize()
        st.markdown("""
        <div style="background-color: #f3e5f5; padding: 15px; border-radius: 8px; text-align: center;">
            <h4 style="color: #7b1fa2; margin: 0;">🚀 Account Type</h4>
            <p style="margin: 5px 0; font-size: 14px;">{}</p>
        </div>
        """.format(account_type_display), unsafe_allow_html=True)

# Only show Student ID column if applicable
if col3 is not None:
    with col3:
        with st.container():
            student_id = profile.get('student_id')
            if student_id:
                st.markdown("""
                <div style="background-color: #e8f5e8; padding: 15px; border-radius: 8px; text-align: center;">
                    <h4 style="color: #388e3c; margin: 0;">🎓 Student ID</h4>
                    <p style="margin: 5px 0; font-size: 14px;">{}</p>
                </div>
                """.format(student_id), unsafe_allow_html=True)
            else:
                st.markdown("""
                <div style="background-color: #fafafa; padding: 15px; border-radius: 8px; text-align: center; border: 1px dashed #ccc;">
                    <h4 style="color: #666; margin: 0;">� Student ID</h4>
                    <p style="margin: 5px 0; font-size: 14px; color: #999;">Not set</p>
                </div>
                """, unsafe_allow_html=True)

st.divider()

# Show data sharing options only for individual users
if profile.get('account_type') == 'individual':
    st.subheader("🔗 Data Sharing")
    st.write("Share your mental health analysis with viewers (friends/family) or institutions.")
    
    # Create two columns for viewers and institutions
    col_viewers, col_institutions = st.columns(2)
    
    # === VIEWER LINKING ===
    with col_viewers:
        with st.expander("💖 Linked Support Person"):
            st.caption("Friends, family, or personal supporters")
            
            # Get existing viewer relationships
            try:
                existing_viewers = db_client.supabase.table('user_relationships')\
                    .select('id, viewer_id, view_analysis, user_profile!user_relationships_viewer_id_fkey(name, account_type)')\
                    .eq('owner_id', current_user['id'])\
                    .execute()
                
                if existing_viewers.data and len(existing_viewers.data) > 0:
                    st.write(f"**{len(existing_viewers.data)} viewer(s) linked:**")
                    
                    for rel in existing_viewers.data:
                        viewer_profile = rel.get('user_profile')
                        if viewer_profile:
                            viewer_name = viewer_profile.get('name', 'Unknown')
                            viewer_type = viewer_profile.get('account_type', 'viewer')
                            
                            with st.container():
                                col_info, col_action = st.columns([3, 1])
                                with col_info:
                                    st.markdown(f"""
<div style="background-color: #f8f9fa; padding: 8px; border-radius: 4px; border-left: 4px solid #007bff;">
{viewer_name}<br>
<small>{viewer_type.capitalize()}</small>
</div>
""", unsafe_allow_html=True)
                                with col_action:
                                    if st.button("🗑️", key=f"remove_viewer_{rel['id']}", width='stretch'):
                                        delete_viewer_dialog(rel)
                                st.divider()
                else:
                    st.info("No viewers linked yet")
            except Exception as e:
                st.error(f"Error loading viewers: {e}")
        
        # Add new viewer form
        st.markdown("#### ➕ Add Support Person")
        with st.form("add_viewer_form", clear_on_submit=True):
            viewer_email = st.text_input(
                "Viewer's Email",
                placeholder="viewer@example.com",
                help="Enter the email address of a registered viewer account"
            )
            
            student_consent = st.checkbox(
                "Share analysis results (Required)",
                value=False,
                help="You must enable this to allow viewer to see your BDI scores and sentiment trends"
            )
            
            submitted = st.form_submit_button("Add Viewer", width='stretch')
            
            if submitted:
                if not viewer_email:
                    st.error("Please enter a viewer email address")
                elif not student_consent:
                    st.error("You must enable 'Share analysis results' to add a viewer")
                elif viewer_email.lower() == current_user.get('email', '').lower():
                    st.error("You cannot add yourself as a viewer")
                else:
                    try:
                        # Look up user by email
                        viewer_profile = auth_service.get_user_by_email(viewer_email)
                        
                        if not viewer_profile:
                            st.error("User not found. Please ensure they have a registered account.")
                        elif viewer_profile['account_type'] != 'viewer':
                            st.error("User must have a 'viewer' account type")
                        else:
                            # Check if already linked
                            existing = db_client.supabase.table('user_relationships')\
                                .select('id')\
                                .eq('owner_id', current_user['id'])\
                                .eq('viewer_id', viewer_profile['id'])\
                                .execute()
                            
                            if existing.data and len(existing.data) > 0:
                                st.error("This viewer is already linked to your account")
                            else:
                                # Insert relationship
                                rel_data = {
                                    'owner_id': current_user['id'],
                                    'viewer_id': viewer_profile['id'],
                                    'view_analysis': student_consent
                                }
                                db_client.supabase.table('user_relationships').insert(rel_data).execute()
                                st.success(f"✅ Viewer **{viewer_profile['name']}** ({viewer_email}) added successfully!")
                                st.rerun()
                    except Exception as e:
                        st.error(f"Error adding viewer: {e}")
    
    # === INSTITUTION LINKING ===
    with col_institutions:
        with st.expander("🏫 Linked Institutions"):
            st.caption("Schools, universities, or support organizations")
            
            # Get existing institution links with new status fields
            try:
                existing_institutions = db_client.supabase.table('user_institution_link')\
                    .select('id, institution_id, student_consent, segment_id, link_status, verification_status, institution!user_institution_link_institution_fkey(name), institution_segments!user_institution_link_segment_id_fkey(segment_name)')\
                    .eq('user_id', current_user['id'])\
                    .execute()
                
                # Fetch fresh user profile to get latest student_id
                fresh_profile = db_client.supabase.table('user_profile')\
                    .select('student_id')\
                    .eq('id', current_user['id'])\
                    .execute()
                
                current_student_id = fresh_profile.data[0].get('student_id') if fresh_profile.data else None
                
                if existing_institutions.data and len(existing_institutions.data) > 0:
                    st.write(f"**{len(existing_institutions.data)} institution(s) linked:**")
                    
                    for link in existing_institutions.data:
                        institution = link.get('institution')
                        segment = link.get('institution_segments')
                        
                        if institution:
                            inst_name = institution.get('name', 'Unknown')
                            segment_name = segment.get('segment_name', 'Not set') if segment else 'Not set'
                            link_status = link.get('link_status', 'unknown')
                            verification_status = link.get('verification_status', 'unknown')
                            
                            verification_badge = {
                                'verified': '✅ Verified',
                                'unverified': '⏳ Unverified',
                                'rejected': '❌ Rejected'
                            }.get(verification_status, '❓ Unknown')
                            
                            with st.container():
                                col_info, col_actions = st.columns([3, 1])
                                with col_info:
                                    st.markdown(f"""
<div style="background-color: #f8f9fa; padding: 8px; border-radius: 4px; border-left: 4px solid #28a745;">
<strong>{inst_name}</strong><br>
<small>Segment: {segment_name}</small><br>
<small>Student ID: {current_student_id if current_student_id else 'Not set'}</small><br>
<small>Status: {verification_badge}</small>
</div>
""", unsafe_allow_html=True)
                                    
                                    # Show rejection message if rejected
                                    if verification_status == 'rejected':
                                        st.write("")  
                                        st.info("You can edit your student ID or segment to request verification again.")
                                
                                with col_actions:
                                    # Only show edit button if not verified and active
                                    is_verified_active = (link_status == 'active' and verification_status == 'verified')
                                    if not is_verified_active:
                                        if st.button("✏️", key=f"edit_inst_{link['id']}", help="Edit", width='stretch'):
                                            st.session_state[f'editing_inst_{link["id"]}'] = True
                                            st.rerun()
                                    else:
                                        st.caption("🔒 Verified")
                                    if st.button("🗑️", key=f"remove_inst_{link['id']}", help="Remove", width='stretch'):
                                        delete_institution_dialog(link)
                                
                                # Edit form
                                if st.session_state.get(f'editing_inst_{link["id"]}', False):
                                    with st.form(f"edit_form_{link['id']}"):
                                        st.write("**Edit Institution Link**")
                                        st.info("⚠️ Once your institution verifies and activates this link, you will not be able to change the segment and student ID.")
                                        
                                        # Fetch segments for this institution
                                        segments = db_client.supabase.table('institution_segments')\
                                            .select('id, segment_name')\
                                            .eq('institution_id', link['institution_id'])\
                                            .order('segment_name')\
                                            .execute()
                                        
                                        if segments.data:
                                            segment_options = {seg['segment_name']: seg['id'] for seg in segments.data}
                                            current_segment_id = link.get('segment_id')
                                            current_segment_name = segment.get('segment_name') if segment else None
                                            
                                            new_segment_name = st.selectbox(
                                                "Segment",
                                                options=list(segment_options.keys()),
                                                index=list(segment_options.keys()).index(current_segment_name) if current_segment_name in segment_options else 0
                                            )
                                            new_segment_id = segment_options[new_segment_name]
                                        else:
                                            st.warning("No segments available")
                                            new_segment_id = None
                                        
                                        new_student_id = st.text_input("Student ID", value=current_student_id if current_student_id else '')
                                        
                                        col_save, col_cancel = st.columns(2)
                                        with col_save:
                                            save_btn = st.form_submit_button("💾 Save", width='stretch')
                                        with col_cancel:
                                            cancel_btn = st.form_submit_button("❌ Cancel", width='stretch')
                                        
                                        if save_btn:
                                            if not new_student_id or not new_student_id.strip():
                                                st.error("Student ID is required")
                                            elif not new_segment_id:
                                                st.error("Segment is required")
                                            else:
                                                try:
                                                    # Update link with new statuses for re-verification
                                                    db_client.supabase.table('user_institution_link')\
                                                        .update({
                                                            'segment_id': new_segment_id,
                                                            'verification_status': 'unverified',
                                                            'link_status': 'requested'
                                                        })\
                                                        .eq('id', link['id'])\
                                                        .execute()
                                                    
                                                    # Update user profile student_id
                                                    db_client.supabase.table('user_profile')\
                                                        .update({'student_id': new_student_id.strip()})\
                                                        .eq('id', current_user['id'])\
                                                        .execute()
                                                    
                                                    st.success("Updated successfully! Your institution will review your changes.")
                                                    del st.session_state[f'editing_inst_{link["id"]}']
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Error updating: {e}")
                                        
                                        if cancel_btn:
                                            del st.session_state[f'editing_inst_{link["id"]}']
                                            st.rerun()
                                
                                st.divider()
                else:
                    st.info("No institutions linked yet")
            except Exception as e:
                st.error(f"Error loading institutions: {e}")
        
        # Add new institution form
        st.markdown("#### ➕ Link Institution")
        
        # Get user's email domain for filtering institutions
        user_email = current_user.get('email', '')
        user_domain = user_email.split('@')[-1] if '@' in user_email else ''
        
        # Step 1: Select institution and check
        try:
            # Get all institutions and filter by email domain containing user domain
            all_institutions = db_client.supabase.table('institution')\
                .select('id, name, email_domain')\
                .order('name')\
                .execute()
            
            # Filter institutions where user domain contains the institution's email_domain
            filtered_institutions = []
            if all_institutions.data:
                for inst in all_institutions.data:
                    inst_domain = inst.get('email_domain', '')
                    if inst_domain and inst_domain in user_domain:
                        filtered_institutions.append(inst)
            
            if filtered_institutions:
                with st.form("select_institution_form"):
                    institution_options = {inst['name']: inst['id'] for inst in filtered_institutions}
                    selected_institution = st.selectbox(
                        "Select Institution",
                        options=list(institution_options.keys()),
                        help=f"Only institutions where your email domain (@{user_domain}) contains their domain are shown"
                    )
                    selected_institution_id = institution_options.get(selected_institution)
                    
                    check_btn = st.form_submit_button("🔍 Check Institution", width='stretch')
                    
                    if check_btn:
                        # Store selected institution in session state
                        st.session_state.selected_institution_id = selected_institution_id
                        st.session_state.selected_institution_name = selected_institution
                        st.rerun()
            else:
                if user_domain:
                    st.warning(f"To link with an institution, please register using your institution's email address (e.g., student@university.edu.my).")
                else:
                    st.warning("Unable to determine your email domain. Please ensure your account has a valid email address.")
        except Exception as e:
            st.error(f"Error loading institutions: {e}")
        
        # Step 2: Show detailed form if institution is selected
        if 'selected_institution_id' in st.session_state:
            st.info(f"**Selected Institution:** {st.session_state.get('selected_institution_name', 'Unknown')}")
            
            with st.form("complete_institution_link_form"):
                # Fetch segments for selected institution
                try:
                    segments = db_client.supabase.table('institution_segments')\
                        .select('id, segment_name')\
                        .eq('institution_id', st.session_state.selected_institution_id)\
                        .order('segment_name')\
                        .execute()
                    
                    if segments.data and len(segments.data) > 0:
                        segment_options = {seg['segment_name']: seg['id'] for seg in segments.data}
                        selected_segment_name = st.selectbox(
                            "Select Segment (Required)",
                            options=list(segment_options.keys()),
                            help="Choose your faculty, class, or department"
                        )
                        selected_segment_id = segment_options[selected_segment_name]
                    else:
                        st.warning("No segments available for this institution. Please contact the institution admin.")
                        selected_segment_id = None
                    
                    student_id_input = st.text_input(
                        "Student ID (Required)",
                        placeholder="Enter your student/member ID",
                        help="Your unique identifier at this institution"
                    )
                    
                    student_consent = st.checkbox(
                        "Share analysis results (Required)",
                        value=False,
                        help="You must enable this to allow institution to see your BDI scores and sentiment trends"
                    )
                    
                    col_submit, col_cancel = st.columns(2)
                    with col_submit:
                        submit_btn = st.form_submit_button("Link Institution", width='stretch', type="primary")
                    with col_cancel:
                        cancel_btn = st.form_submit_button("Cancel", width='stretch')
                    
                    if submit_btn:
                        if not student_consent:
                            st.error("You must enable 'Share analysis results' to link an institution")
                        elif not student_id_input or not student_id_input.strip():
                            st.error("Student ID is required")
                        elif not selected_segment_id:
                            st.error("Segment selection is required")
                        else:
                            try:
                                # Check if already linked
                                existing = db_client.supabase.table('user_institution_link')\
                                    .select('id')\
                                    .eq('user_id', current_user['id'])\
                                    .eq('institution_id', st.session_state.selected_institution_id)\
                                    .execute()
                                
                                if existing.data and len(existing.data) > 0:
                                    st.error("You are already linked to this institution")
                                else:
                                    # Update user profile with student_id
                                    db_client.supabase.table('user_profile')\
                                        .update({'student_id': student_id_input.strip()})\
                                        .eq('id', current_user['id'])\
                                        .execute()
                                    
                                    # Insert institution link with new status fields
                                    link_data = {
                                        'user_id': current_user['id'],
                                        'institution_id': st.session_state.selected_institution_id,
                                        'student_consent': student_consent,
                                        'segment_id': selected_segment_id,
                                        'link_status': 'requested',
                                        'verification_status': 'unverified'
                                    }
                                    db_client.supabase.table('user_institution_link').insert(link_data).execute()
                                    
                                    st.success(f"Requested to link to {st.session_state.selected_institution_name}")
                                    
                                    # Clear session state
                                    del st.session_state.selected_institution_id
                                    del st.session_state.selected_institution_name
                                    st.rerun()
                                        
                            except Exception as e:
                                st.error(f"Error linking institution: {e}")
                    
                    if cancel_btn:
                        # Clear selection
                        del st.session_state.selected_institution_id
                        del st.session_state.selected_institution_name
                        st.rerun()
                        
                except Exception as e:
                    st.error(f"Error loading segments: {e}")


# Institution Admin Data Sharing Management
if profile.get('account_type') == 'institution':
    # Check if user is an approved institution admin (not viewer)
    try:
        staff_info = db_client.supabase.table('institution_staff')\
            .select('institution_id, role, institution!institution_staff_institution_fkey(name)')\
            .eq('user_id', current_user['id'])\
            .eq('status', 'approved')\
            .eq('role', 'admin')\
            .execute()
        
        if staff_info.data and len(staff_info.data) > 0:
            institution_id = staff_info.data[0]['institution_id']
            institution_name = staff_info.data[0]['institution']['name']
            
            st.subheader("📊 Data Sharing Requests")
            st.write(f"Manage data sharing requests for **{institution_name}**")
            
            # Get all requested links for this institution
            try:
                requested_links = db_client.supabase.table('user_institution_link')\
                    .select('id, user_id, institution_id, student_consent, segment_id, link_status, verification_status, user_profile!user_institution_link_user_fkey(name, student_id, email), institution_segments!user_institution_link_segment_id_fkey(segment_name)')\
                    .eq('institution_id', institution_id)\
                    .eq('link_status', 'requested')\
                    .execute()
                
                if requested_links.data and len(requested_links.data) > 0:
                    st.write(f"**{len(requested_links.data)} pending request(s):**")
                    
                    # Group requests by segment
                    requests_by_segment = {}
                    for link in requested_links.data:
                        segment = link.get('institution_segments', {})
                        segment_name = segment.get('segment_name', 'Not set') if segment else 'Not set'
                        
                        if segment_name not in requests_by_segment:
                            requests_by_segment[segment_name] = []
                        requests_by_segment[segment_name].append(link)
                    
                    # Display requests grouped by segment
                    for segment_name, links in requests_by_segment.items():
                        with st.expander(f"📁 {segment_name} ({len(links)} request{'s' if len(links) > 1 else ''})", expanded=False):
                            for link in links:
                                user_profile = link.get('user_profile', {})
                                
                                student_name = user_profile.get('name', 'Unknown')
                                student_email = user_profile.get('email', 'Not available')
                                student_id = user_profile.get('student_id', 'Not set')
                                has_consent = link.get('student_consent', False)
                                
                                with st.container():
                                    col_info, col_actions = st.columns([4, 2])
                                    with col_info:
                                        consent_status = "✅ Consent Given" if has_consent else "❌ No Consent"
                                        st.markdown(f"""
<div style="background-color: #fff3cd; padding: 10px; border-radius: 6px; border-left: 4px solid #ffc107;">
<strong>{student_name}</strong><br>
<small>Email: {student_email}</small><br>
<small>Student ID: {student_id}</small><br>
<small>{consent_status}</small>
</div>
""", unsafe_allow_html=True)
                                    
                                    with col_actions:
                                        col_approve, col_reject = st.columns(2)
                                        with col_approve:
                                            if st.button("✅ Approve", key=f"approve_link_{link['id']}", width='stretch'):
                                                approve_link_dialog(link)
                                        with col_reject:
                                            if st.button("❌ Reject", key=f"reject_link_{link['id']}", width='stretch'):
                                                reject_link_dialog(link)
                                
                                st.divider()
                else:
                    st.info("No pending data sharing requests.")
                    st.divider()
                    
            except Exception as e:
                st.error(f"Error loading requests: {e}")
    except Exception as e:
        st.error(f"Error checking admin status: {e}")


# Segment Management for Institution Accounts
if profile.get('account_type') == 'institution':
    # Check if user is not a viewer role
    try:
        viewer_check = db_client.supabase.table('institution_staff')\
            .select('role')\
            .eq('user_id', current_user['id'])\
            .eq('status', 'approved')\
            .execute()
        
        user_is_viewer = False
        if viewer_check.data and len(viewer_check.data) > 0:
            user_is_viewer = viewer_check.data[0].get('role') == 'viewer'
        
        if not user_is_viewer:
            st.subheader("🏫 Segment Management")
            st.write("Organize users by faculty, class, department, or other groups")
            
            # Get institution ID for this staff member
            try:
                staff_info = db_client.supabase.table('institution_staff')\
                    .select('institution_id, institution!institution_staff_institution_fkey(name)')\
                    .eq('user_id', current_user['id'])\
                    .eq('status', 'approved')\
                    .execute()
                
                if staff_info.data and len(staff_info.data) > 0:
                    institution_id = staff_info.data[0]['institution_id']
                    institution_name = staff_info.data[0].get('institution', {}).get('name', 'Your Institution')
                    
                    st.caption(f"Managing segments for: **{institution_name}**")
                    
                    # Display existing segments
                    segments = db_client.supabase.table('institution_segments')\
                        .select('id, segment_name')\
                        .eq('institution_id', institution_id)\
                        .order('segment_name')\
                        .execute()
                    
                    if segments.data and len(segments.data) > 0:
                        st.write(f"**{len(segments.data)} segment(s):**")
                        
                        with st.expander("📂 All Segments", expanded=False):
                            for segment in segments.data:
                                with st.container():
                                    col_name, col_edit = st.columns([3, 1])
                                    with col_name:
                                        st.markdown(f"""
<div style="background-color: #f8f9fa; padding: 8px; border-radius: 4px; border-left: 4px solid #6c757d;">
{segment['segment_name']}
</div>
""", unsafe_allow_html=True)
                                    with col_edit:
                                        if st.button("✏️", key=f"edit_seg_{segment['id']}", help="Edit segment"):
                                            edit_segment_dialog(segment) 
                    else:
                        st.info("No segments created yet")
                    
                    # Add new segment form
                    st.markdown("#### ➕ Add Segment")
                    with st.form("add_segment_form", clear_on_submit=True):
                        segment_name = st.text_input(
                            "Segment Name",
                            placeholder="e.g., Computer Science, Class 2024, Psychology Department",
                            help="Enter the name of the faculty, class, or department"
                        )
                        
                        submitted = st.form_submit_button("Add Segment", width='stretch')
                        
                        if submitted:
                            if not segment_name or not segment_name.strip():
                                st.error("Please enter a segment name")
                            else:
                                # Store segment info in session state and open confirmation dialog
                                st.session_state.pending_segment_name = segment_name.strip()
                                st.session_state.pending_institution_id = institution_id
                                st.rerun()
                    
                    # Show confirmation dialog if segment addition is pending
                    if 'pending_segment_name' in st.session_state and 'pending_institution_id' in st.session_state:
                        add_segment_dialog(
                            st.session_state.pending_segment_name,
                            st.session_state.pending_institution_id
                        )
                        # Clear session state after dialog is shown
                        del st.session_state.pending_segment_name
                        del st.session_state.pending_institution_id
                else:
                    st.warning("Could not find your institution information")
            except Exception as e:
                st.error(f"Error loading segments: {e}")
        
        if not user_is_viewer:
            st.divider()
    
        # Staff Management Section
        # Only show for admin role, hide completely for viewers
        
        # Get institution ID and role for this staff member
        inst_id = None
        user_role = None
        try:
            staff_info = db_client.supabase.table('institution_staff')\
                .select('institution_id, role')\
                .eq('user_id', current_user['id'])\
                .eq('status', 'approved')\
                .execute()
            if staff_info.data and len(staff_info.data) > 0:
                inst_id = staff_info.data[0].get('institution_id')
                user_role = staff_info.data[0].get('role')
        except Exception:
            inst_id = None
            user_role = None
        
        if user_role == 'admin':
            st.subheader("👥 Staff Management")
            
            if inst_id and user_role == 'admin':
                # Get pending staff
                try:
                    pending_staff = db_client.supabase.table('institution_staff')\
                        .select('id, user_id, role, status, user_profile!institution_staff_user_fkey(name, email, account_type)')\
                        .eq('institution_id', inst_id)\
                        .eq('status', 'pending')\
                        .execute()
                    
                    if pending_staff.data and len(pending_staff.data) > 0:
                        with st.expander("⏳ Pending Staff Approvals", expanded=True):
                            for staff in pending_staff.data:
                                with st.container():
                                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                                    with col1:
                                        name = staff.get('user_profile', {}).get('name', 'Unknown')
                                        email = staff.get('user_profile', {}).get('email', 'Unknown')
                                        st.write(f"**{name}**")
                                        st.caption(f"📧 {email}")
                                    with col2:
                                        if st.button("✅ Approve as Admin", key=f"approve_admin_{staff['id']}", width='stretch'):
                                            approve_staff_dialog(staff, 'admin')
                                    with col3:
                                        if st.button("✅ Approve as Viewer", key=f"approve_viewer_{staff['id']}", width='stretch'):
                                            approve_staff_dialog(staff, 'viewer')
                                    with col4:
                                        if st.button("❌ Reject", key=f"reject_{staff['id']}", width='stretch'):
                                            reject_staff_dialog(staff)
                    else:
                        with st.expander("⏳ Pending Staff Approvals", expanded=False):
                            st.info("No pending staff approvals.")
                    
                except Exception as e:
                    st.error(f"Error loading pending staff: {e}")
                
                # Get approved staff for management
                try:
                    approved_staff = db_client.supabase.table('institution_staff')\
                        .select('id, user_id, role, status, user_profile!institution_staff_user_fkey(name, email, account_type)')\
                        .eq('institution_id', inst_id)\
                        .eq('status', 'approved')\
                        .execute()
                    
                    if approved_staff.data and len(approved_staff.data) > 0:
                        # Count admin staff to prevent removing the last admin
                        admin_count = sum(1 for staff in approved_staff.data if staff.get('role') == 'admin')
                        
                        with st.expander("✅ Approved Staff Members", expanded=False):
                            if admin_count == 1:
                                st.info("⚠️ **Important:** There is currently only one admin. You cannot remove or change the role of the last admin to prevent account lockout.")
                            
                            for staff in approved_staff.data:
                                with st.container():
                                    col_info, col_role, col_edit, col_remove = st.columns([3, 1.5, 1, 1])
                                    
                                    with col_info:
                                        name = staff.get('user_profile', {}).get('name', 'Unknown')
                                        email = staff.get('user_profile', {}).get('email', 'Unknown')
                                        current_role = staff.get('role', 'unknown')
                                        role_display = "👑 Admin" if current_role == 'admin' else "👁️ Viewer" if current_role == 'viewer' else "❓ Unknown"
                                        
                                        st.write(f"**{name}**")
                                        st.caption(f"📧 {email}")
                                        st.caption(f"Role: {role_display}")
                                    
                                    with col_role:
                                        # Show current role status
                                        if current_role == 'admin':
                                            st.success("Admin")
                                        elif current_role == 'viewer':
                                            st.info("Viewer")
                                        else:
                                            st.warning("Unknown")
                                    
                                    with col_edit:
                                        current_staff_role = staff.get('role', 'unknown')
                                        is_last_admin = (admin_count == 1 and current_staff_role == 'admin')
                                        
                                        if is_last_admin:
                                            st.button("✏️ Edit", key=f"edit_staff_{staff['id']}", width='stretch', disabled=True, help="Cannot edit the last admin")
                                        else:
                                            edit_key = f"edit_staff_{staff['id']}"
                                            if st.button("✏️ Edit", key=edit_key, width='stretch'):
                                                edit_staff_role_dialog(staff, admin_count)
                                    
                                    with col_remove:
                                        current_staff_role = staff.get('role', 'unknown')
                                        is_last_admin = (admin_count == 1 and current_staff_role == 'admin')
                                        
                                        if is_last_admin:
                                            st.button("🗑️ Remove", key=f"remove_staff_{staff['id']}", width='stretch', disabled=True, help="Cannot remove the last admin")
                                        else:
                                            remove_key = f"remove_staff_{staff['id']}"
                                            if st.button("🗑️ Remove", key=remove_key, width='stretch'):
                                                remove_staff_dialog(staff, admin_count)
                            
                    else:
                        with st.expander("✅ Approved Staff Members", expanded=False):
                            st.info("No approved staff members found.")
                    
                except Exception as e:
                    st.error(f"Error loading approved staff: {e}")
           
        # Student Management Section - Only for admins
        if user_role == 'admin' and inst_id:
            st.divider()
            st.subheader("🎓 Student Management")
            st.write("Edit student IDs and segment assignments for verified students")
            
            # Get all verified students for this institution
            try:
                verified_students = db_client.supabase.table('user_institution_link')\
                    .select('id, user_id, student_consent, segment_id, user_profile!user_institution_link_user_fkey(id, name, email, student_id, account_type), institution_segments!user_institution_link_segment_id_fkey(segment_name)')\
                    .eq('institution_id', inst_id)\
                    .eq('student_consent', True)\
                    .eq('link_status', 'active')\
                    .eq('verification_status', 'verified')\
                    .execute()
                
                if verified_students.data and len(verified_students.data) > 0:
                    st.write(f"**{len(verified_students.data)} verified student(s):**")
                    
                    # Add search and filter controls
                    col_search, col_segment = st.columns([2, 1])
                    
                    with col_search:
                        search_term = st.text_input(
                            "🔍 Search students",
                            placeholder="Search by name, email, or student ID...",
                            key="student_search",
                            help="Filter students by name, email address, or student ID"
                        ).strip().lower()
                    
                    with col_segment:
                        # Get all available segments for filter dropdown
                        all_segments = ["All Segments"]
                        segment_id_map = {"All Segments": None}
                        
                        try:
                            available_segments = db_client.supabase.table('institution_segments')\
                                .select('id, segment_name')\
                                .eq('institution_id', inst_id)\
                                .execute()
                            
                            if available_segments.data:
                                for seg in available_segments.data:
                                    all_segments.append(seg['segment_name'])
                                    segment_id_map[seg['segment_name']] = seg['id']
                        except Exception as e:
                            st.warning(f"Could not load segments for filter: {e}")
                        
                        selected_segment_filter = st.selectbox(
                            "📁 Filter by Segment",
                            options=all_segments,
                            key="segment_filter",
                            help="Show only students from selected segment"
                        )
                    
                    # Apply filters to the student data
                    filtered_students = verified_students.data
                    
                    # Apply search filter
                    if search_term:
                        filtered_students = [
                            student for student in filtered_students
                            if search_term in student.get('user_profile', {}).get('name', '').lower() or
                               search_term in student.get('user_profile', {}).get('email', '').lower() or
                               search_term in str(student.get('user_profile', {}).get('student_id', '')).lower()
                        ]
                    
                    # Apply segment filter
                    if selected_segment_filter != "All Segments":
                        target_segment_id = segment_id_map.get(selected_segment_filter)
                        filtered_students = [
                            student for student in filtered_students
                            if student.get('segment_id') == target_segment_id
                        ]
                    
                    # Show filtered count
                    if len(filtered_students) != len(verified_students.data):
                        st.info(f"Showing {len(filtered_students)} of {len(verified_students.data)} students")
                    
                    if filtered_students:
                        # Group filtered students by segment for better organization
                        students_by_segment = {}
                        for student in filtered_students:
                            segment = student.get('institution_segments', {})
                            segment_name = segment.get('segment_name', 'Not Assigned') if segment else 'Not Assigned'
                            
                            if segment_name not in students_by_segment:
                                students_by_segment[segment_name] = []
                            students_by_segment[segment_name].append(student)
                        
                        # Display students grouped by segment
                        for segment_name, students in students_by_segment.items():
                            with st.expander(f"📁 {segment_name} ({len(students)} student{'s' if len(students) > 1 else ''})", expanded=False):
                                for student in students:
                                    user_profile = student.get('user_profile', {})
                                    student_name = user_profile.get('name', 'Unknown')
                                    student_email = user_profile.get('email', 'Unknown')
                                    current_student_id = user_profile.get('student_id', '')
                                    
                                    with st.container():
                                        col_info, col_edit = st.columns([3, 2])
                                        
                                        with col_info:
                                            st.write(f"**{student_name}**")
                                            st.caption(f"📧 {student_email}")
                                            st.caption(f"🆔 Current Student ID: {current_student_id or 'Not set'}")
                                        
                                        with col_edit:
                                            # Edit button for this student
                                            edit_key = f"edit_student_{student['id']}"
                                            if st.button("✏️ Edit", key=edit_key, width='stretch'):
                                                edit_student_dialog(student, inst_id)
                        
                    else:
                        if search_term or selected_segment_filter != "All Segments":
                            st.info("No students match your current filters. Try adjusting your search or segment filter.")
                        else:
                            st.info("No verified students found for your institution.")
                    
                else:
                    st.info("No verified students found for your institution.")
                    
            except Exception as e:
                st.error(f"Error loading verified students: {e}")
        
        # Only show divider if institution content was displayed (i.e., user is not a viewer)
        if not user_is_viewer:
            st.divider()
    except Exception as e:
        st.error(f"Error loading institution settings: {e}")

# Logout Section
if st.button("🚪 Logout", width='stretch', type="primary"):
    auth_service.logout()
    st.rerun()


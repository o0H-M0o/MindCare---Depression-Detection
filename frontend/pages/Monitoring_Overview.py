"""
Monitoring Overview - Quick summary of all linked users' mental health status
Shows which users need attention vs. those doing well
"""

import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from utils.auth import init_auth_service
from utils.user_service import UserService
from utils.auth_sidebar import render_auth_sidebar
from utils.db_client import DBClient
from utils.depression_detection import analyze_depression, prepare_dashboard_data, evaluate_recent_data_requirements
from utils.export_utils import df_to_csv_bytes, figs_to_pdf_bytes, dashboard_to_pdf_bytes

# Page config
st.set_page_config(
    page_title="Monitoring Overview",
    page_icon="📊",
    layout="wide"
)

# Initialize services
auth_service = init_auth_service()

# Get current viewer (must be authenticated)
viewer = auth_service.get_current_user()
if not viewer:
    st.error("Authentication required")
    st.stop()

# Initialize DBClient with viewer's user_id
db_client = DBClient(user_id=viewer['id'])
user_service = UserService(db_client.supabase)

# Render auth sidebar
render_auth_sidebar(auth_service)

# Require authentication and viewer or institution role
auth_service.require_auth()
auth_service.require_role(['viewer', 'institution'])

# Get user profile and role
user_profile = auth_service.get_user_profile()
user_role = auth_service.get_user_role()

col_title, col_btn = st.columns([4, 1])
with col_title:
    st.title("📊 Monitoring Overview")
with col_btn:
    st.write("")
    st.write("")

st.write(f"Welcome, **{user_profile.get('name', 'User')}**")
st.caption("Quick overview of all users' mental health status to help you prioritize your support.")

# Get linked users
with st.spinner("Loading linked users..."):
    linked_users = user_service.get_linked_users_for_viewer(viewer['id'])

if not linked_users:
    st.info("ℹ️ No users are currently linked to your account.")
    st.write("""
        **How to get access:**
    - Individual users can opt-in to share their data through their Settings page""")
    st.stop()

st.write(f"Monitoring **{len(linked_users)} user(s)**")

# --- Controls: Search and Segment filter (match Institution Dashboard) ---
inst_id = None
segments = []
try:
    staff_info = db_client.supabase.table('institution_staff')\
        .select('institution_id')\
        .eq('user_id', viewer['id'])\
        .eq('status', 'approved')\
        .execute()
    if getattr(staff_info, 'data', None) and len(staff_info.data) > 0:
        inst_id = staff_info.data[0].get('institution_id')
except Exception:
    inst_id = None

if inst_id:
    try:
        seg_resp = db_client.supabase.table('institution_segments')\
            .select('segment_name')\
            .eq('institution_id', inst_id)\
            .order('segment_name')\
            .execute()
        if getattr(seg_resp, 'data', None):
            segments = [s.get('segment_name') for s in seg_resp.data if s.get('segment_name')]
    except Exception:
        segments = []

col_search, col_seg = st.columns([3, 1])
with col_search:
    if user_role == 'institution':
        search_query = st.text_input("Search by name or student ID", value="", placeholder="Name or Student ID")
    else:
        search_query = st.text_input("Search by name", value="", placeholder="Name")
with col_seg:
    # Only show segment filter for institution staff
    if user_role == 'institution' and inst_id and segments:
        seg_options = ["All segments"] + segments
        selected_segment = st.selectbox("Filter by segment", options=seg_options)
    else:
        selected_segment = None

st.divider()

# Analyze all users
users_need_attention = []
users_doing_well = []
users_no_data = []

with st.spinner("Analyzing all users...It might take some time to load."):
    for user in linked_users:
        try:
            user_df = prepare_dashboard_data(DBClient(user_id=user['id']), window_days=90)
            user_segment = (user.get('segment_name') or user.get('segment') or user.get('institution_segment') or '').strip()
            
            if user_df is None or user_df.empty:
                users_no_data.append({
                    'name': user['name'],
                    'student_id': user.get('student_id', 'N/A'),
                    'segment_name': user_segment,
                    'access_type': user.get('access_type', 'unknown').replace('_', ' ').title(),
                    'institution_name': user.get('institution_name', 'N/A')
                })
                continue

            # Only consider users with enough recent data
            req = evaluate_recent_data_requirements(user_df, window_days=30, min_entries=10, min_distinct_days=5)
            if not req.get('meets', False):
                users_no_data.append({
                    'name': user['name'],
                    'student_id': user.get('student_id', 'N/A'),
                    'segment_name': user_segment,
                    'access_type': user.get('access_type', 'unknown').replace('_', ' ').title(),
                    'institution_name': user.get('institution_name', 'N/A'),
                    'reason': f"{req.get('recent_entries', 0)} entries / {req.get('distinct_days', 0)} days (last 30d)"
                })
                continue
            
            analysis = analyze_depression(user_df, window_days=30)
            
            user_info = {
                'name': user['name'],
                'student_id': user.get('student_id', 'N/A'),
                'segment_name': user_segment,
                'access_type': user.get('access_type', 'unknown').replace('_', ' ').title(),
                'institution_name': user.get('institution_name', 'N/A'),
                'severity': analysis.get('overall_severity', 'Unknown'),
                'trend': analysis.get('trend_direction', 'Unknown'),
                'confidence': analysis.get('confidence_level', 'N/A'),
                'last_entry_date': user_df['datetime'].max().strftime('%b %d, %Y') if not user_df.empty else 'N/A'
            }
            
            if analysis.get("depression_detected", False):
                users_need_attention.append(user_info)
            else:
                users_doing_well.append(user_info)
                
        except Exception as e:
            st.error(f"Error analyzing {user['name']}: {str(e)}")
            users_no_data.append({
                'name': user['name'],
                'student_id': user.get('student_id', 'N/A'),
                'segment_name': (user.get('segment_name') or user.get('segment') or user.get('institution_segment') or '').strip(),
                'access_type': user.get('access_type', 'unknown').replace('_', ' ').title(),
                'institution_name': user.get('institution_name', 'N/A')
            })

# Export buttons moved to bottom of page

# Apply filters
def apply_filters(user_list):
    filtered = user_list.copy()
    
    # Search filter (role-specific)
    if search_query:
        q = search_query.lower()
        if user_role == 'institution':
            filtered = [u for u in filtered if q in u['name'].lower() or q in str(u.get('student_id', '')).lower()]
        else:
            filtered = [u for u in filtered if q in u['name'].lower()]

    # Segment filter (only for institution role)
    if user_role == 'institution' and selected_segment and selected_segment != "All segments":
        def user_segment(u):
            return (u.get('segment_name') or u.get('segment') or u.get('institution_segment') or '').strip()
        filtered = [u for u in filtered if user_segment(u) and selected_segment.lower() == user_segment(u).lower()]
    
    return filtered

# Apply filters to all lists
users_need_attention_filtered = apply_filters(users_need_attention)
users_doing_well_filtered = apply_filters(users_doing_well)
users_no_data_filtered = apply_filters(users_no_data)

# Summary statistics (moved to top after analysis)
st.markdown("### 📈 Summary Statistics")
col1, col2, col3 = st.columns(3)

use_filtered_data = bool(search_query) or (
    user_role == 'institution' and selected_segment and selected_segment != "All segments"
)

total_attention = len(users_need_attention)
total_well = len(users_doing_well)
total_no_data = len(users_no_data)

shown_attention = len(users_need_attention_filtered)
shown_well = len(users_doing_well_filtered)
shown_no_data = len(users_no_data_filtered)

total_all = total_attention + total_well + total_no_data
shown_all = shown_attention + shown_well + shown_no_data

with col1:
    st.metric(
        "⚠️ Showing Sign of Depression",
        shown_attention if use_filtered_data else total_attention,
        delta=f"{shown_attention}/{total_attention} shown" if use_filtered_data else None,
        help="Users showing signs of persistent emotional distress"
    )

with col2:
    st.metric(
        "✅ No Sign of Depression",
        shown_well if use_filtered_data else total_well,
        delta=f"{shown_well}/{total_well} shown" if use_filtered_data else None,
        help="Users with no signs of depression"
    )

with col3:
    st.metric(
        "ℹ️ Insufficient Data",
        shown_no_data if use_filtered_data else total_no_data,
        delta=f"{shown_no_data}/{total_no_data} shown" if use_filtered_data else None,
        help="Users who need more journal entries"
    )

# Summary counts chart (calm horizontal bar)
try:
    summary_counts = {
        'Depressed': shown_attention if use_filtered_data else total_attention,
        'Not Depressed': shown_well if use_filtered_data else total_well,
        'Insufficient Data': shown_no_data if use_filtered_data else total_no_data,
    }
    df_summary = pd.DataFrame(list(summary_counts.items()), columns=['Category', 'Number of Users'])
    color_map_summary = {
        'Depressed': '#F4A59A',
        'Not Depressed': '#A8D5A2',
        'Insufficient Data': '#CFCFCF'
    }
    fig_summary = px.bar(
        df_summary,
        x='Number of Users',
        y='Category',
        orientation='h',
        color='Category',
        color_discrete_map=color_map_summary,
        text='Number of Users'
    )
    fig_summary.update_traces(textposition='outside')
    fig_summary.update_layout(height=240, margin=dict(l=40, r=40, t=40, b=40), showlegend=False)
    st.plotly_chart(fig_summary, width='stretch')
except Exception:
    pass

st.divider()

# === AGGREGATE VISUALIZATIONS ===
if (users_need_attention_filtered if use_filtered_data else users_need_attention) or (users_doing_well_filtered if use_filtered_data else users_doing_well):
    # Combine all users with data for aggregate analysis (respect filters)
    all_users_with_data = (users_need_attention_filtered + users_doing_well_filtered) if use_filtered_data else (users_need_attention + users_doing_well)
    
    viz_col1, viz_col2 = st.columns(2)
    
    with viz_col1:
        # Severity Distribution
        st.markdown("#### 🎯 Recent Emotional Distress Level")
        severity_counts = {}
        for user in all_users_with_data:
            sev = user.get('severity', 'Unknown')
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        
        if severity_counts:
            severity_df = pd.DataFrame(list(severity_counts.items()), columns=['Severity', 'Count'])
            # Define color map for severity
            # Calmer palette: soft greens/blues/peach for a gentler look
            color_map = {
                'Minimal': '#A8D5A2',  # soft green
                'Mild': '#C6DEC9',     # muted mint
                'Moderate': '#F6D7B0', # soft peach
                'Severe': '#F4A59A',   # muted coral
                'Unknown': '#CFCFCF'   # soft grey
            }
            fig_severity = px.pie(
                severity_df,
                names='Severity',
                values='Count',
                color='Severity',
                color_discrete_map=color_map,
                hole=0.4
            )
            fig_severity.update_traces(textposition='inside', textinfo='percent+label')
            fig_severity.update_layout(height=300, margin=dict(l=40, r=40, t=40, b=40), showlegend=True)
            st.plotly_chart(fig_severity, width='stretch')
        else:
            st.info("No severity data available")
    
    with viz_col2:
        # Trend Direction
        st.markdown("#### 📈 Trend Direction")
        trend_counts = {}
        for user in all_users_with_data:
            trend = user.get('trend', 'Unknown')
            trend_counts[trend] = trend_counts.get(trend, 0) + 1
        
        if trend_counts:
            trend_df = pd.DataFrame(list(trend_counts.items()), columns=['Trend', 'Count'])
            # Map trends to friendly labels with emojis
            trend_df['Display'] = trend_df['Trend'].apply(lambda x: 
                f"{x}" if x == "Improving" else f"{x}" if x == "Stable" else f"{x}" if x == "Worsening" else x
            )
            
            # Single-color bar chart - default blue
            single_color = '#1f77b4'
            fig_trend = px.bar(
                trend_df,
                x='Display',
                y='Count',
                color_discrete_sequence=[single_color],
                labels={'Display': 'Trend Direction', 'Count': 'Number of Users'}
            )
            fig_trend.update_layout(height=300, margin=dict(l=40, r=40, t=40, b=40), showlegend=False)
            st.plotly_chart(fig_trend, width='stretch')
        else:
            st.info("No trend data available")
    
    st.divider()

# SECTION 1: Users who need attention (Priority - Shown in expander)
segment_by_student_id = {}
segment_by_name = {}
if user_role == 'institution':
    def _extract_segment(u: dict) -> str:
        return (u.get('segment_name') or u.get('segment') or u.get('institution_segment') or '').strip()

    for u in linked_users:
        seg = _extract_segment(u)
        if not seg:
            continue
        sid = str(u.get('student_id') or '').strip()
        if sid and sid.lower() != 'n/a':
            segment_by_student_id[sid] = seg
        name = str(u.get('name') or '').strip()
        if name:
            segment_by_name[name] = seg

def _lookup_segment(name_val, student_id_val) -> str:
    # prefer id lookup, then name
    sid = str(student_id_val or '').strip()
    if sid and sid.lower() != 'n/a' and sid in segment_by_student_id:
        return segment_by_student_id[sid]
    nm = str(name_val or '').strip()
    return segment_by_name.get(nm, '')

if users_need_attention_filtered:
    with st.expander(f"⚠️ Users Showing Sign of Depression ({len(users_need_attention_filtered)} user(s))", expanded=True):
        st.caption("Users showing signs of persistent emotional distress")
        
        # Convert to DataFrame for table display
        df_need_attention = pd.DataFrame(users_need_attention_filtered)
        
        # Create a cleaner display dataframe
        display_cols_attention = {
            '👤 Name': df_need_attention['name'],
        }
        if user_role == 'institution':
            display_cols_attention['🎓 Student ID'] = df_need_attention.get('student_id', 'N/A')
            display_cols_attention['🧩 Segment'] = df_need_attention.apply(
                lambda r: (r.get('segment_name') or r.get('segment') or r.get('institution_segment') or '').strip()
                or _lookup_segment(r.get('name'), r.get('student_id')),
                axis=1
            )
        display_cols_attention.update({
            '📊 Recent Emotional Distress Level': df_need_attention['severity'],
            '📈 Trend': df_need_attention['trend'].apply(lambda x:
                f"↗️ {x}" if x == "Improving" else f"→ {x}" if x == "Stable" else f"↘️ {x}"),
            '📅 Last Entry': df_need_attention['last_entry_date']
        })
        display_df_attention = pd.DataFrame(display_cols_attention)
        
        # Display as interactive table
        st.dataframe(
            display_df_attention,
            width='stretch',
            hide_index=True,
            height=min(400, len(display_df_attention) * 35 + 38)  # Dynamic height based on rows
        )
elif users_need_attention:
    st.info(f"⚠️ {len(users_need_attention)} user(s) are showing signs of depression, but none match your search.")

# SECTION 2: Users who are doing well (Compact table view in expander)
if users_doing_well_filtered:
    with st.expander(f"✅ Users With No Sign of Depression ({len(users_doing_well_filtered)} user(s))", expanded=False):
        st.caption("Users showing no signs of depression")
        
        # Convert to DataFrame for table display
        df_doing_well = pd.DataFrame(users_doing_well_filtered)
        
        # Create a cleaner display dataframe
        display_cols_well = {
            '👤 Name': df_doing_well['name'],
        }
        if user_role == 'institution':
            display_cols_well['🎓 Student ID'] = df_doing_well.get('student_id', 'N/A')
            display_cols_well['🧩 Segment'] = df_doing_well.apply(
                lambda r: (r.get('segment_name') or r.get('segment') or r.get('institution_segment') or '').strip()
                or _lookup_segment(r.get('name'), r.get('student_id')),
                axis=1
            )
        display_cols_well.update({
            '📊 Recent Emotional Distress Level': df_doing_well['severity'],
            '📈 Trend': df_doing_well['trend'].apply(lambda x:
                f"↗️ {x}" if x == "Improving" else f"→ {x}" if x == "Stable" else f"↘️ {x}"),
            '📅 Last Entry': df_doing_well['last_entry_date']
        })
        display_df = pd.DataFrame(display_cols_well)
        
        # Display as interactive table
        st.dataframe(
            display_df,
            width='stretch',
            hide_index=True,
            height=min(400, len(display_df) * 35 + 38)  # Dynamic height based on rows
        )
elif users_doing_well:
    st.info(f"✅ {len(users_doing_well)} user(s) have no sign of depression, but none match your search.")

# SECTION 3: Users with no data (Collapsible)
if users_no_data_filtered:
    with st.expander(f"ℹ️ Users With Insufficient Data ({len(users_no_data_filtered)} user(s))", expanded=False):
        st.caption("These users need more journal entries before analysis can be performed")

        df_no_data = pd.DataFrame(users_no_data_filtered)
        display_cols_no = {
            '👤 Name': df_no_data.get('name', ''),
        }
        if user_role == 'institution':
            display_cols_no['🎓 Student ID'] = df_no_data.get('student_id', 'N/A')
            display_cols_no['🧩 Segment'] = df_no_data.apply(
                lambda r: (r.get('segment_name') or r.get('segment') or r.get('institution_segment') or '').strip()
                or _lookup_segment(r.get('name'), r.get('student_id')),
                axis=1
            )
        else:
            display_cols_no['🎓 Student ID'] = df_no_data.get('student_id', 'N/A')
        display_cols_no['ℹ️ Status'] = df_no_data.get('reason', 'Insufficient data')
        display_no_data = pd.DataFrame(display_cols_no)

        st.dataframe(
            display_no_data,
            width='stretch',
            hide_index=True,
            height=min(400, len(display_no_data) * 35 + 38)
        )
elif users_no_data:
    st.info(f"ℹ️ {len(users_no_data)} user(s) have insufficient data, but none match your current search.")

# Action guidance
st.divider()
st.info("💡 **Next Steps:** Click on 'Analysis Details' in the sidebar to view detailed insights for each user.")

st.divider()

# EXPORT SECTION - CSV and PDF at bottom
st.subheader("📥 Export Data")

export_col1, export_col2 = st.columns(2)

with export_col1:
    # CSV export
    try:
        # Build export DF in a way that preserves a real boolean depression column
        # and reliably fills segment from linked user records.
        if users_need_attention or users_doing_well or users_no_data:
            def _extract_segment(u: dict) -> str:
                return (u.get('segment_name') or u.get('segment') or u.get('institution_segment') or '').strip()

            segment_by_student_id = {}
            segment_by_name = {}
            for u in linked_users:
                seg = _extract_segment(u)
                if seg:
                    sid = str(u.get('student_id') or '').strip()
                    if sid and sid.lower() != 'n/a':
                        segment_by_student_id[sid] = seg
                    name = str(u.get('name') or '').strip()
                    if name:
                        segment_by_name[name] = seg

            df_need = pd.DataFrame(users_need_attention)
            if not df_need.empty:
                df_need['depression'] = True

            df_well = pd.DataFrame(users_doing_well)
            if not df_well.empty:
                df_well['depression'] = False

            df_no = pd.DataFrame(users_no_data)
            if not df_no.empty:
                df_no['depression'] = pd.NA

            df_export = pd.concat([df_need, df_well, df_no], ignore_index=True, sort=False)

            # Ensure depression is a boolean dtype (nullable)
            if 'depression' in df_export.columns:
                df_export['depression'] = df_export['depression'].astype('boolean')

            # Add/normalize segment column (prefer existing, otherwise lookup from linked_users)
            def _segment_for_row(r) -> str:
                existing = (r.get('segment_name') or r.get('segment') or r.get('institution_segment') or '').strip()
                if existing:
                    return existing
                sid = str(r.get('student_id') or '').strip()
                if sid and sid.lower() != 'n/a' and sid in segment_by_student_id:
                    return segment_by_student_id[sid]
                name = str(r.get('name') or '').strip()
                return segment_by_name.get(name, '')

            df_export['segment'] = df_export.apply(_segment_for_row, axis=1)

            # Drop columns not needed in the monitoring CSV
            df_export = df_export.drop(
                columns=[
                    'access_type',
                    'institution_name',
                    'confidence',
                    'confidence_level',
                    # internal/raw segment fields; keep normalized 'segment'
                    'segment_name',
                    'institution_segment',
                ],
                errors='ignore'
            )

            # Rename columns per monitoring export spec
            df_export = df_export.rename(
                columns={
                    'severity': 'recent_emotional_distress_level',
                    'reason': 'insufficient_data',
                }
            )

            # Reorder columns: put segment beside student_id (only for institution role)
            if user_role == 'institution':
                preferred_order = ['name', 'student_id', 'segment']
                cols = list(df_export.columns)
                ordered_cols = [c for c in preferred_order if c in cols] + [c for c in cols if c not in preferred_order]
                df_export = df_export[ordered_cols]
            else:
                # For viewers, exclude student_id and segment columns
                df_export = df_export.drop(columns=['student_id', 'segment'], errors='ignore')
                # Reorder columns for viewers
                preferred_order = ['name']
                cols = list(df_export.columns)
                ordered_cols = [c for c in preferred_order if c in cols] + [c for c in cols if c not in preferred_order]
                df_export = df_export[ordered_cols]

            csv_export = df_export.to_csv(index=False)
            
            st.download_button(
                label="📄 Download CSV",
                data=csv_export,
                file_name=f"monitoring_overview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                help="Download aggregate monitoring data",
                use_container_width=True
            )
        else:
            st.info("No data available for export")
    except Exception as e:
        st.error(f"CSV export error: {e}")

with export_col2:
    # PDF export
    try:
        viz_figs = []
        # if 'fig_summary' in locals():
        #     viz_figs.append({'fig': locals()['fig_summary'], 'title': 'Summary Statistics'})
        if 'fig_severity' in locals():
            viz_figs.append({'fig': locals()['fig_severity'], 'title': 'Recent Emotional Distress Level'})
        if 'fig_trend' in locals():
            viz_figs.append({'fig': locals()['fig_trend'], 'title': 'Trend Direction'})

        if viz_figs:
            with st.spinner("Preparing PDF..."):
                generated_on = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                filters = {
                    'Search': (search_query or '').strip() or 'None',
                }
                if user_role == 'institution' and selected_segment:
                    filters['Segment'] = selected_segment
                else:
                    filters['Segment'] = 'All segments'

                summary_stats = {
                    'Users showing sign of depression': len(users_need_attention_filtered),
                    'Users with no sign of depression': len(users_doing_well_filtered),
                    'Users with insufficient data': len(users_no_data_filtered),
                    'Total users (after filters)': len(users_need_attention_filtered) + len(users_doing_well_filtered) + len(users_no_data_filtered),
                }

                tables = []

                df_att = pd.DataFrame(users_need_attention_filtered)
                if not df_att.empty:
                    if user_role == 'institution':
                        tables.append({
                            'title': 'Users Showing Sign of Depression',
                            'df': pd.DataFrame({
                                'Name': df_att.get('name', ''),
                                'Student ID': df_att.get('student_id', 'N/A'),
                                'Segment': df_att.apply(lambda rr: _seg_for_row(rr), axis=1),
                                'Recent Emotional Distress Level': df_att.get('severity', ''),
                                'Trend': df_att.get('trend', ''),
                                'Last Entry': df_att.get('last_entry_date', ''),
                            })
                        })
                    else:
                        # For viewers, exclude student_id and segment
                        tables.append({
                            'title': 'Users Showing Sign of Depression',
                            'df': pd.DataFrame({
                                'Name': df_att.get('name', ''),
                                'Recent Emotional Distress Level': df_att.get('severity', ''),
                                'Trend': df_att.get('trend', ''),
                                'Last Entry': df_att.get('last_entry_date', ''),
                            })
                        })

                df_well = pd.DataFrame(users_doing_well_filtered)
                if not df_well.empty:
                    if user_role == 'institution':
                        tables.append({
                            'title': 'Users With No Sign of Depression',
                            'df': pd.DataFrame({
                                'Name': df_well.get('name', ''),
                                'Student ID': df_well.get('student_id', 'N/A'),
                                'Segment': df_well.apply(lambda rr: _seg_for_row(rr), axis=1),
                                'Recent Emotional Distress Level': df_well.get('severity', ''),
                                'Trend': df_well.get('trend', ''),
                                'Last Entry': df_well.get('last_entry_date', ''),
                            })
                        })
                    else:
                        # For viewers, exclude student_id and segment
                        tables.append({
                            'title': 'Users With No Sign of Depression',
                            'df': pd.DataFrame({
                                'Name': df_well.get('name', ''),
                                'Recent Emotional Distress Level': df_well.get('severity', ''),
                                'Trend': df_well.get('trend', ''),
                                'Last Entry': df_well.get('last_entry_date', ''),
                            })
                        })

                df_no = pd.DataFrame(users_no_data_filtered)
                if not df_no.empty:
                    if user_role == 'institution':
                        tables.append({
                            'title': 'Users With Insufficient Data',
                            'df': pd.DataFrame({
                                'Name': df_no.get('name', ''),
                                'Student ID': df_no.get('student_id', 'N/A'),
                                'Segment': df_no.apply(lambda rr: _seg_for_row(rr), axis=1),
                                'Insufficient Data': df_no.get('reason', 'Insufficient data'),
                            })
                        })
                    else:
                        # For viewers, exclude student_id and segment
                        tables.append({
                            'title': 'Users With Insufficient Data',
                            'df': pd.DataFrame({
                                'Name': df_no.get('name', ''),
                                'Insufficient Data': df_no.get('reason', 'Insufficient data'),
                            })
                        })

                pdf_title = f"Monitoring Overview Report (Generated on {generated_on})"
                pdf_bytes = dashboard_to_pdf_bytes({
                    'summary_stats': summary_stats,
                    'filters': filters,
                    'tables': tables,
                    'figs': viz_figs,
                }, title=pdf_title)
            if pdf_bytes:
                st.download_button(
                    label="📊 Download PDF Report",
                    data=pdf_bytes,
                    file_name=f"monitoring_overview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
        else:
            st.info("No charts available for PDF export")
    except ImportError as ie:
        st.error(str(ie))
    except Exception as e:
        st.error(f"PDF export error: {e}")

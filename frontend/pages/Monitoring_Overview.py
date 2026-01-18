"""
Overview Dashboard - Quick summary of all linked users' mental health status
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
    page_title="Overview Dashboard",
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

# Helper function for segment extraction in PDF export
def _seg_for_row(row):
    """Extract segment name from a user data row for PDF export."""
    return (row.get('segment_name') or row.get('segment') or row.get('institution_segment') or '').strip() or 'N/A'

# Get user profile and role
user_profile = auth_service.get_user_profile()
user_role = auth_service.get_user_role()

col_title, col_btn = st.columns([4, 1])
with col_title:
    st.title("📊 Overview Dashboard")
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
                    'email': user.get('email') or 'N/A',
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
                    'email': user.get('email') or 'N/A',
                    'student_id': user.get('student_id', 'N/A'),
                    'segment_name': user_segment,
                    'access_type': user.get('access_type', 'unknown').replace('_', ' ').title(),
                    'institution_name': user.get('institution_name', 'N/A'),
                    'reason': f"{req.get('recent_entries', 0)} entries / {req.get('distinct_days', 0)} days (last 30d)",
                    'recent_entries_30d': int(req.get('recent_entries', 0) or 0),
                    'distinct_days_30d': int(req.get('distinct_days', 0) or 0),
                })
                continue
            
            analysis = analyze_depression(user_df, window_days=30)
            
            user_info = {
                'name': user['name'],
                'email': user.get('email') or 'N/A',
                'student_id': user.get('student_id', 'N/A'),
                'segment_name': user_segment,
                'access_type': user.get('access_type', 'unknown').replace('_', ' ').title(),
                'institution_name': user.get('institution_name', 'N/A'),
                'severity': analysis.get('overall_severity', 'Unknown'),
                'trend': analysis.get('trend_direction', 'Unknown'),
                'confidence': analysis.get('confidence_level', 'N/A'),
                'top_symptoms': analysis.get('top_symptoms', []) or [],
                'last_entry_dt': user_df['datetime'].max() if not user_df.empty else None,
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
                'email': user.get('email') or 'N/A',
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
all_users_with_data = (users_need_attention_filtered + users_doing_well_filtered) if use_filtered_data else (users_need_attention + users_doing_well)

# Build compact aggregate figures (rendered in tabs below)
fig_summary = None
fig_segment = None
fig_top_symptoms = None
fig_data_quality = None

# Support priority snapshot (pie)
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
    fig_summary = px.pie(
        df_summary,
        names='Category',
        values='Number of Users',
        color='Category',
        color_discrete_map=color_map_summary,
        hole=0.45,
    )
    fig_summary.update_traces(textposition='inside', textinfo='percent+label')
    fig_summary.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), showlegend=True)
except Exception:
    fig_summary = None

# Segment overview (institution only)
try:
    if user_role == 'institution':
        rows = []
        def _seg(u: dict) -> str:
            return (u.get('segment_name') or u.get('segment') or u.get('institution_segment') or '').strip() or 'Unassigned'

        src_attention = users_need_attention_filtered if use_filtered_data else users_need_attention
        src_well = users_doing_well_filtered if use_filtered_data else users_doing_well
        src_no = users_no_data_filtered if use_filtered_data else users_no_data

        for u in src_attention:
            rows.append({'segment': _seg(u), 'status': 'Depressed'})
        for u in src_well:
            rows.append({'segment': _seg(u), 'status': 'Not Depressed'})
        for u in src_no:
            rows.append({'segment': _seg(u), 'status': 'Insufficient Data'})

        if rows:
            seg_df = pd.DataFrame(rows)
            seg_counts = seg_df.groupby(['segment', 'status']).size().reset_index(name='count')
            fig_segment = px.bar(
                seg_counts,
                x='segment',
                y='count',
                color='status',
                barmode='stack',
                color_discrete_map={
                    'Depressed': '#F4A59A',
                    'Not Depressed': '#A8D5A2',
                    'Insufficient Data': '#CFCFCF',
                },
                labels={'segment': 'Segment', 'count': 'Users', 'status': ''}
            )
            fig_segment.update_layout(height=260, margin=dict(l=30, r=30, t=30, b=30), legend_title_text='')
except Exception:
    fig_segment = None

# Top symptoms (aggregate among depressed users)
try:
    src_for_symptoms = users_need_attention_filtered if use_filtered_data else users_need_attention
    symptom_counts = {}
    for u in src_for_symptoms:
        symptoms = u.get('top_symptoms', []) or []
        if isinstance(symptoms, str):
            try:
                symptoms = json.loads(symptoms)
            except Exception:
                symptoms = []
        if not isinstance(symptoms, list):
            symptoms = []
        for s in symptoms:
            s = str(s or '').strip()
            if not s:
                continue
            symptom_counts[s] = symptom_counts.get(s, 0) + 1

    if symptom_counts:
        df_sym = pd.DataFrame(
            sorted(symptom_counts.items(), key=lambda kv: kv[1], reverse=True)[:5],
            columns=['Symptom', 'Users']
        )
        fig_top_symptoms = px.bar(
            df_sym,
            x='Users',
            y='Symptom',
            orientation='h',
            color_discrete_sequence=['#1f77b4'],
        )
        fig_top_symptoms.update_layout(
            height=320,
            margin=dict(l=30, r=30, t=30, b=30),
            showlegend=False,
            yaxis={
                'categoryorder': 'array',
                'categoryarray': df_sym['Symptom'].tolist(),
                'autorange': 'reversed'
            }
        )
except Exception:
    fig_top_symptoms = None

# Data quality (insufficient data reasons)
try:
    src_no_data = users_no_data_filtered if use_filtered_data else users_no_data
    reason_counts = {
        'Too few entries': 0,
        'Too few days': 0,
        'Too few entries and days': 0,
        'Unknown': 0,
    }

    for u in src_no_data:
        re = u.get('recent_entries_30d')
        dd = u.get('distinct_days_30d')
        if re is None or dd is None:
            reason_counts['Unknown'] += 1
            continue
        try:
            re = int(re)
            dd = int(dd)
        except Exception:
            reason_counts['Unknown'] += 1
            continue

        low_entries = re < 10
        low_days = dd < 5
        if low_entries and low_days:
            reason_counts['Too few entries and days'] += 1
        elif low_entries:
            reason_counts['Too few entries'] += 1
        elif low_days:
            reason_counts['Too few days'] += 1
        else:
            reason_counts['Unknown'] += 1

    df_q = pd.DataFrame(
        [(k, v) for k, v in reason_counts.items() if v > 0],
        columns=['Reason', 'Users']
    )
    if not df_q.empty:
        fig_data_quality = px.bar(
            df_q,
            x='Reason',
            y='Users',
            color_discrete_sequence=['#1f77b4'],
        )
        fig_data_quality.update_layout(height=280, margin=dict(l=30, r=30, t=30, b=30), showlegend=False)
except Exception:
    fig_data_quality = None


# === MAIN TABS ===
tab_charts, tab_dep, tab_well, tab_no = st.tabs([
    "📊 Charts",
    f"⚠️ Depressed ({len(users_need_attention_filtered)})",
    f"✅ Not Depressed ({len(users_doing_well_filtered)})",
    f"ℹ️ Insufficient Data ({len(users_no_data_filtered)})",
])

with tab_charts:
    # Institution: 2x2 grid. Viewer: 2 charts first row + 1 full-width chart second row.

    row1_col1, row1_col2 = st.columns(2)
    with row1_col1:
        st.markdown("#### Support Priority Snapshot")
        if fig_summary is not None:
            st.plotly_chart(fig_summary, width='stretch')
        else:
            st.info("No snapshot chart available.")

    with row1_col2:
        if user_role == 'institution':
            st.markdown("#### Status by segment")
            if fig_segment is not None:
                st.plotly_chart(fig_segment, width='stretch')
            else:
                st.info("No segment chart available.")
        else:
            # Viewer: put Data Quality here instead of Segment
            st.markdown("#### Why some users have insufficient data")
            if fig_data_quality is not None:
                st.plotly_chart(fig_data_quality, width='stretch')
            else:
                st.info("No data quality chart available.")

    if user_role == 'institution':
        row2_col1, row2_col2 = st.columns(2)
        with row2_col1:
            st.markdown("#### Most common signals among users showing signs of depression")
            if fig_top_symptoms is not None:
                st.plotly_chart(fig_top_symptoms, width='stretch')
            else:
                st.info("No symptom signals available.")
        with row2_col2:
            st.markdown("#### Why some users have insufficient data")
            if fig_data_quality is not None:
                st.plotly_chart(fig_data_quality, width='stretch')
            else:
                st.info("No data quality chart available.")
    else:
        # Viewer: Signals in second row, full width (one column)
        st.markdown("#### Most common signals among users showing signs of depression")
        if fig_top_symptoms is not None:
            st.plotly_chart(fig_top_symptoms, width='stretch')
        else:
            st.info("No symptom signals available.")


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

def _base_table_cols(df: pd.DataFrame) -> dict:
    cols = {
        '👤 Name': df.get('name', ''),
        '📧 Email': df.get('email', 'N/A'),
    }
    if user_role == 'institution':
        cols['🎓 Student ID'] = df.get('student_id', 'N/A')
        cols['🧩 Segment'] = df.apply(
            lambda r: (r.get('segment_name') or r.get('segment') or r.get('institution_segment') or '').strip()
            or _lookup_segment(r.get('name'), r.get('student_id')),
            axis=1
        )
    return cols

with tab_dep:
    if users_need_attention_filtered:
        df_need_attention = pd.DataFrame(users_need_attention_filtered)
        display_cols = _base_table_cols(df_need_attention)
        display_cols['📅 Last Entry'] = df_need_attention.get('last_entry_date', 'N/A')
        st.dataframe(
            pd.DataFrame(display_cols),
            width='stretch',
            hide_index=True,
            height=360,
        )
    elif users_need_attention:
        st.info(f"⚠️ {len(users_need_attention)} user(s) are showing signs of depression, but none match your filters.")
    else:
        st.info("No users in this category.")

with tab_well:
    if users_doing_well_filtered:
        df_doing_well = pd.DataFrame(users_doing_well_filtered)
        display_cols = _base_table_cols(df_doing_well)
        display_cols['📅 Last Entry'] = df_doing_well.get('last_entry_date', 'N/A')
        st.dataframe(
            pd.DataFrame(display_cols),
            width='stretch',
            hide_index=True,
            height=360,
        )
    elif users_doing_well:
        st.info(f"✅ {len(users_doing_well)} user(s) have no sign of depression, but none match your filters.")
    else:
        st.info("No users in this category.")

with tab_no:
    if users_no_data_filtered:
        df_no_data = pd.DataFrame(users_no_data_filtered)
        display_cols = _base_table_cols(df_no_data)
        display_cols['ℹ️ Status'] = df_no_data.get('reason', 'Insufficient data')
        st.dataframe(
            pd.DataFrame(display_cols),
            width='stretch',
            hide_index=True,
            height=360,
        )
    elif users_no_data:
        st.info(f"ℹ️ {len(users_no_data)} user(s) have insufficient data, but none match your filters.")
    else:
        st.info("No users in this category.")

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
                    'severity',
                    'trend',
                    'top_symptoms',
                    'last_entry_date',
                    'recent_entries_30d',
                    'distinct_days_30d',
                ],
                errors='ignore'
            )

            # Rename columns per monitoring export spec
            df_export = df_export.rename(
                columns={
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
                width='stretch'
            )
        else:
            st.info("No data available for export")
    except Exception as e:
        st.error(f"CSV export error: {e}")

with export_col2:
    # PDF export
    try:
        viz_figs = []
        if fig_summary is not None:
            viz_figs.append({'fig': fig_summary, 'title': 'Support Priority Snapshot'})
        if user_role == 'institution' and fig_segment is not None:
            viz_figs.append({'fig': fig_segment, 'title': 'Status by Segment'})
        if fig_top_symptoms is not None:
            viz_figs.append({'fig': fig_top_symptoms, 'title': 'Most Common Signals (Top Symptoms)'})
        if fig_data_quality is not None:
            viz_figs.append({'fig': fig_data_quality, 'title': 'Data Quality: Insufficient Data Reasons'})

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

                tables = []

                df_att = pd.DataFrame(users_need_attention_filtered)
                if not df_att.empty:
                    if user_role == 'institution':
                        tables.append({
                            'title': 'Users Showing Sign of Depression',
                            'df': pd.DataFrame({
                                'Name': df_att.get('name', ''),
                                'Email': df_att.get('email', 'N/A'),
                                'Student ID': df_att.get('student_id', 'N/A'),
                                'Segment': df_att.apply(lambda rr: _seg_for_row(rr), axis=1),
                                'Last Entry': df_att.get('last_entry_date', ''),
                            })
                        })
                    else:
                        # For viewers, exclude student_id and segment
                        tables.append({
                            'title': 'Users Showing Sign of Depression',
                            'df': pd.DataFrame({
                                'Name': df_att.get('name', ''),
                                'Email': df_att.get('email', 'N/A'),
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
                                'Email': df_well.get('email', 'N/A'),
                                'Student ID': df_well.get('student_id', 'N/A'),
                                'Segment': df_well.apply(lambda rr: _seg_for_row(rr), axis=1),
                                'Last Entry': df_well.get('last_entry_date', ''),
                            })
                        })
                    else:
                        # For viewers, exclude student_id and segment
                        tables.append({
                            'title': 'Users With No Sign of Depression',
                            'df': pd.DataFrame({
                                'Name': df_well.get('name', ''),
                                'Email': df_well.get('email', 'N/A'),
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
                                'Email': df_no.get('email', 'N/A'),
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
                                'Email': df_no.get('email', 'N/A'),
                                'Insufficient Data': df_no.get('reason', 'Insufficient data'),
                            })
                        })

                pdf_title = f"Overview Dashboard Report (Generated on {generated_on})"
                pdf_bytes = dashboard_to_pdf_bytes({
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
                    width='stretch'
                )
        else:
            st.info("No charts available for PDF export")
    except ImportError as ie:
        st.error(str(ie))
    except Exception as e:
        st.error(f"PDF export error: {e}")


"""Logbook - Bulletproof maintenance logbook with CSV upload and AI analysis."""
import streamlit as st
import pandas as pd
from src.engine import run_logbook_forensic_audit
from src.config import Config

st.set_page_config(
    page_title="AeroMind Logbook",
    page_icon="🛩️",
    layout="wide",
)

# Match main app styling
st.markdown(
    """
    <style>
    :root { --text: #1e293b; --accent: #0d7377; --accent-bg: #f0fdfa; --surface: #f8fafc; }
    [data-testid="stChatMessage"] { background: var(--surface) !important; border-radius: 8px; border-left: 4px solid var(--accent) !important; }
    [data-testid="stChatMessage"] .stMarkdown { color: var(--text) !important; line-height: 1.6 !important; }
    [data-testid="stSidebar"] .stAlert { border-radius: 8px; border-left: 4px solid var(--accent); background: var(--accent-bg) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Validate configuration
try:
    Config.validate()
except ValueError as e:
    st.error(f"Configuration error: {e}")
    st.info("Please check your .env file and ensure all API keys are set.")
    st.stop()

st.title("🛩️ AeroMind: Maintenance Logbook Analysis")
st.markdown("""
Enter component data manually or upload a CSV export. AeroMind uses a **Forensic Audit** (Map-Reduce) 
architecture: each component is analyzed individually, then cross-referenced for system-wide anomalies.
This deep analysis takes 30-60 seconds but ensures accuracy—critical for aviation maintenance.
""")

# 1. Initialize Safe Session State with Sample Data
if "logbook_df" not in st.session_state:
    df = pd.DataFrame([
        {"Component": "Main Rotor Blades", "Part_Number": "C016-7", "Hours_Since_New": 1779.5, "Installed_Date": None},
        {"Component": "Magneto", "Part_Number": "10-600646-201", "Hours_Since_New": 726.0, "Installed_Date": None},
        {"Component": "ELT Battery", "Part_Number": "", "Hours_Since_New": None, "Installed_Date": None}
    ])
    # Convert Installed_Date to datetime type (None becomes NaT)
    df["Installed_Date"] = pd.to_datetime(df["Installed_Date"])
    # Ensure Part_Number uses empty string (not None) for consistency with Streamlit
    df["Part_Number"] = df["Part_Number"].fillna("").astype(str)
    st.session_state.logbook_df = df

# 2. File Uploader (Optional)
uploaded_file = st.file_uploader("Upload Digital Logbook (CSV)", type=["csv"])
if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file)
        # Ensure Installed_Date is datetime type if column exists
        if "Installed_Date" in df.columns:
            df["Installed_Date"] = pd.to_datetime(df["Installed_Date"], errors="coerce")
        # Ensure Part_Number uses empty string (not None) for consistency
        if "Part_Number" in df.columns:
            df["Part_Number"] = df["Part_Number"].fillna("").astype(str).str.strip()
        st.session_state.logbook_df = df
        st.success("CSV Uploaded Successfully.")
    except Exception as e:
        st.error(f"Error reading CSV: {e}")

st.divider()

# 3. Bug-Free Manual Entry Table with column_config constraints
st.subheader("Current Logbook Entries")
st.caption("Add, edit, or delete rows. The table enforces correct data types to prevent errors.")

# Normalize dataframe before passing to data_editor (ensure consistent dtypes)
df_for_editor = st.session_state.logbook_df.copy()
if "Part_Number" in df_for_editor.columns:
    df_for_editor["Part_Number"] = df_for_editor["Part_Number"].fillna("").astype(str)

edited_df = st.data_editor(
    df_for_editor,
    num_rows="dynamic",  # Allows adding/deleting rows
    width="stretch",
    column_config={
        "Component": st.column_config.TextColumn(
            "Component Name",
            required=True,
            help="Component name (e.g., Main Rotor Blades, Magneto)"
        ),
        "Part_Number": st.column_config.TextColumn(
            "Part Number",
            required=False,
            help="Part number from IPC (optional - leave empty if unknown, system will look it up)"
        ),
        "Hours_Since_New": st.column_config.NumberColumn(
            "Hours Since New",
            min_value=0.0,
            format="%.1f",
            help="Total hours on the component since new"
        ),
        "Installed_Date": st.column_config.DateColumn(
            "Date Installed",
            help="Date when component was installed (optional)"
        ),
    },
    hide_index=True,
)

# Save edits back to state (normalize Part_Number to handle empty strings consistently)
st.session_state.logbook_df = edited_df.copy()
if "Part_Number" in st.session_state.logbook_df.columns:
    st.session_state.logbook_df["Part_Number"] = st.session_state.logbook_df["Part_Number"].fillna("").astype(str)

st.divider()

# 4. The AI Execution - Map-Reduce Forensic Audit Pattern
if st.button("🔍 Generate Maintenance & Compliance Plan", type="primary"):
    if edited_df.empty:
        st.warning("Please add at least one component to analyze.")
    else:
        # Build rows in the same format as the API (single implementation: run_logbook_forensic_audit)
        rows = []
        for _, row in edited_df.iterrows():
            comp = str(row.get("Component", "")).strip()
            pn = row.get("Part_Number", "")
            if pd.isna(pn) or pn == "" or (isinstance(pn, str) and not pn.strip()):
                pn = ""
            else:
                pn = str(pn).strip()
            hours = row.get("Hours_Since_New")
            inst = row.get("Installed_Date")
            if pd.notna(inst) and inst is not None and hasattr(inst, "strftime"):
                inst = inst.strftime("%Y-%m-%d")
            else:
                inst = None
            rows.append({"Component": comp, "Part_Number": pn, "Hours_Since_New": hours, "Installed_Date": inst})

        progress_bar = st.progress(0)
        status_text = st.empty()
        status_text.text("🔍 Running Forensic Audit (Map + Reduce)... This may take 30–60 seconds.")
        progress_bar.progress(0.3)

        try:
            # Same function as the API: identical prompts, agentic mode, skip_regulation_check=True
            component_reports, synthesis_response, synthesis_sources = run_logbook_forensic_audit(rows)

            progress_bar.progress(1.0)
            status_text.text("✅ Forensic Audit Complete")

            # ===== PEDAGOGICAL OUTPUT (same as before) =====
            st.markdown("---")
            
            # System-Wide Anomaly Report (prominent at top)
            st.warning("⚠️ **SYSTEM-WIDE ANOMALY REPORT**")
            st.markdown(synthesis_response)
            
            if synthesis_sources:
                with st.expander("Anomaly Detection Sources", expanded=False):
                    for i, source in enumerate(synthesis_sources, 1):
                        st.markdown(
                            f"**Source {i}:**\n"
                            f"- **File:** {source.get('file_name', 'Unknown')}\n"
                            f"- **Page:** {source.get('page_number', 'Unknown')}"
                        )
            
            st.markdown("---")
            st.markdown("### 📋 Individual Component Audits")
            st.caption("Deep dive into each component's compliance status and remaining life.")
            
            # Display each component report in an expander
            for idx, comp_data in enumerate(component_reports, 1):
                pn_display = comp_data['part_number']
                if pn_display == "Looked up by system":
                    pn_display = "P/N: (looked up)"
                else:
                    pn_display = f"P/N: {pn_display}"
                with st.expander(
                    f"**{comp_data['component']}** ({pn_display})",
                    expanded=False
                ):
                    st.markdown(comp_data['report'])
                    
                    if comp_data['sources']:
                        st.markdown("**Sources:**")
                        for i, source in enumerate(comp_data['sources'], 1):
                            st.markdown(
                                f"{i}. {source.get('file_name', 'Unknown')}, "
                                f"Page {source.get('page_number', 'Unknown')}"
                            )
            
            # Clear progress indicators
            progress_bar.empty()
            status_text.empty()
            
        except Exception as e:
            progress_bar.empty()
            status_text.empty()
            st.error(f"An error occurred during forensic audit: {e}")
            import traceback
            with st.expander("Error Details"):
                st.code(traceback.format_exc())

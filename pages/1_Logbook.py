"""Logbook - Bulletproof maintenance logbook with CSV upload and AI analysis."""
import streamlit as st
import pandas as pd
import asyncio
import time
from datetime import datetime
from src.engine import ask_assistant
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
        # Initialize progress tracking
        total_rows = len(edited_df)
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        component_reports = []
        component_sources = []
        
        try:
            # ===== PHASE 1: MAP PHASE (Row-by-Row Deep Audit) =====
            status_text.text("🔍 Starting Forensic Audit: Analyzing each component individually...")
            
            for idx, (row_idx, row) in enumerate(edited_df.iterrows()):
                component = str(row.get("Component", "")).strip()
                part_number_raw = row.get("Part_Number", "")
                # Handle empty string, None, or NaN as "no part number"
                if pd.isna(part_number_raw) or part_number_raw == "" or (isinstance(part_number_raw, str) and not part_number_raw.strip()):
                    part_number = ""
                else:
                    part_number = str(part_number_raw).strip()
                hours = row.get("Hours_Since_New", None)
                installed_date = row.get("Installed_Date", None)
                
                # Format date if present
                date_str = "Not specified"
                if pd.notna(installed_date) and installed_date:
                    if isinstance(installed_date, str):
                        date_str = installed_date
                    elif hasattr(installed_date, "strftime"):
                        date_str = installed_date.strftime("%Y-%m-%d")
                    else:
                        date_str = str(installed_date)
                
                # Format hours
                hours_str = f"{hours:.1f} hours" if pd.notna(hours) and hours is not None else "Not specified"
                
                # Update progress (show part number only if available)
                progress = (idx + 1) / (total_rows + 1)  # +1 for reduce phase
                progress_bar.progress(progress)
                if part_number:
                    status_text.text(f"🔍 Auditing {component} (P/N: {part_number})... [{idx + 1}/{total_rows}]")
                else:
                    status_text.text(f"🔍 Auditing {component} (looking up part number)... [{idx + 1}/{total_rows}]")
                
                # Micro-Prompt for this specific component
                if part_number:
                    pn_context = f"Part Number (P/N): {part_number}"
                    search_instruction = f"Search the Aircraft Maintenance Manual (AMM) for the exact flight hour limit OR calendar time limit for Part Number {part_number}. If not found, search by component name \"{component}\"."
                else:
                    pn_context = "Part Number (P/N): Not provided - you must look it up"
                    search_instruction = f"FIRST: Search the Illustrated Parts Catalog (IPC) or AMM to find the Part Number for component \"{component}\". THEN search for the exact flight hour limit OR calendar time limit using the Part Number you found (or component name if P/N still not found)."
                
                micro_prompt = f"""You are auditing a single component for compliance. Act as AeroMind, the Senior Lead Engineer.

COMPONENT DETAILS:
- Component Name: {component}
- {pn_context}
- Hours Since New: {hours_str}
- Date Installed: {date_str}

AUDIT TASKS:
1. {search_instruction}
2. Search for the mandated inspection or replacement procedure for this component.
3. Calculate the component's current status:
   - If Hours_Since_New is provided: Compare against the hour limit from the manual.
   - If Installed_Date is provided: Calculate calendar days elapsed and compare against calendar limit.
   - Determine if COMPLIANT, DUE SOON (within 10% of limit), or OVERDUE.
4. Calculate remaining life (if applicable).

OUTPUT FORMAT:
Provide a highly detailed 3-bullet summary:
• **Part Number Found:** [P/N if looked up, or "P/N: {part_number}" if provided] - **Limit Found:** [Exact limit from manual with citation, e.g., "IAW AMM 20-10-00, p. 5: 2000 hours"]
• **Current Status:** [COMPLIANT / DUE SOON / OVERDUE] - [Reasoning with calculation]
• **Remaining Life:** [Hours/days remaining or "OVERDUE by X hours/days"]

Always cite the exact AMM source (document name and page number)."""
                
                # Call agent for this row (skip regulation check - this is maintenance compliance, not regulatory)
                try:
                    response_text, source_nodes = ask_assistant(
                        micro_prompt,
                        use_chat_mode=True,  # Agentic mode for deep search
                        skip_regulation_check=True,  # Bypass regulation path - this is maintenance audit, not regulatory
                    )
                    component_reports.append({
                        "component": component,
                        "part_number": part_number or "Looked up by system",
                        "report": response_text,
                        "sources": source_nodes,
                    })
                    component_sources.extend(source_nodes)
                except Exception as e:
                    component_reports.append({
                        "component": component,
                        "part_number": part_number or "Looked up by system",
                        "report": f"❌ Error auditing this component: {str(e)}",
                        "sources": [],
                    })
                
                # Anti-burst delay: space out requests to stay under 30k TPM
                if idx + 1 < total_rows:
                    progress_bar.progress(progress, text="Rate limit cooldown... moving to next component")
                    time.sleep(8)
            
            # ===== PHASE 2: REDUCE PHASE (Cross-System Anomaly Detection) =====
            progress_bar.progress(0.95)
            status_text.text("🔍 Running Cross-System Anomaly Detection...")
            
            # Truncate each report to stay under OpenAI token limit (~30k TPM); ~4 chars/token
            MAX_CHARS_PER_REPORT = 2500   # ~600 tokens per component
            MAX_TOTAL_CONTEXT_CHARS = 18000  # ~4.5k tokens for context
            def truncate(s: str, max_len: int) -> str:
                s = (s or "").strip()
                return s[:max_len] + ("..." if len(s) > max_len else "")
            
            parts = []
            total_len = 0
            for r in component_reports:
                block = f"**{r['component']}** (P/N: {r['part_number']})\n\n{truncate(r['report'], MAX_CHARS_PER_REPORT)}"
                if total_len + len(block) > MAX_TOTAL_CONTEXT_CHARS:
                    block = truncate(block, max(500, MAX_TOTAL_CONTEXT_CHARS - total_len - 100))
                parts.append(block)
                total_len += len(block)
                if total_len >= MAX_TOTAL_CONTEXT_CHARS:
                    break
            full_context = "\n\n---\n\n".join(parts)
            if total_len >= MAX_TOTAL_CONTEXT_CHARS or any(len((r["report"] or "")) > MAX_CHARS_PER_REPORT for r in component_reports):
                full_context = "(Reports truncated for token limit.)\n\n" + full_context
            
            # Synthesis prompt for anomaly detection (kept short to avoid 429)
            synthesis_prompt = f"""You are a Senior Aerospace Engineer performing a final forensic review of a compiled component audit.

COMPONENT AUDIT REPORTS:
{full_context}

ANOMALY DETECTION TASKS:
1. **Cross-Component Logic Check:** Look for logical anomalies between components. For example:
   - Component A was replaced but Component B (which must be inspected concurrently per AMM) was not mentioned.
   - Related systems show inconsistent maintenance patterns.
   - Missing prerequisites or dependencies.

2. **Maintenance Pattern Analysis:** Identify odd maintenance patterns:
   - Components replaced out of sequence.
   - Missing required inspections before replacements.
   - Calendar vs. hour-based limits being ignored.

3. **System-Wide Forecast:** Based on all component statuses, generate a maintenance forecast:
   - Which components need immediate attention?
   - What is the next critical maintenance window?
   - Are there any cascading maintenance requirements?

OUTPUT FORMAT:
Generate a "System-Wide Anomaly Report" with:
- **Critical Anomalies:** [Any safety-critical issues found]
- **Maintenance Forecast:** [Next maintenance windows and priorities]
- **Recommendations:** [Specific actions to ensure compliance]

Be specific and cite AMM references when identifying anomalies."""
            
            # Run synthesis (skip regulation check - anomaly detection is maintenance-focused)
            synthesis_response, synthesis_sources = ask_assistant(
                synthesis_prompt,
                use_chat_mode=True,
                skip_regulation_check=True,  # Bypass regulation path
            )
            
            progress_bar.progress(1.0)
            status_text.text("✅ Forensic Audit Complete")
            
            # ===== PHASE 3: PEDAGOGICAL OUTPUT =====
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

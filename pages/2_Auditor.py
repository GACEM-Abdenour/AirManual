"""Compliance Auditor - Verify maintenance actions are compliant or overdue."""
import streamlit as st
import pandas as pd
from datetime import datetime, date
from src.engine import audit_log_compliance
from src.config import Config

st.set_page_config(
    page_title="Compliance Auditor",
    page_icon="✅",
    layout="wide",
)

st.title("✅ Compliance Auditor")
st.markdown(
    """
    Verify if maintenance actions are compliant or overdue based on inspection intervals
    found in the maintenance manuals.
    """
)

# Validate configuration
try:
    Config.validate()
except ValueError as e:
    st.error(f"Configuration error: {e}")
    st.info("Please check your .env file and ensure all API keys are set.")
    st.stop()

# Initialize session state for data editor
if "audit_data" not in st.session_state:
    st.session_state.audit_data = pd.DataFrame(
        columns=["Date Performed", "Aircraft Type", "Part Name", "Action Description"]
    )

# Instructions
with st.expander("ℹ️ How to Use", expanded=False):
    st.markdown("""
    1. **Add Rows**: Use the data editor below to add maintenance actions to audit
    2. **Columns**:
       - **Date Performed**: Date when maintenance was performed (YYYY-MM-DD format)
       - **Aircraft Type**: Aircraft type/model (e.g., "R44", "R22", "Robinson R44")
       - **Part Name**: Part or system name (e.g., "fuel pump", "engine", "rotor system")
       - **Action Description**: Brief description of what was done
    3. **Audit**: Click "Audit Compliance" to check each entry against manual requirements
    4. **Review**: Check the status (COMPLIANT/OVERDUE) and reasoning for each entry
    """)

# Data editor
st.subheader("📋 Maintenance Actions to Audit")
edited_df = st.data_editor(
    st.session_state.audit_data,
    num_rows="dynamic",
    column_config={
        "Date Performed": st.column_config.DateColumn(
            "Date Performed",
            format="YYYY-MM-DD",
            help="Date when maintenance was performed",
        ),
        "Aircraft Type": st.column_config.TextColumn(
            "Aircraft Type",
            help="Aircraft model/type (e.g., R44, R22)",
            required=True,
        ),
        "Part Name": st.column_config.TextColumn(
            "Part Name",
            help="Part or system name",
            required=True,
        ),
        "Action Description": st.column_config.TextColumn(
            "Action Description",
            help="What maintenance was performed",
        ),
    },
    hide_index=True,
    use_container_width=True,
)

# Update session state
st.session_state.audit_data = edited_df

# Audit button
if st.button("🔍 Audit Compliance", type="primary", use_container_width=True):
    if edited_df.empty:
        st.warning("Please add at least one entry before auditing.")
    else:
        # Validate required columns
        required_cols = ["Date Performed", "Aircraft Type", "Part Name"]
        missing_cols = [col for col in required_cols if col not in edited_df.columns]
        if missing_cols:
            st.error(f"Missing required columns: {', '.join(missing_cols)}")
        else:
            # Process each row
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Container for results
            results_container = st.container()
            
            compliant_count = 0
            overdue_count = 0
            
            for idx, row in edited_df.iterrows():
                date_performed = row.get("Date Performed", "")
                aircraft_type = str(row.get("Aircraft Type", "")).strip()
                part_name = str(row.get("Part Name", "")).strip()
                action_desc = str(row.get("Action Description", "")).strip()
                
                if not aircraft_type or not part_name:
                    continue
                
                # Format date
                if pd.isna(date_performed) or date_performed == "":
                    date_str = datetime.now().strftime("%Y-%m-%d")
                else:
                    if isinstance(date_performed, str):
                        date_str = date_performed
                    else:
                        date_str = date_performed.strftime("%Y-%m-%d") if hasattr(date_performed, 'strftime') else str(date_performed)
                
                # Update progress
                progress = (idx + 1) / len(edited_df)
                progress_bar.progress(progress)
                status_text.text(f"Auditing entry {idx + 1} of {len(edited_df)}: {aircraft_type} - {part_name}...")
                
                try:
                    status, reasoning = audit_log_compliance(date_str, part_name, aircraft_type)
                    
                    # Display result
                    with results_container:
                        st.markdown("---")
                        st.markdown(f"**Entry {idx + 1}:** {aircraft_type} - {part_name}")
                        st.caption(f"Date Performed: {date_str}")
                        if action_desc:
                            st.caption(f"Action: {action_desc}")
                        
                        if status == "COMPLIANT":
                            st.success(f"✅ **{status}**")
                            compliant_count += 1
                        elif status == "OVERDUE":
                            st.error(f"⚠️ **{status}**")
                            overdue_count += 1
                        else:
                            st.warning(f"❓ **{status}**")
                        
                        st.markdown(f"**Reasoning:**\n{reasoning}")
                        
                except Exception as e:
                    with results_container:
                        st.markdown("---")
                        st.error(f"❌ **ERROR** processing entry {idx + 1}: {e}")
            
            progress_bar.empty()
            status_text.empty()
            
            # Summary
            st.markdown("---")
            st.subheader("📊 Audit Summary")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Entries", len(edited_df))
            with col2:
                st.metric("✅ Compliant", compliant_count, delta=None)
            with col3:
                st.metric("⚠️ Overdue", overdue_count, delta=None)
            
            if overdue_count > 0:
                st.warning(f"⚠️ **{overdue_count} entry/entries require immediate attention!**")

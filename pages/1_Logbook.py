"""Logbook - Input your maintenance logbook entries and query/review them."""
import streamlit as st
import pandas as pd
from datetime import datetime
from src.engine import ask_assistant, review_logbook_entries
from src.config import Config

st.set_page_config(
    page_title="Logbook",
    page_icon="📝",
    layout="wide",
)

st.title("📝 Maintenance Logbook")
st.markdown(
    """
    Enter your maintenance logbook entries. You can then ask questions about them or request a compliance review.
    """
)

# Validate configuration
try:
    Config.validate()
except ValueError as e:
    st.error(f"Configuration error: {e}")
    st.info("Please check your .env file and ensure all API keys are set.")
    st.stop()

# Initialize session state
if "logbook_data" not in st.session_state:
    st.session_state.logbook_data = pd.DataFrame(
        columns=["Date", "Aircraft Type", "Part/System", "Action Description"]
    )
if "logbook_messages" not in st.session_state:
    st.session_state.logbook_messages = []

# Instructions
with st.expander("ℹ️ How to Use", expanded=False):
    st.markdown("""
    1. **Enter Logbook Entries**: Use the table below to add your maintenance entries
    2. **Columns**:
       - **Date**: Date of maintenance (YYYY-MM-DD format)
       - **Aircraft Type**: Aircraft model (e.g., "R44", "R22")
       - **Part/System**: Part name, system, or part number
       - **Action Description**: What maintenance was performed
    3. **Ask Questions**: Use the chat below to ask questions about your logbook entries
    4. **Review**: Click "Review Logbook" to check for compliance issues or missing information
    """)

# Data editor
st.subheader("📋 Your Logbook Entries")
edited_df = st.data_editor(
    st.session_state.logbook_data,
    num_rows="dynamic",
    column_config={
        "Date": st.column_config.DateColumn(
            "Date",
            format="YYYY-MM-DD",
            default=datetime.now().date(),
        ),
        "Aircraft Type": st.column_config.TextColumn(
            "Aircraft Type",
            help="Aircraft model (e.g., R44, R22)",
        ),
        "Part/System": st.column_config.TextColumn(
            "Part/System",
            help="Part name, system, or part number",
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
st.session_state.logbook_data = edited_df

# Review button
col1, col2 = st.columns([1, 4])
with col1:
    if st.button("🔍 Review Logbook", type="primary", use_container_width=True):
        if edited_df.empty:
            st.warning("Please add at least one entry before reviewing.")
        else:
            with st.spinner("Reviewing logbook entries..."):
                try:
                    review_result = review_logbook_entries(edited_df)
                    st.session_state.logbook_messages.append({
                        "role": "assistant",
                        "content": review_result,
                    })
                    st.rerun()
                except Exception as e:
                    st.error(f"Error reviewing logbook: {e}")

st.markdown("---")

# Chat interface for asking questions about the logbook
st.subheader("💬 Ask Questions About Your Logbook")

# Display chat history
for message in st.session_state.logbook_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("Ask a question about your logbook entries..."):
    # Add user message
    st.session_state.logbook_messages.append({"role": "user", "content": prompt})
    
    # Display user message
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Get assistant response
    with st.chat_message("assistant"):
        with st.spinner("Analyzing logbook and generating answer..."):
            try:
                # Create context from logbook
                logbook_context = ""
                if not edited_df.empty:
                    logbook_context = "\n\nUSER'S LOGBOOK ENTRIES:\n"
                    for idx, row in edited_df.iterrows():
                        date = row.get("Date", "")
                        aircraft = row.get("Aircraft Type", "")
                        part = row.get("Part/System", "")
                        action = row.get("Action Description", "")
                        
                        if pd.isna(date) or date == "":
                            date_str = "N/A"
                        else:
                            if isinstance(date, str):
                                date_str = date
                            else:
                                date_str = date.strftime("%Y-%m-%d") if hasattr(date, 'strftime') else str(date)
                        
                        logbook_context += f"- Date: {date_str}, Aircraft: {aircraft}, Part: {part}, Action: {action}\n"
                    
                    logbook_context += "\n\nCRITICAL INSTRUCTIONS FOR LOGBOOK CONTEXT:\n"
                    logbook_context += "- ONLY use information from the logbook entries listed above\n"
                    logbook_context += "- Do NOT invent or assume logbook entries that are not shown\n"
                    logbook_context += "- If the answer requires information NOT in the logbook entries above, clearly state: 'This information is not available in the provided logbook entries'\n"
                    logbook_context += "- When referencing logbook entries, use the exact dates and details shown above\n"
                    logbook_context += "- Combine logbook information with manual knowledge when answering, but clearly distinguish between what's in the logbook vs. what's in the manuals"
                
                # Ask with logbook context
                full_prompt = f"{prompt}\n\n{logbook_context}" if logbook_context else prompt
                response_text, source_nodes = ask_assistant(full_prompt)
                
                st.markdown(response_text)
                
                # Add assistant message
                st.session_state.logbook_messages.append({
                    "role": "assistant",
                    "content": response_text,
                })
                
            except Exception as e:
                error_message = f"Error: {str(e)}"
                st.error(error_message)
                st.session_state.logbook_messages.append({
                    "role": "assistant",
                    "content": error_message,
                })

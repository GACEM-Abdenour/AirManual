"""Streamlit app for Aircraft Maintenance Documentation Assistant."""
import streamlit as st
from src.engine import ask_assistant
from src.config import Config

# Page configuration
st.set_page_config(
    page_title="Aircraft Maintenance Assistant",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []


def main():
    """Main Streamlit app function."""
    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        st.error(f"Configuration error: {e}")
        st.info("Please check your .env file and ensure all API keys are set.")
        return
    
    # Title and description
    st.title("✈️ Aircraft Maintenance Documentation Assistant")
    st.markdown(
        """
        Ask questions about aircraft maintenance procedures, parts, regulations, and technical documentation.
        The assistant will provide detailed answers with source citations.
        """
    )
    
    # Sidebar with instructions
    with st.sidebar:
        st.header("ℹ️ How to Use")
        st.markdown(
            """
            **Ask questions about:**
            - Maintenance procedures
            - Part numbers (e.g., "What is part 12-45A?")
            - Regulations and compliance
            - Troubleshooting guides
            - Technical specifications
            
            **Features:**
            - ✅ Automatic source citations
            - ✅ Part number recognition
            - ✅ Cross-reference handling
            - ✅ Complete, detailed answers
            
            **Agentic mode** (when enabled): remembers context ("it" = last topic), decomposes complex questions, asks for clarification when vague.
            """
        )
        
        st.header("🔧 Setup")
        st.markdown(
            """
            Before using the assistant:
            1. Ensure your `.env` file has API keys configured
            2. Run `python src/ingest.py` to index your documents
            3. Start asking questions!
            """
        )
        st.header("⚙️ Options")
        use_deep_search = st.checkbox(
            "Use Agentic mode (context, decomposition, clarification)",
            value=False,
            help="When enabled: remembers conversation, breaks down complex questions, asks for clarification when vague. May take longer.",
        )
        st.caption(
            "If the app is slow with a large index (20k+ points), set **QDRANT_URL** in `.env` "
            "(e.g. `http://localhost:6333`) and run Qdrant in Docker for better performance."
        )
    
    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
            # Display sources if available
            if message["role"] == "assistant" and "sources" in message:
                with st.expander("View Sources", expanded=False):
                    if message["sources"]:
                        for i, source in enumerate(message["sources"], 1):
                            st.markdown(
                                f"**Source {i}:**\n"
                                f"- **File:** {source.get('file_name', 'Unknown')}\n"
                                f"- **Page:** {source.get('page_number', 'Unknown')}\n"
                                f"- **Type:** {source.get('element_type', 'Unknown')}"
                            )
                    else:
                        st.info("No sources available for this response.")
    
    # Chat input
    if prompt := st.chat_input("Ask a question about aircraft maintenance..."):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Get assistant response
        with st.chat_message("assistant"):
            with st.spinner("Searching documentation and generating answer..."):
                try:
                    response_text, source_nodes = ask_assistant(
                        prompt, use_chat_mode=use_deep_search
                    )
                    
                    # Display response
                    st.markdown(response_text)
                    
                    # Display sources in expander
                    with st.expander("View Sources", expanded=False):
                        if source_nodes:
                            for i, source in enumerate(source_nodes, 1):
                                st.markdown(
                                    f"**Source {i}:**\n"
                                    f"- **File:** {source.get('file_name', 'Unknown')}\n"
                                    f"- **Page:** {source.get('page_number', 'Unknown')}\n"
                                    f"- **Type:** {source.get('element_type', 'Unknown')}"
                                )
                                if source.get('score') is not None:
                                    st.caption(f"Relevance score: {source['score']:.4f}")
                        else:
                            st.info("No sources available for this response.")
                    
                    # Add assistant message to chat history
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response_text,
                        "sources": source_nodes,
                    })
                    
                except Exception as e:
                    error_message = f"Error: {str(e)}"
                    st.error(error_message)
                    st.info("Please ensure the index has been created. Run 'python src/ingest.py' first.")
                    
                    # Add error message to chat history
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": error_message,
                        "sources": [],
                    })


if __name__ == "__main__":
    main()

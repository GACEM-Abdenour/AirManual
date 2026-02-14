"""Streamlit app for Aircraft Maintenance Documentation Assistant."""
import streamlit as st
from llama_index.core.callbacks import CallbackManager
from llama_index.core.settings import Settings

from src.config import Config
from src.engine import ask_assistant
from src.usage_tracker import OpenAITokenCountingHandler, get_usage, reset_usage

# Page configuration
st.set_page_config(
    page_title="Aircraft Maintenance Assistant",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS: high-contrast, readable text; appealing but calm colors
st.markdown(
    """
    <style>
    /* Contrast-safe palette: dark text on light backgrounds */
    :root {
        --text: #1e293b;
        --text-secondary: #475569;
        --accent: #0d7377;
        --accent-bg: #f0fdfa;
        --surface: #f8fafc;
        --border: #e2e8f0;
    }
    /* Chat blocks: clear text, comfortable line length */
    [data-testid="stChatMessage"] {
        background: var(--surface) !important;
        border-radius: 8px;
        border-left: 4px solid var(--accent) !important;
        padding: 1rem 1.25rem !important;
        margin: 0.75rem 0 !important;
        box-shadow: none !important;
    }
    [data-testid="stChatMessage"] .stMarkdown {
        color: var(--text) !important;
        font-size: 1rem !important;
        line-height: 1.6 !important;
        letter-spacing: 0.01em;
    }
    [data-testid="stChatMessage"] [data-testid="stChatMessageAvatar"] {
        display: none;
    }
    /* Main area: readable width and spacing */
    .main .block-container { padding-top: 1.5rem; max-width: 52rem; }
    h1 { color: var(--text) !important; font-weight: 600 !important; letter-spacing: -0.02em; }
    .stCaption { color: var(--text-secondary) !important; font-size: 0.9375rem !important; }
    /* Sidebar: clear labels and notices */
    [data-testid="stSidebar"] .stMarkdown { color: var(--text) !important; }
    [data-testid="stSidebar"] .stAlert {
        border-radius: 8px;
        border-left: 4px solid var(--accent);
        background: var(--accent-bg) !important;
    }
    /* Expanders and sources: legible meta text */
    [data-testid="stExpander"] .stMarkdown { color: var(--text) !important; line-height: 1.55 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "usage" not in st.session_state:
    st.session_state.usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
        "estimated_cost_usd": 0.0,
    }


def main():
    """Main Streamlit app function."""
    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        st.error(f"Configuration error: {e}")
        st.info("Please check your .env file and ensure all API keys are set.")
        return

    # Wire OpenAI token/cost tracking once (so engine LLMs use it)
    if "callback_manager_set" not in st.session_state:
        Settings.callback_manager = CallbackManager(handlers=[OpenAITokenCountingHandler()])
        st.session_state.callback_manager_set = True

    # Title and short description
    st.title("Aircraft Maintenance Documentation")
    st.caption("Procedures, parts, regulations, and technical documentation — with source citations.")

    # Sidebar: how to use, options, and notices
    with st.sidebar:
        st.header("How to use")
        st.markdown(
            "Ask about maintenance procedures, part numbers, regulations, or technical specs. "
            "Answers include **source citations** so you can check the manuals."
        )
        st.divider()
        st.header("Options")
        use_deep_search = st.checkbox(
            "Use Agentic mode",
            value=False,
            help="Remembers context, breaks down complex questions, may ask for clarification.",
        )
        if use_deep_search:
            st.caption("Futuristic idea — we’re testing smarter, context-aware answers. Preview only.")

        st.divider()
        st.header("OpenAI usage")
        u = get_usage()
        st.session_state.usage = u
        st.metric("Estimated cost (total)", f"${u['estimated_cost_usd']:.4f}")
        st.caption(f"Requests: {u['request_count']} · Tokens: {u['total_tokens']:,} (in: {u['prompt_tokens']:,}, out: {u['completion_tokens']:,})")
        st.caption("Saved to file — persists across restarts (local & Render).")
        if st.button("Reset usage", help="Reset saved total to zero (file will be overwritten)"):
            reset_usage()
            st.session_state.usage = get_usage()
            st.rerun()

        st.divider()
        st.header("Notices")
        st.info(
            "**Logbook** (see page in sidebar) is **preview only** — not fully working. "
            "Use it to try the interface; do not rely on it for real compliance or record-keeping."
        )
        st.caption("Agentic mode above is also a preview / futuristic feature.")

    # Display conversation: flat, document-style
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
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

    # Input
    if prompt := st.chat_input("Ask a question about aircraft maintenance..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Searching documentation and generating answer..."):
                try:
                    response_text, source_nodes = ask_assistant(
                        prompt, use_chat_mode=use_deep_search
                    )
                    st.session_state.usage = get_usage()
                    st.markdown(response_text)
                    with st.expander("View Sources", expanded=False):
                        if source_nodes:
                            for i, source in enumerate(source_nodes, 1):
                                st.markdown(
                                    f"**Source {i}:**\n"
                                    f"- **File:** {source.get('file_name', 'Unknown')}\n"
                                    f"- **Page:** {source.get('page_number', 'Unknown')}\n"
                                    f"- **Type:** {source.get('element_type', 'Unknown')}"
                                )
                                if source.get("score") is not None:
                                    st.caption(f"Relevance score: {source['score']:.4f}")
                        else:
                            st.info("No sources available for this response.")
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response_text,
                        "sources": source_nodes,
                    })
                except Exception as e:
                    error_message = f"Error: {str(e)}"
                    st.error(error_message)
                    st.info("Please ensure the index has been created. Run 'python src/ingest.py' first.")
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": error_message,
                        "sources": [],
                    })


if __name__ == "__main__":
    main()

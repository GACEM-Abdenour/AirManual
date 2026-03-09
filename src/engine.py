"""Query engine for the Aircraft Maintenance Assistant."""
import asyncio
import threading
import time
from typing import List, Dict, Any, Tuple, Optional
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.chat_engine import ContextChatEngine
from llama_index.core.response import Response
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.core.retrievers import BaseRetriever
from llama_index.llms.openai import OpenAI
from llama_index.core.prompts import PromptTemplate, ChatPromptTemplate
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.settings import Settings
from src.config import Config
from src.index_store import get_index, get_retriever

# For regulation questions: only use chunks with at least this similarity (0–1).
REGULATION_SIMILARITY_THRESHOLD = 0.7
REGULATION_KNOWLEDGE_FALLBACK = (
    "I don't have enough knowledge to reply to this, maybe try to decompose your question."
)

# Deep Research: trigger when top retrieval score is below this (0–1).
DEEP_RESEARCH_CONFIDENCE_THRESHOLD = 0.70

# System prompt used when synthesizing from expanded retrieval (low-confidence path).
DEEP_RESEARCH_SYSTEM_PROMPT = """You are in Deep Research Mode. The direct answer was not found in the first pass.
Use the provided chunks to infer a helpful answer. Connect disparate data points (e.g., use Fuel Capacity + Burn Rate to calculate Flight Time).
Explain your reasoning step-by-step.
Structure your response as follows:

**Direct Answer:** (Best effort based on inference from the chunks.)

**Reasoning:** "I calculated this based on..." or "I inferred this because the manual states..."

**Related Data:** "While the exact X wasn't found, here is Y and Z which are relevant." Cite sources (e.g., IAW AMM 24-30-00).
Always cite your sources. Do not make up values not present in the chunks."""

# System prompt for the Expert Aviation Technician (used by query engine and regulation path)
SYSTEM_PROMPT = """You are an Expert Aviation Maintenance Technician with comprehensive knowledge of aircraft maintenance procedures, technical manuals, Illustrated Parts Catalogs (IPC), regulations, and all aviation documentation.

Your role is to provide accurate, detailed, and complete answers about aircraft maintenance based solely on the documentation provided to you.

CRITICAL RULES:
1. **Always cite sources**: Every answer MUST include the document name and page number where the information comes from. Format citations as: [Document Name, Page X]

2. **Part Number handling**: 
   - When asked about a part number (e.g., "Part 12-45A", "PN 123-456", "A23-554"), you MUST search explicitly for that exact part number in the documentation
   - Always include the part number in your response when discussing parts
   - If a part number is mentioned, provide its description, location, and any relevant specifications

3. **Completeness**: 
   - Provide complete, thorough answers using ALL relevant information from the documentation
   - Never give vague or partial answers when more detail is available
   - If information spans multiple documents or pages, cite all sources

4. **Cross-references (CRITICAL)**: 
   - ALWAYS follow cross-references (e.g., "See Section 5", "Refer to Table 2-1", "See IPC for part numbers")
   - If the retrieved context mentions a reference (section number, table number, another document, etc.) that is not fully present in the current snippet, you MUST use your retrieval tools to search for that specific section/reference
   - Combine information from the original query context AND any cross-referenced sections to provide a unified, complete answer
   - Example: If context says "See Section 5.2 for torque values", search for "Section 5.2" and include those torque values in your answer

5. **Accuracy**: 
   - Only answer based on the provided documentation
   - If information is not available in the documentation, clearly state: "This information is not available in the provided documentation"
   - Never hallucinate or make up information

6. **Stay on topic**: 
   - Only answer questions related to aircraft maintenance, aviation regulations, technical procedures, and parts
   - Politely redirect off-topic questions back to aviation maintenance topics

7. **Technical precision**: 
   - Use exact terminology from the documentation
   - Include specific values, measurements, and specifications when available
   - Reference exact procedure numbers, section numbers, and regulation numbers when mentioned

Remember: You are the expert technician who has memorized every manual and regulation. Provide answers as if you have that level of knowledge, but always cite your sources. When you see cross-references, actively search for them to provide complete answers."""

# System prompt for the Agentic Technician (decomposition, context, clarification)
AGENT_SYSTEM_PROMPT = """
You are AeroMind, a Senior Lead Aircraft Maintenance Engineer.
Your role is to assist mechanics by finding accurate information in the Aircraft Maintenance Manuals (AMM) and Parts Catalogs (IPC).
YOUR BEHAVIORAL PROTOCOLS:
Safety First (The "Fatal" Rule):

If the manual contains a WARNING (risk of death/injury) or CAUTION (risk of damage), you must state this first in your response, in BOLD RED.

Example: "⚠️ WARNING: ENSURE HYDRAULIC POWER IS OFF BEFORE PROCEEDING."

Hold the Handbook (Data Completeness):

CRITICAL: When providing a Procedure, use ALL steps from the manual. DO NOT SUMMARIZE. Missing a step is a safety violation.

Part Number Precision:

Always cite Part Numbers (P/N) when available.

Format: Fuel Pump (P/N 65-1234).

Clarify & Verify:

If the question is vague, ask: "Which system? Left or Right?" before answering.

Citation:

ALWAYS cite your source (e.g., "IAW AMM 24-30-00").

Partial Data & Inference (The "Helpful Engineer" Rule):
* **NEVER** say "The information is not provided" if you have related data in the context chunks.
* **Scenario A (Related Data):** If the user asks for "Flight Time" and you only find "Fuel Capacity" and "Burn Rate", **REPORT** those values and explain they determine flight time.
* **Scenario B (Contextual Mention):** If you find a mention like *"Perform endurance test for 3 hours"*, **REPORT** it: *"The manual mentions an endurance test of 3 hours (Ref: [Source]), which suggests a capability of at least this duration."*
* **Goal:** Provide the *closest available data* rather than a blank refusal.

VISUAL & FORMATTING STANDARDS (CRITICAL):
You must structure your response using Markdown Headers with Icons and Bullet Points. Do not output walls of text.

Use this structure:

1. For Specific Data (Torques, Limits, Part Numbers):

Use the format:

📉 Specifications
Item Name: [Value]

Limit: [Value]

Source: [Citation]

2. For Procedures:

Use the format:

🛠️ Maintenance Procedure ([AMM Reference])
1. [Step 1 Details]

2. [Step 2 Details]...

3. For General Explanations:

Break it down into:

📋 Context
[Brief explanation]

### 🔍 Key Factors
* **Factor 1:** [Explanation]
* **Factor 2:** [Explanation]
4. Text Emphasis:

Always BOLD important values (e.g., 150 in-lbs, Shell Grease 22, P/N 123-456). """


# Persona prompt for game API: small-talk only (no RAG). Used when user says hi/hello/etc.
GAME_API_SMALL_TALK_PROMPT = """You are a welcoming, slightly silly, but highly skilled aviation mechanic AI assistant (a copilot for aircraft maintenance).

The user has just sent a greeting or small talk (e.g. "hi", "hello", "how are you", "hey").

Your rules:
1. Do NOT search or cite technical manuals for this. Do NOT make up helicopter parts or procedures.
2. Acknowledge the greeting in a friendly, playful way (one short sentence).
3. Seamlessly pivot the conversation back to aircraft maintenance—invite them to ask about the helicopter, a part, or a procedure.
4. Keep the whole reply to 1–3 sentences. Do not output "GAME_CMD:" or any JSON. Do not output "Sources:" or citations.

Example tone: "Hey there! My circuits are running on all cylinders today. Speaking of cylinders, do we need to tear down an engine today, or are you just dropping by to say hi?"

User message: {{user_message}}

Reply (conversational only, no citations, no GAME_CMD):"""


def reply_to_small_talk(user_message: str) -> str:
    """Reply to greetings/small talk without RAG. Zero manual lookup, zero hallucination."""
    llm = OpenAI(
        model="gpt-4o",
        api_key=Config.OPENAI_API_KEY,
        temperature=0.3,
    )
    prompt = GAME_API_SMALL_TALK_PROMPT.replace("{{user_message}}", user_message.strip())
    response = llm.complete(prompt)
    text = str(response).strip() if hasattr(response, "__str__") else (getattr(response, "text", "") or "")
    return text.strip()


def _is_factual_lookup_question(question: str) -> bool:
    """Classification heuristic for the Deterministic Fallback Layer.

    Detects factual/technical queries (torque, limits, fuel, procedures, etc.) where
    we cannot tolerate false negatives: the mechanic must get official manual data
    and citations. Used to trigger high-priority retrieval when the Agent has not
    invoked the RAG tool (see ask_assistant fallback).
    """
    if not question or len(question.strip()) < 5:
        return False
    q = question.lower().strip()
    triggers = [
        "how much", "how long", "how many", "what is the", "what are the",
        "fuel", "endurance", "flight time", "range", "capacity",
        "torque", "inspection", "interval", "procedure", "removal", "install",
        "r44", "r22", "robinson", "weight", "limit", "specification",
    ]
    return any(t in q for t in triggers)


def detect_part_number(question: str) -> Optional[str]:
    """Detect if the question contains a part number.
    
    Args:
        question: The question text
        
    Returns:
        Part number string if detected, None otherwise
    """
    import re
    
    # Common part number patterns
    patterns = [
        r'\b(?:Part|PN|P/N|Part Number|Part No\.?)\s*[:\-]?\s*([A-Z0-9\-]+)',  # "Part 12-45A", "PN: 123-456"
        r'\b([A-Z]{1,3}[\-\s]?\d{2,4}[\-\s]?[A-Z]?)\b',  # "12-45A", "123-456"
        r'\b\d{2,4}[\-\s]\d{2,4}[\-\s]?[A-Z]?\b',  # "12-45", "123-456-A"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, question, re.IGNORECASE)
        if match:
            return match.group(1) if match.groups() else match.group(0)
    
    return None


def detect_regulation_question(question: str) -> bool:
    """Detect if the question is about regulations (CARs, standards, legal, regulatory compliance).
    
    When True, we enforce a higher similarity threshold and fallback if no high-scoring chunks exist.
    Note: "compliance" alone (e.g., "compliance status") is NOT a regulation question - it's maintenance compliance.
    """
    import re
    q = (question or "").lower().strip()
    patterns = [
        r"\bregulation(s)?\b",
        r"\bcar(s)?\b",  # Canadian Aviation Regulations
        r"\bstandard(s)?\s+\d",  # e.g. "Standard 624"
        r"\badvisory\b",
        r"\btransport\s+canada\b",
        r"\blegal\b",
        r"\bregulatory\s+compliance\b",  # More specific - not just "compliance"
        r"\bcompliance\s+with\s+regulation(s)?\b",
        r"\bsor[-/]?\d",  # SOR/96-433
        r"\bsubpart\s+\d",
        r"\bact(s)?\b.*aviation",
        r"aviation.*\bact(s)?\b",
    ]
    return any(re.search(p, q) for p in patterns)


class _FixedNodesRetriever(BaseRetriever):
    """Retriever that always returns a fixed list of nodes (used for regulation path)."""

    def __init__(self, nodes: List[NodeWithScore]) -> None:
        super().__init__()
        self._nodes = nodes

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        return self._nodes


def create_agent(
    similarity_top_k: int = 20,
    temperature: float = 0.3,
    extra_system_prompt: Optional[str] = None,
    memory: Optional[ChatMemoryBuffer] = None,
):
    """Create an OpenAIAgent (FunctionAgent) with QueryEngineTool for decomposition and context.

    The agent can:
    - Remember conversation context (ChatMemoryBuffer)
    - Decompose complex questions into multiple searches
    - Ask for clarification when vague
    - Call the search tool multiple times in a loop

    Args:
        similarity_top_k: Number of chunks to retrieve.
        temperature: LLM temperature.
        extra_system_prompt: Optional text (e.g. game rulebook) appended to the agent system prompt.
        memory: Optional ChatMemoryBuffer for session-scoped history; if None, uses a new default buffer.

    Returns:
        FunctionAgent instance
    """
    if not Config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required for the agent")
    
    from llama_index.core.agent.workflow import FunctionAgent
    from llama_index.core.tools import QueryEngineTool
    
    _cb = getattr(Settings, "callback_manager", None)
    llm = OpenAI(
        model="gpt-4o",
        api_key=Config.OPENAI_API_KEY,
        temperature=temperature,
        timeout=120.0,
        callback_manager=_cb,
    )
    
    index = get_index()
    query_engine = index.as_query_engine(
        similarity_top_k=similarity_top_k,
        llm=llm,
    )
    # Update query engine with system prompt
    qa_prompt = PromptTemplate(
        f"{SYSTEM_PROMPT}\n\n"
        "Context information from the documentation is below.\n"
        "---------------------\n"
        "{{context_str}}\n"
        "---------------------\n"
        "Given the context information and not prior knowledge, "
        "answer the question: {{query_str}}\n"
    )
    query_engine.update_prompts(
        {"response_synthesizer:text_qa_template": qa_prompt}
    )
    
    aviation_tool = QueryEngineTool.from_defaults(
        query_engine=query_engine,
        name="aviation_manuals_tool",
        description=(
            "Use this tool to look up technical information from the Aircraft Maintenance Manuals (AMM), "
            "POH, or Parts Catalogs. Use it for: fuel capacity, endurance/flight time, part numbers, "
            "torque values, removal/installation procedures, inspection intervals, limits, weights, or compliance. "
            "Call it immediately for clear factual questions (e.g. 'how much time can I fly with the R44?'). "
            "Do NOT use for greetings or small talk; do NOT use for vague questions that need clarification first."
        ),
    )
    
    system_prompt = AGENT_SYSTEM_PROMPT
    if extra_system_prompt and extra_system_prompt.strip():
        system_prompt = f"{system_prompt}\n\n{extra_system_prompt.strip()}"

    if memory is None:
        memory = ChatMemoryBuffer.from_defaults(token_limit=8000)

    agent = FunctionAgent(
        tools=[aviation_tool],
        llm=llm,
        system_prompt=system_prompt,
        memory=memory,
    )
    return agent


def create_chat_engine(
    similarity_top_k: int = 20,
    temperature: float = 0.1,  # Low temperature for factual accuracy
) -> ContextChatEngine:
    """Create a ChatEngine with context mode (legacy fallback).
    
    For agentic behavior (decomposition, clarification), use create_agent instead.
    """
    # Validate configuration
    if not Config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required for the query engine")
    
    llm = OpenAI(
        model="gpt-4o",
        api_key=Config.OPENAI_API_KEY,
        temperature=temperature,
        timeout=120.0,
    )
    
    index = get_index()
    chat_engine = index.as_chat_engine(
        chat_mode="context",
        llm=llm,
        similarity_top_k=similarity_top_k,
        memory=ChatMemoryBuffer.from_defaults(token_limit=3000),
        system_prompt=SYSTEM_PROMPT,
    )
    
    return chat_engine


def create_query_engine(
    similarity_top_k: int = 20,
    temperature: float = 0.1,  # Low temperature for factual accuracy
) -> RetrieverQueryEngine:
    """Create a QueryEngine with the configured LLM and retriever.
    
    This is a fallback for non-conversational queries.
    
    Args:
        similarity_top_k: Number of top results to retrieve
        temperature: LLM temperature (lower = more factual, higher = more creative)
        
    Returns:
        RetrieverQueryEngine instance
    """
    # Validate configuration
    if not Config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required for the query engine")
    
    # Initialize LLM (use global callback manager for token/cost tracking if set)
    _cb = getattr(Settings, "callback_manager", None)
    llm = OpenAI(
        model="gpt-4o",
        api_key=Config.OPENAI_API_KEY,
        temperature=temperature,
        callback_manager=_cb,
    )
    
    # Get the index
    index = get_index()
    
    # Get retriever with hybrid search
    retriever = get_retriever(similarity_top_k=similarity_top_k)
    
    # Create query engine with system prompt
    query_engine = RetrieverQueryEngine.from_args(
        retriever=retriever,
        llm=llm,
        response_mode="compact",  # Compact mode for focused answers
    )
    
    # Set custom prompt template that includes system prompt
    qa_prompt_template = PromptTemplate(
        f"{SYSTEM_PROMPT}\n\n"
        "Context information from the documentation is below.\n"
        "---------------------\n"
        "{{context_str}}\n"
        "---------------------\n"
        "Given the context information and not prior knowledge, "
        "answer the question: {{query_str}}\n"
    )
    
    # Update the query engine's prompt
    query_engine.update_prompts(
        {"response_synthesizer:text_qa_template": qa_prompt_template}
    )
    
    return query_engine


# Agent cache: key (session_id, extra_system_prompt) -> agent. Enables session-scoped memory and game-API system prompt.
_agent_cache: Dict[Tuple[Optional[str], Optional[str]], Any] = {}
_agent_cache_lock = threading.Lock()

# Session-scoped memories for API (session_id -> ChatMemoryBuffer). Streamlit uses default agent with no session_id.
_session_memories: Dict[str, ChatMemoryBuffer] = {}
_session_memories_lock = threading.Lock()

# Global chat engine instance (legacy context mode)
_chat_engine: Optional[ContextChatEngine] = None

# Global query engine instance (fallback)
_query_engine: Optional[RetrieverQueryEngine] = None


def get_agent(
    similarity_top_k: int = 20,
    force_reload: bool = False,
    extra_system_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """Get or create a FunctionAgent (agentic technician), optionally with extra system prompt and session-scoped memory."""
    cache_key = (session_id or "default", (extra_system_prompt or "").strip() or "default")
    with _agent_cache_lock:
        if force_reload and cache_key in _agent_cache:
            del _agent_cache[cache_key]
        if cache_key in _agent_cache:
            return _agent_cache[cache_key]

        memory: Optional[ChatMemoryBuffer] = None
        if session_id and session_id.strip():
            with _session_memories_lock:
                if session_id not in _session_memories:
                    _session_memories[session_id] = ChatMemoryBuffer.from_defaults(token_limit=8000)
                memory = _session_memories[session_id]

        agent = create_agent(
            similarity_top_k=similarity_top_k,
            extra_system_prompt=extra_system_prompt or None,
            memory=memory,
        )
        _agent_cache[cache_key] = agent
    return agent


def get_chat_engine(
    similarity_top_k: int = 20,
    force_reload: bool = False,
):
    """Get or create the agent (agentic mode). Alias for get_agent for backward compatibility."""
    return get_agent(similarity_top_k=similarity_top_k, force_reload=force_reload)


def get_query_engine(
    similarity_top_k: int = 20,
    force_reload: bool = False,
) -> RetrieverQueryEngine:
    """Get or create the global query engine instance.
    
    Args:
        similarity_top_k: Number of top results to retrieve
        force_reload: If True, recreate the query engine
        
    Returns:
        RetrieverQueryEngine instance
    """
    global _query_engine
    
    if _query_engine is None or force_reload:
        _query_engine = create_query_engine(similarity_top_k=similarity_top_k)
    
    return _query_engine


def extract_source_info(node: NodeWithScore) -> Dict[str, Any]:
    """Extract source information from a node.
    
    Args:
        node: NodeWithScore object
        
    Returns:
        Dictionary with source information (file_name, page_number, etc.)
    """
    metadata = node.node.metadata if hasattr(node.node, 'metadata') else {}
    
    return {
        "file_name": metadata.get("file_name", "Unknown"),
        "page_number": metadata.get("page_number", "Unknown"),
        "element_type": metadata.get("element_type", "Unknown"),
        "score": node.score if hasattr(node, 'score') else None,
    }


def _get_node_id(n: NodeWithScore) -> str:
    """Stable id for deduping (node_id or hash of content)."""
    if hasattr(n, "node") and n.node is not None:
        if hasattr(n.node, "node_id") and n.node.node_id:
            return str(n.node.node_id)
        if hasattr(n.node, "get_content"):
            return str(hash(n.node.get_content()[:500]))
    return str(id(n))


def _generate_query_variations(question: str, llm: Any) -> List[str]:
    """Use LLM to generate 3 alternative phrasings for wider retrieval."""
    prompt = (
        "Generate exactly 3 alternative phrasings of this question for searching "
        "aviation maintenance manuals. Use synonyms, technical terms (e.g. AMM, POH, endurance, fuel capacity), "
        "or broader scope. Output one question per line, no numbering. Question:\n\n"
        f"{question}"
    )
    try:
        resp = llm.complete(prompt)
        text = str(resp).strip() if hasattr(resp, "__str__") else (getattr(resp, "text", "") or "")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:3]
        return lines if lines else [question]
    except Exception:
        return [question]


def _run_deep_research(question: str, similarity_top_k: int) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Deep Research Mode: expand retrieval (1.5x top_k, cap 30) and run 2 query variations,
    then synthesize with a pedagogical prompt (Direct Answer, Reasoning, Related Data).
    Context is capped at 40k chars (~10k tokens) to avoid TPM/context-window limits.
    """
    if not Config.OPENAI_API_KEY:
        return (
            "Deep research is unavailable (no API key). Please rephrase your question.",
            [],
        )
    _cb = getattr(Settings, "callback_manager", None)
    llm = OpenAI(
        model="gpt-4o",
        api_key=Config.OPENAI_API_KEY,
        temperature=0.3,
        timeout=120.0,
        callback_manager=_cb,
    )
    expanded_k = min(int(1.5 * similarity_top_k), 30)
    retriever_double = get_retriever(similarity_top_k=expanded_k)
    retriever_single = get_retriever(similarity_top_k=similarity_top_k)
    # Original question with expanded scope (capped at 30 chunks)
    nodes_original = retriever_double.retrieve(question)
    seen_ids: set = set()
    all_nodes: List[NodeWithScore] = []
    for n in nodes_original:
        nid = _get_node_id(n)
        if nid not in seen_ids:
            seen_ids.add(nid)
            all_nodes.append(n)
    # 2 query variations (reduced from 3 to lower context + burst load)
    variations = _generate_query_variations(question, llm)[:2]
    for var in variations:
        for n in retriever_single.retrieve(var):
            nid = _get_node_id(n)
            if nid not in seen_ids:
                seen_ids.add(nid)
                all_nodes.append(n)
    if not all_nodes:
        return (
            "No additional documentation could be found. Try rephrasing or specifying the manual/section.",
            [],
        )
    
    # Truncate context to stay under context window + TPM (approx 10k tokens)
    MAX_CHARS = 40000
    context_parts = []
    current_len = 0
    for n in all_nodes:
        text = n.get_content() if hasattr(n, "get_content") else (
            n.node.get_content() if hasattr(n, "node") and n.node else str(n)
        )
        if current_len + len(text) > MAX_CHARS:
            break
        context_parts.append(text)
        current_len += len(text)
    context_str = "\n\n---\n\n".join(context_parts)
    if len(all_nodes) > len(context_parts):
        context_str = f"(Context truncated: {len(context_parts)} of {len(all_nodes)} nodes)\n\n" + context_str
    
    synthesis_prompt = (
        f"{DEEP_RESEARCH_SYSTEM_PROMPT}\n\n"
        "Context from the documentation:\n"
        "---------------------\n"
        f"{context_str}\n"
        "---------------------\n"
        f"User question: {question}\n\n"
        "Provide your structured response (Direct Answer, Reasoning, Related Data) below."
    )
    try:
        response = llm.complete(synthesis_prompt)
        response_text = str(response).strip() if hasattr(response, "__str__") else (getattr(response, "text", "") or "")
    except Exception as e:
        response_text = f"Deep research synthesis failed: {e}. Here are the raw source excerpts for manual review."
    source_nodes = [extract_source_info(n) for n in all_nodes]
    return response_text, source_nodes


def ask_assistant(
    question: str,
    similarity_top_k: int = 20,
    use_chat_mode: bool = True,  # Use chat mode for agentic cross-reference following
    skip_regulation_check: bool = False,  # Skip regulation path for logbook/maintenance queries
    extra_system_prompt: Optional[str] = None,  # e.g. game rulebook; injected into agent system prompt
    raw_question: Optional[str] = None,  # Unpadded user text for regulation/factual classification
    session_id: Optional[str] = None,  # For API: session-scoped chat memory
) -> Tuple[str, List[Dict[str, Any]]]:
    """Ask a question to the aircraft maintenance assistant.

    Uses ContextChatEngine with chat_mode="context" to enable agentic behavior:
    - LLM can use retrieval tools to follow cross-references
    - Maintains conversation context
    - Can search for specific sections when mentioned

    Args:
        question: The question to ask (keep concise; use extra_system_prompt for instructions).
        similarity_top_k: Number of top results to retrieve (increased for part number queries).
        use_chat_mode: If True, use ContextChatEngine for agentic behavior.
        skip_regulation_check: If True, skip regulation-specific retrieval path.
        extra_system_prompt: Appended to agent system prompt (e.g. game API rulebook).
        raw_question: If set, used for regulation detection and factual fallback (avoids prompt dilution).
        session_id: If set, use session-scoped chat memory (API multi-user).

    Returns:
        Tuple of (response_text, source_nodes).
    """
    # For classification use raw user question so padding (e.g. rulebook in question) doesn't break triggers
    classification_question = (raw_question or question).strip() if (raw_question or question) else ""

    # Regulation questions: enforce 70% similarity threshold; fallback if no high-scoring chunks
    # Skip this check for logbook/maintenance queries (they use "compliance" but aren't about regulations)
    if not skip_regulation_check and classification_question and detect_regulation_question(classification_question):
        index = get_index()
        base_retriever = index.as_retriever(similarity_top_k=15)
        nodes = base_retriever.retrieve(classification_question)
        high_nodes = [
            n for n in nodes
            if getattr(n, "score", None) is not None and n.score >= REGULATION_SIMILARITY_THRESHOLD
        ]
        if not high_nodes:
            return REGULATION_KNOWLEDGE_FALLBACK, []
        fixed_retriever = _FixedNodesRetriever(high_nodes)
        _cb = getattr(Settings, "callback_manager", None)
        llm = OpenAI(model="gpt-4o", api_key=Config.OPENAI_API_KEY, temperature=0.1, callback_manager=_cb)
        qa_prompt = PromptTemplate(
            f"{SYSTEM_PROMPT}\n\n"
            "Context information from the documentation is below.\n"
            "---------------------\n"
            "{{context_str}}\n"
            "---------------------\n"
            "Given the context information and not prior knowledge, "
            "answer the question: {{query_str}}\n"
        )
        reg_engine = RetrieverQueryEngine.from_args(
            retriever=fixed_retriever,
            llm=llm,
            response_mode="compact",
        )
        reg_engine.update_prompts({"response_synthesizer:text_qa_template": qa_prompt})
        response = reg_engine.query(question)
        source_nodes = [extract_source_info(n) for n in (response.source_nodes or [])]
        return str(response), source_nodes

    # Detect if this is a part number query (use full question for retrieval context)
    part_number = detect_part_number(question)
    if part_number:
        # Increase retrieval for part number queries to ensure we find exact matches
        # Hybrid search (BM25) will prioritize exact part number matches
        similarity_top_k = max(similarity_top_k, 15)
        print(f"Detected part number query: {part_number}")

    # Use agent for agentic behavior (decomposition, context, clarification)
    if use_chat_mode:
        agent = get_agent(
            similarity_top_k=similarity_top_k,
            extra_system_prompt=extra_system_prompt,
            session_id=session_id,
        )
        
        async def _run_agent():
            from llama_index.core.agent.workflow import ToolCallResult
            from llama_index.core.workflow import Context
            
            ctx = Context(agent)
            handler = agent.run(question, ctx=ctx)
            tool_outputs = []
            async for ev in handler.stream_events():
                if isinstance(ev, ToolCallResult):
                    tool_outputs.append(ev.tool_output)
            result = await handler
            return result, tool_outputs
        
        result, tool_outputs = asyncio.run(_run_agent())
        
        # Extract response text from AgentOutput
        response_text = str(result.response.content or "")
        if not response_text and hasattr(result, "response"):
            from llama_index.core.llms import ChatMessage
            msg = result.response
            if hasattr(msg, "content") and msg.content:
                response_text = msg.content
        
        # Extract source nodes from tool outputs (QueryEngineTool returns Response)
        source_nodes: List[Dict[str, Any]] = []
        for tool_out in tool_outputs:
            raw = getattr(tool_out, "raw_output", None)
            if raw is not None and hasattr(raw, "source_nodes") and raw.source_nodes:
                for node in raw.source_nodes:
                    if hasattr(node, "node") and hasattr(node, "score"):
                        source_nodes.append(extract_source_info(node))

        # Deterministic Fallback Layer (safety-critical): The Agent uses probabilistic
        # reasoning to decide when to use tools; we cannot tolerate false negatives
        # (missing a manual lookup). If the Agent did not invoke the RAG tool for a
        # factual query, trigger high-priority retrieval and override with cited data.
        # Use raw_question for classification so padded API prompts don't break triggers.
        if not source_nodes and _is_factual_lookup_question(classification_question):
            query_engine = get_query_engine(similarity_top_k=similarity_top_k)
            response: Response = query_engine.query(question)
            response_text = str(response)
            if hasattr(response, "source_nodes") and response.source_nodes:
                source_nodes = [extract_source_info(node) for node in response.source_nodes]
    else:
        # Fallback to query engine
        query_engine = get_query_engine(similarity_top_k=similarity_top_k)
        response: Response = query_engine.query(question)
        response_text = str(response)
        
        # Extract source nodes
        source_nodes: List[Dict[str, Any]] = []
        if hasattr(response, 'source_nodes') and response.source_nodes:
            for node in response.source_nodes:
                source_info = extract_source_info(node)
                source_nodes.append(source_info)

    # Deep Research: if top retrieval score is low, expand search and reformulate queries.
    scores = [s.get("score") for s in source_nodes if s.get("score") is not None]
    top_score = max(scores, default=1.0)
    if scores and top_score < DEEP_RESEARCH_CONFIDENCE_THRESHOLD:
        response_text, source_nodes = _run_deep_research(question, similarity_top_k)

    return response_text, source_nodes


# Logbook Forensic Audit: Map/Reduce constants (match LOGBOOK_FORENSIC_AUDIT_TECHNICAL_FLOW.md)
MAX_CHARS_PER_REPORT = 2500
MAX_TOTAL_CONTEXT_CHARS = 18000


def _truncate_report(s: str, max_len: int) -> str:
    s = (s or "").strip()
    return s[:max_len] + ("..." if len(s) > max_len else "")


def run_logbook_forensic_audit(
    rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], str, List[Dict[str, Any]]]:
    """Run the full Logbook Map/Reduce forensic audit.

    Single implementation used by both Streamlit (pages/1_Logbook.py) and the API (POST /api/logbook/analyze).
    Map: one ask_assistant call per row with a micro-prompt; 8s sleep between rows (429-safe).
    Reduce: truncate reports, build synthesis prompt, one ask_assistant for system-wide anomaly report.
    Uses agentic mode and skip_regulation_check=True (maintenance compliance, not regulatory).

    Args:
        rows: List of dicts with keys Component, Part_Number, Hours_Since_New, Installed_Date.
              Part_Number can be "" or missing; Installed_Date can be None or ISO date string.

    Returns:
        (component_reports, synthesis_response, synthesis_sources)
        - component_reports: list of {component, part_number, report, sources}
        - synthesis_sources: list of {file_name, page_number, ...} for anomaly report
    """
    component_reports: List[Dict[str, Any]] = []
    total_rows = len(rows)

    for idx, row in enumerate(rows):
        component = str(row.get("Component", "")).strip()
        part_number_raw = row.get("Part_Number", "")
        if part_number_raw is None or part_number_raw == "" or (isinstance(part_number_raw, str) and not str(part_number_raw).strip()):
            part_number = ""
        else:
            part_number = str(part_number_raw).strip()
        hours = row.get("Hours_Since_New")
        installed_date = row.get("Installed_Date")

        date_str = "Not specified"
        if installed_date is not None and installed_date != "":
            if isinstance(installed_date, str):
                date_str = installed_date
            elif hasattr(installed_date, "strftime"):
                date_str = installed_date.strftime("%Y-%m-%d")
            else:
                date_str = str(installed_date)
        hours_str = f"{hours:.1f} hours" if hours is not None and not (isinstance(hours, float) and (hours != hours)) else "Not specified"

        if part_number:
            pn_context = f"Part Number (P/N): {part_number}"
            search_instruction = (
                f"Search the Aircraft Maintenance Manual (AMM) for the exact flight hour limit OR calendar time limit for Part Number {part_number}. "
                f'If not found, search by component name "{component}".'
            )
        else:
            pn_context = "Part Number (P/N): Not provided - you must look it up"
            search_instruction = (
                f'FIRST: Search the Illustrated Parts Catalog (IPC) or AMM to find the Part Number for component "{component}". '
                "THEN search for the exact flight hour limit OR calendar time limit using the Part Number you found (or component name if P/N still not found)."
            )

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

        try:
            response_text, source_nodes = ask_assistant(
                micro_prompt,
                use_chat_mode=True,
                skip_regulation_check=True,
            )
            component_reports.append({
                "component": component,
                "part_number": part_number or "Looked up by system",
                "report": response_text,
                "sources": source_nodes,
            })
        except Exception as e:
            component_reports.append({
                "component": component,
                "part_number": part_number or "Looked up by system",
                "report": f"❌ Error auditing this component: {str(e)}",
                "sources": [],
            })

        if idx + 1 < total_rows:
            time.sleep(8)

    parts = []
    total_len = 0
    for r in component_reports:
        block = f"**{r['component']}** (P/N: {r['part_number']})\n\n{_truncate_report(r['report'], MAX_CHARS_PER_REPORT)}"
        if total_len + len(block) > MAX_TOTAL_CONTEXT_CHARS:
            block = _truncate_report(block, max(500, MAX_TOTAL_CONTEXT_CHARS - total_len - 100))
        parts.append(block)
        total_len += len(block)
        if total_len >= MAX_TOTAL_CONTEXT_CHARS:
            break
    full_context = "\n\n---\n\n".join(parts)
    if total_len >= MAX_TOTAL_CONTEXT_CHARS or any(len((r.get("report") or "")) > MAX_CHARS_PER_REPORT for r in component_reports):
        full_context = "(Reports truncated for token limit.)\n\n" + full_context

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

    synthesis_response, synthesis_sources = ask_assistant(
        synthesis_prompt,
        use_chat_mode=True,
        skip_regulation_check=True,
    )
    return component_reports, synthesis_response, synthesis_sources


def generate_formal_log_entry(part_ref: str, raw_action: str) -> Tuple[str, str]:
    """Generate a formal aviation log entry from raw action notes.
    
    Uses RAG to find the maintenance procedure for the part, then rewrites
    the raw notes into Standard Aviation Phraseology.
    
    Args:
        part_ref: Part name or system reference (e.g., "fuel pump", "Part 12-45A")
        raw_action: Raw engineering notes (e.g., "replaced fuel pump, checked for leaks")
        
    Returns:
        Tuple of (formal_log_entry, reference_cited)
    """
    # Search for the maintenance procedure
    query = f"{part_ref} maintenance procedure removal installation"
    response_text, source_nodes = ask_assistant(query, similarity_top_k=5, use_chat_mode=False)
    
    # Extract reference from sources
    reference = "Manual Reference"
    if source_nodes:
        ref_parts = []
        for src in source_nodes[:2]:  # Use top 2 sources
            file_name = src.get('file_name', '')
            page = src.get('page_number', '')
            if file_name and page:
                ref_parts.append(f"{file_name}, Page {page}")
        if ref_parts:
            reference = " / ".join(ref_parts)
    
    # Create specialized prompt for log entry generation
    log_prompt = f"""You are an Aviation Maintenance Logger. Rewrite the user's raw notes into a formal log entry using Standard Aviation Phraseology (Uppercase).

RAW NOTES: {raw_action}

PART/SYSTEM: {part_ref}

CONTEXT FROM MANUALS:
{response_text}

INSTRUCTIONS:
1. Rewrite the raw notes into formal aviation logbook language
2. Use UPPERCASE for key actions (REMOVED, INSTALLED, INSPECTED, REPLACED, etc.)
3. Include the manual reference format: "IAW [Manual Name] [Section/Page]"
4. Keep it concise (1-2 sentences maximum)
5. Use standard aviation terminology

FORMAL LOG ENTRY:"""

    llm = OpenAI(model="gpt-4o", api_key=Config.OPENAI_API_KEY, temperature=0.1)
    response = llm.complete(log_prompt)
    formal_entry = str(response).strip() if hasattr(response, '__str__') else (response.text if hasattr(response, 'text') else str(response))
    
    return formal_entry, reference


def audit_log_compliance(date_performed: str, part_name: str, aircraft_type: str) -> Tuple[str, str]:
    """Audit if a maintenance action is compliant or overdue.
    
    Calculates days elapsed since maintenance, searches for inspection intervals,
    and determines compliance status.
    
    Args:
        date_performed: Date string (format: YYYY-MM-DD)
        part_name: Name of the part/system maintained
        aircraft_type: Aircraft type (e.g., "R44", "R22")
        
    Returns:
        Tuple of (status, reasoning) where status is "COMPLIANT" or "OVERDUE"
    """
    from datetime import datetime, date
    
    # Parse date and calculate days elapsed
    try:
        if isinstance(date_performed, str):
            perf_date = datetime.strptime(date_performed, "%Y-%m-%d").date()
        else:
            perf_date = date_performed
        today = date.today()
        days_elapsed = (today - perf_date).days
    except Exception as e:
        return "ERROR", f"Invalid date format: {e}"
    
    # Search for maintenance interval
    query = f"{aircraft_type} {part_name} maintenance interval frequency inspection schedule"
    response_text, source_nodes = ask_assistant(query, similarity_top_k=5, use_chat_mode=False)
    
    # Extract reference
    reference = "Manual Reference"
    if source_nodes:
        ref_parts = []
        for src in source_nodes[:2]:
            file_name = src.get('file_name', '')
            page = src.get('page_number', '')
            if file_name and page:
                ref_parts.append(f"{file_name}, Page {page}")
        if ref_parts:
            reference = " / ".join(ref_parts)
    
    # Create audit prompt
    audit_prompt = f"""Today is {today.strftime('%Y-%m-%d')}. The user performed maintenance on {part_name} on {date_performed} ({days_elapsed} days ago).

CONTEXT FROM MANUALS:
{response_text}

INSTRUCTIONS:
1. Extract the required inspection/maintenance interval from the context (e.g., "12 months", "500 hours", "every 6 months")
2. Convert the interval to days if needed (assume 1 month = 30 days, 1 year = 365 days)
3. Compare {days_elapsed} days elapsed vs. the required interval
4. Determine if the maintenance is COMPLIANT or OVERDUE
5. Provide specific reasoning with the interval found

Answer format:
STATUS: [COMPLIANT or OVERDUE]
REASONING: [Specific explanation with interval found and comparison]"""

    llm = OpenAI(model="gpt-4o", api_key=Config.OPENAI_API_KEY, temperature=0.1)
    response = llm.complete(audit_prompt)
    audit_result = str(response).strip() if hasattr(response, '__str__') else (response.text if hasattr(response, 'text') else str(response))
    
    # Parse status
    status = "COMPLIANT"
    if "OVERDUE" in audit_result.upper() or "NON-COMPLIANT" in audit_result.upper():
        status = "OVERDUE"
    
    reasoning = audit_result.replace("STATUS:", "").replace("REASONING:", "").strip()
    if not reasoning:
        reasoning = audit_result
    
    return status, f"{reasoning}\n\nReference: {reference}"


def review_logbook_entries(logbook_df) -> str:
    """Review logbook entries for compliance and completeness.
    
    Analyzes each entry and checks if it's compliant with maintenance intervals.
    If information is missing or insufficient, clearly states what's needed.
    
    Args:
        logbook_df: DataFrame with columns: Date, Aircraft Type, Part/System, Action Description
        
    Returns:
        Review result as a formatted string
    """
    import pandas as pd
    from datetime import datetime, date
    
    if logbook_df.empty:
        return "No logbook entries to review."
    
    # Build logbook summary
    logbook_summary = "LOGBOOK ENTRIES TO REVIEW:\n\n"
    entries_to_review = []
    missing_info_entries = []
    
    for idx, row in logbook_df.iterrows():
        date_val = row.get("Date", "")
        aircraft_type = str(row.get("Aircraft Type", "")).strip()
        part_name = str(row.get("Part/System", "")).strip()
        action_desc = str(row.get("Action Description", "")).strip()
        
        # Check for missing info
        missing = []
        if pd.isna(date_val) or date_val == "":
            missing.append("Date")
        if not aircraft_type:
            missing.append("Aircraft Type")
        if not part_name:
            missing.append("Part/System")
        if not action_desc:
            missing.append("Action Description")
        
        if missing:
            missing_info_entries.append({
                "entry": idx + 1,
                "missing": missing,
                "partial_info": f"Aircraft: {aircraft_type or 'N/A'}, Part: {part_name or 'N/A'}, Action: {action_desc or 'N/A'}"
            })
        else:
            # Format date
            if isinstance(date_val, str):
                date_str = date_val
            else:
                date_str = date_val.strftime("%Y-%m-%d") if hasattr(date_val, 'strftime') else str(date_val)
            
            entries_to_review.append({
                "entry": idx + 1,
                "date": date_str,
                "aircraft": aircraft_type,
                "part": part_name,
                "action": action_desc,
            })
            
            logbook_summary += f"Entry {idx + 1}: Date={date_str}, Aircraft={aircraft_type}, Part={part_name}, Action={action_desc}\n"
    
    # If there are entries with missing info, state clearly what's needed
    if missing_info_entries:
        missing_msg = "⚠️ **CANNOT REVIEW - MISSING INFORMATION**\n\n"
        missing_msg += "The following entries are missing critical information and cannot be reviewed:\n\n"
        for item in missing_info_entries:
            missing_msg += f"**Entry {item['entry']}:** Missing: {', '.join(item['missing'])}\n"
            missing_msg += f"  Partial info: {item['partial_info']}\n\n"
        missing_msg += "**Please provide complete information (Date, Aircraft Type, Part/System, Action Description) for all entries before requesting a review.**\n\n"
        
        if entries_to_review:
            missing_msg += "---\n\n**Entries with complete information will be reviewed below:**\n\n"
        else:
            return missing_msg
    
    if not entries_to_review:
        return "No complete entries to review. Please ensure all entries have Date, Aircraft Type, Part/System, and Action Description."
    
    # Review complete entries
    today = date.today()
    review_results = []
    
    for entry in entries_to_review:
        try:
            # Calculate days elapsed
            perf_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
            days_elapsed = (today - perf_date).days
            
            # Search for maintenance interval
            query = f"{entry['aircraft']} {entry['part']} maintenance interval frequency inspection schedule"
            response_text, source_nodes = ask_assistant(query, similarity_top_k=5, use_chat_mode=False)
            
            # Extract reference
            reference = "Manual Reference"
            if source_nodes:
                ref_parts = []
                for src in source_nodes[:2]:
                    file_name = src.get('file_name', '')
                    page = src.get('page_number', '')
                    if file_name and page:
                        ref_parts.append(f"{file_name}, Page {page}")
                if ref_parts:
                    reference = " / ".join(ref_parts)
            
            # Create review prompt
            review_prompt = f"""Today is {today.strftime('%Y-%m-%d')}. Review this maintenance logbook entry:

ENTRY {entry['entry']}:
- Date Performed: {entry['date']} ({days_elapsed} days ago)
- Aircraft Type: {entry['aircraft']}
- Part/System: {entry['part']}
- Action: {entry['action']}

CONTEXT FROM MAINTENANCE MANUALS:
{response_text}

INSTRUCTIONS:
1. Extract the required inspection/maintenance interval for {entry['part']} on {entry['aircraft']} from the context
2. If the interval is not clearly found in the context, state: "CANNOT REVIEW - Interval information not found in manuals. Please provide the specific maintenance interval requirement."
3. If interval is found, convert to days (1 month = 30 days, 1 year = 365 days, 1 hour = assume 0.1 days for calculation)
4. Compare {days_elapsed} days elapsed vs. the required interval
5. Determine if COMPLIANT or OVERDUE
6. Provide clear reasoning

Answer format:
STATUS: [COMPLIANT / OVERDUE / CANNOT REVIEW]
REASONING: [Specific explanation]"""

            llm = OpenAI(model="gpt-4o", api_key=Config.OPENAI_API_KEY, temperature=0.1)
            response = llm.complete(review_prompt)
            review_result = str(response).strip() if hasattr(response, '__str__') else (response.text if hasattr(response, 'text') else str(response))
            
            review_results.append({
                "entry": entry['entry'],
                "result": review_result,
                "reference": reference,
            })
            
        except Exception as e:
            review_results.append({
                "entry": entry['entry'],
                "result": f"ERROR: Could not review entry {entry['entry']}: {str(e)}",
                "reference": "N/A",
            })
    
    # Format final review
    final_review = ""
    if missing_info_entries:
        final_review += missing_msg
    
    final_review += "## 📋 Logbook Review Results\n\n"
    
    compliant_count = 0
    overdue_count = 0
    cannot_review_count = 0
    
    for result in review_results:
        final_review += f"### Entry {result['entry']}\n\n"
        final_review += f"{result['result']}\n\n"
        final_review += f"**Reference:** {result['reference']}\n\n"
        final_review += "---\n\n"
        
        if "CANNOT REVIEW" in result['result'].upper():
            cannot_review_count += 1
        elif "OVERDUE" in result['result'].upper():
            overdue_count += 1
        elif "COMPLIANT" in result['result'].upper():
            compliant_count += 1
    
    # Summary
    final_review += f"## 📊 Summary\n\n"
    final_review += f"- ✅ **Compliant:** {compliant_count}\n"
    final_review += f"- ⚠️ **Overdue:** {overdue_count}\n"
    final_review += f"- ❓ **Cannot Review:** {cannot_review_count}\n"
    
    if overdue_count > 0:
        final_review += f"\n⚠️ **{overdue_count} entry/entries require immediate attention!**\n"
    
    if cannot_review_count > 0:
        final_review += f"\n❓ **{cannot_review_count} entry/entries could not be reviewed due to missing information in manuals. Please verify intervals manually.**\n"
    
    return final_review


def main():
    """Test the assistant engine."""
    import sys
    
    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        print(f"Configuration error: {e}")
        return
    
    # Get question from command line or use default
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    else:
        question = "What is the procedure for inspecting a fuel pump?"
    
    print(f"\nQuestion: {question}\n")
    print("=" * 80)
    
    try:
        response_text, source_nodes = ask_assistant(question)
        
        print("\nAnswer:")
        print("-" * 80)
        print(response_text)
        print("-" * 80)
        
        print(f"\n\nSources ({len(source_nodes)}):")
        print("=" * 80)
        for i, source in enumerate(source_nodes, 1):
            print(f"\nSource {i}:")
            print(f"  File: {source['file_name']}")
            print(f"  Page: {source['page_number']}")
            print(f"  Type: {source['element_type']}")
            if source.get('score') is not None:
                print(f"  Score: {source['score']:.4f}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

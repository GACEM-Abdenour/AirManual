# Agent's Brain Technical Audit Report
## `src/engine.py` - FunctionAgent Configuration

**Date:** February 9, 2026  
**File:** `src/engine.py`  
**Function:** `create_agent()` (lines 133-196)

---

## 1. THE SYSTEM PROMPT

**Location:** Lines 62-70 (`AGENT_SYSTEM_PROMPT` constant)  
**Passed to:** `FunctionAgent` constructor, `system_prompt` parameter (line 193)

**Exact Text:**
```
You are an advanced Aviation Maintenance AI with access to aircraft manuals and regulations.

Capabilities:
- **Context Awareness**: If the user says "it", "that", or "the part", refer to the previous conversation. Remember what component or procedure was discussed.
- **Decomposition**: If the user asks a complex question (e.g., "Compare A and B", "Check the pump and the landing gear"), break it down. Search for A, then search for B, then synthesize the answer.
- **Clarification**: If the user's query is vague (e.g., "How do I fix it?" without prior context, or "Is it broken?"), DO NOT search blindly. Instead, ask the user to clarify what component they are referring to.
- **Citations**: Always cite the manual name and page from the tool output. Format: [Document Name, Page X]

Use the aviation_manuals_tool for any technical lookup. Never guess or hallucinate—only answer from tool results.
```

**Note:** There is also a `SYSTEM_PROMPT` constant (lines 22-59) used for the query engine's QA template, but the agent itself uses `AGENT_SYSTEM_PROMPT`.

---

## 2. MEMORY CONFIGURATION

**Location:** Line 194  
**Class:** `ChatMemoryBuffer` (imported from `llama_index.core.memory`)

**Code:**
```python
memory=ChatMemoryBuffer.from_defaults(token_limit=4000)
```

**Findings:**
- ✅ **Token Limit:** `4000` tokens
- ✅ **Memory IS Passed:** Yes, the memory is correctly passed to `FunctionAgent` constructor at line 194
- ✅ **Memory is Active:** The agent has memory enabled and will maintain conversation context

**Verification:**
```python
agent = FunctionAgent(
    tools=[aviation_tool],
    llm=llm,
    system_prompt=AGENT_SYSTEM_PROMPT,
    memory=ChatMemoryBuffer.from_defaults(token_limit=4000),  # ← Memory is passed here
)
```

---

## 3. MODEL SETTINGS

**Location:** Lines 154-159  
**Class:** `OpenAI` (from `llama_index.llms.openai`)

**Code:**
```python
llm = OpenAI(
    model="gpt-4o",
    api_key=Config.OPENAI_API_KEY,
    temperature=temperature,
    timeout=120.0,
)
```

**Default Temperature:** `0.1` (line 135, function parameter default)

**Findings:**
- **Model:** `gpt-4o` (GPT-4 Omni)
- **Temperature:** `0.1` (very low, makes responses more deterministic/factual)
- **Timeout:** `120.0` seconds

**Analysis:**
- The temperature of `0.1` is very low, which makes the AI more robotic and deterministic
- For a more conversational persona, consider increasing to `0.3-0.7` range
- Current setting prioritizes factual accuracy over conversational tone

---

## 4. TOOL DESCRIPTION

**Location:** Lines 180-188  
**Tool:** `QueryEngineTool.from_defaults()`

**Code:**
```python
aviation_tool = QueryEngineTool.from_defaults(
    query_engine=query_engine,
    name="aviation_manuals_tool",
    description=(
        "Useful for looking up technical procedures, part numbers, and maintenance "
        "intervals in the Aircraft Manuals and Regulations. Always use this for "
        "technical questions about maintenance, parts, inspections, or compliance."
    ),
)
```

**Exact Description String:**
```
Useful for looking up technical procedures, part numbers, and maintenance intervals in the Aircraft Manuals and Regulations. Always use this for technical questions about maintenance, parts, inspections, or compliance.
```

**Analysis:**
- This description controls when the agent decides to use the tool vs. just chatting
- The phrase "Always use this for technical questions" is directive and may cause the agent to over-use the tool
- For a more conversational persona, consider softening the language (e.g., "Use this when you need to look up..." instead of "Always use this for...")

---

## SUMMARY

| Component | Current Value | Status |
|-----------|--------------|--------|
| **System Prompt** | `AGENT_SYSTEM_PROMPT` (62-70) | ✅ Active |
| **Memory Token Limit** | `4000` | ✅ Configured & Passed |
| **Model** | `gpt-4o` | ✅ Set |
| **Temperature** | `0.1` | ⚠️ Very Low (Robotic) |
| **Tool Description** | Directive ("Always use this...") | ⚠️ May Over-Trigger Tool |

---

## RECOMMENDATIONS FOR CONVERSATIONAL PERSONA

1. **Temperature:** Increase from `0.1` to `0.4-0.6` for more natural conversation
2. **System Prompt:** Rewrite `AGENT_SYSTEM_PROMPT` to be more conversational and less directive
3. **Tool Description:** Soften language to reduce over-triggering (e.g., "Use this when you need..." instead of "Always use this...")

---

**End of Report**

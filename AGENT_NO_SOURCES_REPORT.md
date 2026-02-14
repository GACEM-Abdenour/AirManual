# Report: Agent Not Using Tool → No Sources (Worse Than Before)

**Date:** February 2026  
**Question:** "how much time can i fly with the r44"  
**Mode:** Agentic (Use Agentic mode checked)

---

## 1. What You Observed

### Before (from your screenshot)
- **Answer:** Specific data from the manual: inspection intervals (100 hours or 12 months, whichever first; 10-hour extension if allowed). Citation in text: "[HELICOPTER MAINTENANCE MANUAL, Page 57]".
- **View Sources:** Present (expandable). So the response was grounded in retrieval and sources were available.

### After our persona/tool-description changes
- **Answer:** "I'm currently unable to access the specific manuals to retrieve the flight time or endurance for the R44 helicopter. However, typically, the R44 has an endurance of approximately 3 to 4 hours..."
- **View Sources:** "No sources available for this response."

So the behavior got **worse**: the model stopped using the manuals and started deflecting (“unable to access”) and giving generic, uncited text.

---

## 2. Root Cause (Detailed)

### 2.1 Why there are no sources

- In **agentic mode**, the UI calls `ask_assistant(prompt, use_chat_mode=True)`.
- That uses a **FunctionAgent** with one tool: `aviation_manuals_tool` (the RAG lookup).
- Sources in the UI come **only** from **tool outputs**. The code does:
  - Run the agent → collect `tool_outputs` from each `ToolCallResult`.
  - Build `source_nodes` by reading `raw_output.source_nodes` from each tool output.
- If the agent **never calls** `aviation_manuals_tool`, then:
  - `tool_outputs` is empty.
  - `source_nodes` stays empty → **"No sources available for this response."**

So: **no tool call ⇒ no sources.** The problem is that the agent is not calling the tool for your question.

### 2.2 Why the agent says “unable to access” and gives generic text

Two possibilities (both lead to the same bad UX):

1. **Agent never called the tool**  
   The model chose to answer from its own knowledge and added a polite deflection (“I’m currently unable to access the specific manuals”) so it didn’t have to say “I don’t know.” So you get a generic answer (e.g. “3–4 hours”) and no sources.

2. **Agent called the tool but something failed**  
   If the tool had been called and raised an exception (e.g. index not loaded, Qdrant error), the framework might pass an error back to the agent, and the model could reply with “unable to access.” Even then, our code would still see no successful tool output → no `source_nodes` → no sources.

In both cases the **observable** result is: answer with no sources and a deflection. So the fix must both (a) make tool use more reliable and (b) guarantee that **factual questions still get a retrieved answer with sources** when the agent doesn’t use the tool.

### 2.3 Why it used to work “like the picture”

- In your screenshot, the reply looked like a **single-shot RAG** answer: one clear answer, one citation, and a “View Sources” section. That matches **non‑agentic** behavior: the app calls the **query engine** directly (`get_query_engine().query(question)`), which **always** retrieves and always returns `response.source_nodes`. So you always get sources.
- In **agentic** mode, the app uses the **agent**; the agent can either call the tool or not. When it doesn’t call the tool, we never run retrieval, so we never have sources. So the regression is: in agentic mode, the agent often does not call the tool for questions like “how much time can I fly with the r44,” and we had no fallback to retrieval.

---

## 3. What Was Done So Far (And Why It Wasn’t Enough)

- **Prompt:** We added instructions like “use the tool immediately for factual questions” and “do not say ‘Would you like me to look up?’”.
- **Tool description:** We made it explicit that the tool is for fuel, endurance, flight time, etc., and to “call it immediately” for questions like “how much time can I fly with the R44?”.

**Why it wasn’t enough:**  
LLM behavior is not deterministic. The model can still:
- Skip the tool and answer from memory.
- Reply with “unable to access” without having called the tool (or after a failed call).

Relying only on prompt/description does not **guarantee** tool use or sources. So we need a **logic-level guarantee**: when the user asks a clear factual question and the agent returns **no sources**, we run retrieval ourselves and return that answer and its sources.

---

## 4. Fix Implemented in Code

### 4.1 Factual-question detector

- Added `_is_factual_lookup_question(question)` in `src/engine.py`.
- It uses simple heuristics: question contains phrases like “how much”, “how long”, “fuel”, “endurance”, “flight time”, “r44”, “inspection”, “torque”, “procedure”, “capacity”, “limit”, etc.
- Used only to decide when to apply the fallback below.

### 4.2 Fallback when agent returns no sources

- In `ask_assistant()`, in the **agentic** branch, after we have the agent’s reply and we’ve built `source_nodes` from tool outputs:
  - If **`source_nodes` is empty** and **`_is_factual_lookup_question(question)` is True**:
    - We **ignore** the agent’s reply for the purpose of the final answer.
    - We call **`get_query_engine(similarity_top_k=...).query(question)`** once (same as non‑agentic path).
    - We set:
      - `response_text = str(response)`
      - `source_nodes = [extract_source_info(node) for node in response.source_nodes]`
- So for questions like “how much time can I fly with the r44”, even if the agent never calls the tool (or the tool fails), the user **always** gets:
  - An answer from the **retrieved** docs (like before in your screenshot).
  - **View Sources** populated from the query engine’s `source_nodes`.

So we fix both:
- **No sources** → fallback ensures sources for factual lookups.
- **“Worse than before”** → for these questions the answer is again the RAG answer from the manuals, not the generic “unable to access” + “3–4 hours” reply.

### 4.3 What stays the same

- For **non‑factual** questions (e.g. “Hello”, “Which pump?”), we do **not** fallback; we keep the agent’s reply and accept that there may be no sources.
- When the agent **does** call the tool and returns sources, we keep the agent’s answer and those sources; the fallback is only when `source_nodes` is empty and the question looks factual.

---

## 5. Summary

| Item | Detail |
|------|--------|
| **Problem** | In agentic mode, for “how much time can I fly with the r44”, the agent often doesn’t call the tool → no sources; it then says “unable to access” and gives a generic answer. So it was worse than the previous behavior (single-shot RAG with citation and sources). |
| **Root cause** | Sources come only from tool outputs. No tool call ⇒ no sources. Prompt/tool description alone don’t guarantee tool use. |
| **Fix** | If agentic mode returns **no** `source_nodes` and the question is considered a factual lookup, we **fallback** to the query engine once and return its answer + `source_nodes`. So factual questions always get a manual-grounded answer with sources. |
| **Code** | `src/engine.py`: added `_is_factual_lookup_question()`, and in the agentic branch added the fallback that calls `get_query_engine(...).query(question)` and uses that response when `source_nodes` was empty and the question is factual. |

After this change, asking “how much time can I fly with the r44” in agentic mode should again yield an answer from the manuals and a filled “View Sources” (either from the agent’s tool call or from the fallback).

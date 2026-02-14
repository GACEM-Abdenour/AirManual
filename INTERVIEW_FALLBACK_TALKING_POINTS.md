# Deterministic Fallback Layer — Interview / Client Demo Talking Points

Use this when explaining the "lazy agent" fix in interviews or client demos.

---

## Don't say
"The AI was buggy so we forced it."

## Do say

> "I implemented a **Deterministic Fallback Layer** for safety-critical queries.
>
> The Agent uses probabilistic reasoning to decide when to use tools. In aviation maintenance we cannot tolerate false negatives—missing a manual lookup. So I added a classification heuristic that detects factual parameters: torque, limits, fuel, procedures, and the like.
>
> If the Agent fails to invoke the RAG tool for those queries, the system automatically triggers a **high-priority retrieval** and overrides the response with the official procedure and citations. That way the mechanic always sees cited, manual-based data, regardless of the Agent's decision."

## One-liner
"We treat the Agent as advisory and the fallback as the guarantee for safety-critical lookups."

---

## In the code

- **`_is_factual_lookup_question()`** — docstring describes it as the "classification heuristic for the Deterministic Fallback Layer."
- **Fallback block in `ask_assistant()`** — comment describes "Deterministic Fallback Layer (safety-critical)" and why we override when the Agent didn't invoke the RAG tool.

# Bug Report: 429 Rate Limit Error (TPM Exceeded) in Logbook Analysis

## Issue Summary
The System-Wide Anomaly Report (Reduce phase) fails with a 429 error when processing component audits. The error indicates the request exceeds OpenAI's tokens-per-minute (TPM) limit of 30,000 tokens.

**Error Message:**
```
Deep research synthesis failed: Error code: 429 - {'error': {'message': 'Request too large for gpt-4o in organization org-lmDBusNx5wT6r5G95G94qdzw on tokens per min (TPM): Limit 30000, Requested 45890. The input or output tokens must be reduced in order to run successfully. Visit https://platform.openai.com/account/rate-limits to learn more.', 'type': 'tokens', 'param': None, 'code': 'rate_limit_exceeded'}}
```

## Root Cause Analysis

### Architecture Flow
1. **Map Phase**: Each component is audited individually via `ask_assistant()` in `pages/1_Logbook.py`
2. **Deep Research Trigger**: If retrieval confidence < 0.70, `_run_deep_research()` is called (in `src/engine.py`)
3. **Deep Research Context Building**: `_run_deep_research()` concatenates ALL retrieved nodes without truncation:
   - Original query: `2 × similarity_top_k` nodes (up to 60)
   - 3 query variations: `similarity_top_k` nodes each (default 20)
   - Total: Up to 120 nodes × ~500-1000 tokens/node = **60k-120k tokens**
4. **Reduce Phase**: All component reports (including full deep research outputs) are concatenated into `full_context`
5. **Synthesis Call**: The synthesis prompt includes the entire `full_context`, exceeding 30k TPM limit

### Problem Locations

#### Issue 1: `_run_deep_research()` in `src/engine.py` (Lines 532-544)
```python
context_str = "\n\n---\n\n".join(
    n.get_content() if hasattr(n, "get_content") else ...
    for n in all_nodes  # No truncation - can be 60-120 nodes
)
```
**Problem**: No token/character limit on `context_str`. With expanded retrieval (up to 120 nodes), this can easily exceed 50k+ tokens.

#### Issue 2: Component Report Concatenation in `pages/1_Logbook.py` (Line 244)
**Status**: ✅ **PARTIALLY FIXED** - Truncation added (lines 227-246), but:
- Truncation limits: 2,500 chars per report, 18,000 chars total
- If individual component audits already return huge reports (from deep research), truncation may not be sufficient
- The truncation happens AFTER deep research has already built a massive context

## Impact
- **Severity**: High - Blocks logbook analysis functionality
- **Frequency**: Occurs when:
  - Multiple components trigger deep research (low confidence retrievals)
  - Component audits return large reports
  - More than 2-3 components are analyzed simultaneously

## Proposed Solutions

### Solution 1: Add Truncation to `_run_deep_research()` (RECOMMENDED)
**File**: `src/engine.py`, function `_run_deep_research()`

Add token-aware truncation before building `context_str`:
```python
# After line 531 (after collecting all_nodes)
MAX_CONTEXT_TOKENS = 15000  # ~60k chars, safe margin under 30k TPM
MAX_CHARS_PER_NODE = 1000   # ~250 tokens per node
MAX_TOTAL_CONTEXT_CHARS = 50000  # ~12.5k tokens

def truncate_node_content(node) -> str:
    content = node.get_content() if hasattr(node, "get_content") else (
        node.node.get_content() if hasattr(node, "node") and node.node else str(node)
    )
    return content[:MAX_CHARS_PER_NODE] + ("..." if len(content) > MAX_CHARS_PER_NODE else "")

context_parts = []
total_len = 0
for n in all_nodes:
    node_str = truncate_node_content(n)
    if total_len + len(node_str) > MAX_TOTAL_CONTEXT_CHARS:
        break
    context_parts.append(node_str)
    total_len += len(node_str)

context_str = "\n\n---\n\n".join(context_parts)
if len(all_nodes) > len(context_parts):
    context_str = f"(Context truncated: showing {len(context_parts)} of {len(all_nodes)} nodes)\n\n" + context_str
```

### Solution 2: Reduce Deep Research Retrieval Scope
**File**: `src/engine.py`, function `_run_deep_research()`

Reduce the number of nodes retrieved:
- Change `expanded_k = min(2 * similarity_top_k, 60)` to `min(2 * similarity_top_k, 30)`
- Reduce query variations from 3 to 2
- This reduces max nodes from ~120 to ~50

### Solution 3: Increase Truncation Limits in Logbook Reduce Phase
**File**: `pages/1_Logbook.py`, lines 228-229

If deep research contexts are already truncated, increase logbook truncation:
```python
MAX_CHARS_PER_REPORT = 4000   # Increased from 2500
MAX_TOTAL_CONTEXT_CHARS = 25000  # Increased from 18000
```

### Solution 4: Implement Chunked Synthesis (For Many Components)
**File**: `pages/1_Logbook.py`, Reduce phase

If >5 components, synthesize in batches:
1. Group components into batches of 3
2. Run synthesis on each batch
3. Run final meta-synthesis on batch summaries

## Recommended Implementation Order
1. **Immediate**: Implement Solution 1 (truncate `_run_deep_research()` context)
2. **Secondary**: Implement Solution 2 (reduce retrieval scope) if Solution 1 isn't sufficient
3. **Future**: Consider Solution 4 (chunked synthesis) if analyzing many components becomes common

## Testing Checklist
- [ ] Test with 1 component (should not trigger deep research)
- [ ] Test with 2-3 components (some may trigger deep research)
- [ ] Test with 5+ components (multiple deep research calls)
- [ ] Verify synthesis prompt stays under 25k tokens
- [ ] Verify individual component audits still return useful information
- [ ] Verify truncation warnings appear when context is truncated

## Files Modified
- ✅ `src/engine.py` - `_run_deep_research()` function (**FIXED** - truncation added)
- ✅ `pages/1_Logbook.py` - Reduce phase truncation (already implemented)

## Fix Status
**FIXED** - Both issues addressed:
1. `_run_deep_research()` now truncates context to ~50k chars (~12.5k tokens)
2. Logbook Reduce phase truncates reports to ~18k chars (~4.5k tokens)
3. Combined: Synthesis prompts should stay well under 30k TPM limit

## Related Code References
- `DEEP_RESEARCH_CONFIDENCE_THRESHOLD = 0.70` (line 23 in `engine.py`)
- `similarity_top_k` default = 20 (line 556 in `engine.py`)
- Map-Reduce architecture in `pages/1_Logbook.py` (lines 198-280)

## Notes
- OpenAI TPM limit: 30,000 tokens per minute
- Rough token estimation: ~4 characters per token
- Current request size: 45,890 tokens (53% over limit)
- Safe target: Keep synthesis prompts under 20,000 tokens to allow for response tokens

# Geo-Resolver Performance Options

## Current Profile (Gemini 3 Flash via OpenRouter)
- 3 LLM round trips × ~1s each = **3.4s total**
- DB lookups: <10ms (negligible)
- Bottleneck is 100% LLM network latency

## Option 1: Single-Shot Structured Output (Recommended — biggest win)

**Idea:** Instead of a multi-turn tool-calling loop, have the LLM output a single structured plan (JSON) that we execute locally. One LLM call instead of 3+.

```
Current:  User → LLM → tool call → LLM → tool call → LLM → finalize  (3 calls)
Proposed: User → LLM → structured plan → execute locally → done        (1 call)
```

The LLM returns something like:
```json
{
  "strategy": "simple_lookup",
  "steps": [
    {"tool": "search_places", "args": {"name": "San Francisco", "place_type": "locality", "context": "California"}}
  ]
}
```

For complex queries ("Bay Area" = 9 counties unioned), it'd return:
```json
{
  "strategy": "compose",
  "steps": [
    {"tool": "search_places", "args": {"name": "San Francisco County"}},
    {"tool": "search_places", "args": {"name": "Alameda County", "context": "California"}},
    ...
  ],
  "compose": {"tool": "union", "args": {"geometry_ids": "all"}}
}
```

**Speedup:** 1 LLM call (~1s) instead of 3+ (~3.4s). **~3x faster.**
**Risk:** Complex queries may need iteration (fallback to current loop).
**Hybrid:** Try single-shot first, fall back to multi-turn if the plan fails.

## Option 2: Pre-query RAG / Context Injection

**Idea:** Before the LLM call, do a fast DB pre-search to inject candidate results into the prompt. This gives the LLM enough info to finalize in fewer rounds.

```python
# Before LLM call:
candidates = db.quick_search(query)  # fuzzy match, top 5 results
# Inject into prompt:
"Pre-matched candidates: [{name: 'San Francisco', type: 'locality', geometry_id: 'g1', ...}]"
```

**Speedup:** Eliminates 1-2 LLM round trips. Combined with single-shot, could be 1 call for almost everything.
**Complexity:** Need a good pre-search (fuzzy text match + type inference).

## Option 3: Local Model (Ollama)

**Idea:** Run a small model locally to eliminate network latency entirely.

- Qwen 2.5 7B or Mistral 7B can do structured output / tool calling
- ~200ms per call on CPU (Ryzen 5 7640U)
- 3 calls × 200ms = **~0.6s total**

**Speedup:** ~5-6x faster than remote API.
**Risk:** Smaller models may struggle with complex decomposition (Bay Area = 9 counties).
**Setup:** `ollama pull qwen2.5:7b` — already OpenAI-compatible, no code changes needed.

## Option 4: Caching Layer

**Idea:** Cache resolved queries. "San Francisco" is always San Francisco.

- LRU cache keyed on normalized query string
- Store the final GeoJSON + geometry
- Cache hit = 0ms, no LLM call at all

**Speedup:** Instant for repeat queries.
**Scope:** Only helps with exact/near-exact repeats. Still need LLM for novel queries.

## Option 5: Hybrid Pipeline

Combine the best of each:

```
Query arrives
  → Check cache → HIT → return immediately
  → MISS → Pre-search DB for candidates
  → If single obvious match (high confidence) → return without LLM
  → Else → Single-shot LLM call with candidates injected
  → If plan fails → Fall back to multi-turn loop
```

**Expected performance:**
- Cached queries: **<10ms**
- Simple lookups (1 clear match): **<50ms** (no LLM needed!)
- Standard queries: **~1s** (single LLM call)
- Complex compositions: **~2-3s** (multi-turn fallback)

## Recommendation

**Start with Options 1 + 2 + 4 combined:**
1. Add a cache layer (easy, instant wins for repeats)
2. Add DB pre-search that injects candidates into prompt
3. Restructure prompt for single-shot structured output
4. Keep multi-turn as fallback for complex queries

This gets most queries down to **~1s** with zero infrastructure changes.

**Then optionally add Option 3 (Ollama)** if you want sub-second for everything and are OK with the quality tradeoff on complex queries.

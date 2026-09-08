# LifeContext L1 memory architecture

LifeContext keeps memory construction local even when final inference uses a
cloud model. The cloud endpoint receives only the already selected and compiled
`messages` for the current turn.

## Memory layers

1. **Archive** — immutable, content-addressed source files.
2. **Evidence** — traceable excerpts with source and locator metadata.
3. **ThoughtCell** — semantic candidates extracted from Evidence and linked back
   through `evidence_ids`.
4. **Persona** — versionable SOUL, MEMORY and STYLE views compiled from reviewed
   ThoughtCells and merged with the hand-curated templates/persona/ baseline.
5. **Conversation** — append-only local turn logs, isolated by `session_id`.
6. **Working context** — the bounded context assembled for one inference call.

## Trust and write policy

The current trust order is: user-authored oral history, user-confirmed memory or
ThoughtCell, unreviewed extracted candidate, and model output. Model output is
never treated as a user memory.

Messages that contain an explicit preference, decision, identity statement or
life event may create a memory candidate. Candidates start as `unreviewed` and
must be confirmed or rejected through `/v1/memory/candidates/{id}/review`.
Confirmed candidates are injected into later working contexts; rejected ones are
retained for audit but not used as memory.

## Retrieval

The dependency-free local retriever combines direct lexical matches, Chinese
bigrams, source-name matches and query expansion through related ThoughtCells.
Confirmed ThoughtCells receive a higher trust weight. Each answer still cites the
underlying Evidence rather than citing an opaque vector hit.

A later release can add embeddings and a reranker behind this interface without
changing the portable Archive, Evidence or ThoughtCell formats.

## Cloud boundary

`data/cloud/config.json` stores only provider, base URL, model, timeout and the
enabled state. API keys remain in backend process memory and disappear when the
backend stops. Extraction, retrieval, conversation storage and memory review do
not call the cloud endpoint.

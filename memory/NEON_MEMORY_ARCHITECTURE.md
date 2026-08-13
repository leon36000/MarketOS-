# Neon Memory Control Plane

Neon Postgres is a candidate durable index and structured memory service, not a replacement for the verified file canon.

## Retrieval order

1. exact ID;
2. authority and temporal SQL filters;
3. keyword/BM25 search;
4. vector similarity;
5. hybrid reciprocal-rank fusion;
6. graph expansion only when necessary;
7. reranking and bounded context compression.

## Memory classes

- canonical requirements and decisions;
- episodic experiments and incidents;
- semantic facts with provenance;
- temporal corrections and invalidations;
- evidence and negative results;
- open loops and checkpoints.

## Safety

Secrets are referenced, never embedded. Memories must preserve source, version, hash, first-seen time and validity intervals. Invalidated records remain auditable and cannot silently become current state.

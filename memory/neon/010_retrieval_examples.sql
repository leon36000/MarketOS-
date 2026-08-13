-- Exact ID first
SELECT * FROM marketos_memory.requirements
WHERE requirement_id = $1 AND (valid_to IS NULL OR valid_to > now());

-- Authority-aware full-text retrieval
SELECT d.document_id, d.source_id, d.canonical_id, d.section_path,
       ts_rank_cd(d.tsv, websearch_to_tsquery('simple', $1)) AS rank,
       d.content
FROM marketos_memory.active_documents d
JOIN marketos_memory.sources s USING (source_id)
WHERE d.tsv @@ websearch_to_tsquery('simple', $1)
  AND s.status NOT IN ('QUARANTINED','REJECTED')
ORDER BY s.authority_rank ASC, rank DESC
LIMIT $2;

-- Vector retrieval should be added only after embedding model + dimension are locked.
-- Hybrid RRF should fuse keyword and vector rankings while preserving authority filters.

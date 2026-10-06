"""Book-content RAG: grounded question answering over ingested book editions.

Separate from the catalogue assistant (bot/ai.py): the catalogue answers "which
book / where to buy", this answers "what does this book say", only from stored
passages, with page citations, and abstains when the passages don't support an
answer.

Modules:
  normalize  — Uzbek Cyrillic/Latin + apostrophe-variant search keys
  embeddings — replaceable embedding interface (none / local hashing / OpenAI)
  ingest     — JSONL validation + idempotent, versioned import
  retrieval  — PostgreSQL full-text retrieval (+ optional vector rerank)
  citations  — map verified quotes to exact pages via source_segments
  qa         — grounded answer pipeline with abstention and excerpt limits
"""

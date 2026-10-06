"""Retrieve passages of one edition from PostgreSQL.

Primary signal: PostgreSQL full-text search over `search_text` (the
script/apostrophe-normalised key) with prefix matching on stemmed query terms,
so "tashvishlarni" / "ташвишга" both reach "ташвиш", scored by IDF-weighted
term coverage (see `_fts`). Candidate selection uses the GIN index
ix_book_chunks_search_fts. No extension (pgvector / pg_trgm) is required.

Optional second signal: if an embedding provider is configured and the
edition's chunks carry vectors from that same model, a cosine ranking re-ranks
the full-text candidates (reciprocal-rank fusion). Swapping to pgvector later
only changes `_vector_ranking`.

Contents pages and publication/advertising metadata are never story evidence.
Publication details belong to the catalogue route.
"""

import math
import re
from dataclasses import dataclass

from sqlalchemy import select, text

from bot.models import BookChunk, BookEdition
from bot.rag.embeddings import EmbeddingProvider, NoEmbeddings, cosine
from bot.rag.normalize import query_terms
from bot.rag.scope import constrain

_EXCLUDED_TYPES = ("contents", "front_matter", "front_or_back_matter", "frontmatter",
                   "backmatter", "colophon", "advertisement", "advertisements", "publisher")
_RRF_K = 60
_MAX_TERMS = 10
# A passage must cover at least this share of the question's term weight.
MIN_COVERAGE = 0.5


@dataclass
class Passage:
    chunk_id: str
    text: str
    content_type: str
    page_map: list
    source_segments: list
    pdf_page_start: int
    pdf_page_end: int
    score: float


def build_tsquery(question: str) -> str:
    """OR of prefix terms; terms are [a-z0-9] only, so the string is safe."""
    return " | ".join(f"{t}:*" for t in query_terms(question)[:_MAX_TERMS])


async def enabled_editions(session_factory) -> list[BookEdition]:
    async with session_factory() as session:
        return list(
            await session.scalars(
                select(BookEdition).where(BookEdition.enabled.is_(True)).order_by(BookEdition.catalog_title)
            )
        )


async def get_edition(session_factory, edition_key: str) -> BookEdition | None:
    async with session_factory() as session:
        return await session.get(BookEdition, edition_key)


async def context_passages(session_factory, edition_key: str, chunk_ids: list[str]) -> list[Passage]:
    """Reload prior evidence from the current edition, never from another book.

    Only IDs live in the conversation. Text is read fresh, so changed/deleted
    chunks cannot survive as stale evidence in a conversation.
    """
    ids = list(dict.fromkeys(x for x in chunk_ids if isinstance(x, str)))[:3]
    if not ids:
        return []
    async with session_factory() as session:
        rows = (await session.scalars(select(BookChunk).where(
            BookChunk.edition_key == edition_key,
            BookChunk.chunk_id.in_(ids),
            BookChunk.content_type.notin_(_EXCLUDED_TYPES),
        ))).all()
    by_id = {r.chunk_id: r for r in rows}
    return [Passage(r.chunk_id, r.text, r.content_type, r.page_map, r.source_segments,
                    r.pdf_page_start, r.pdf_page_end, 0.0)
            for key in ids if (r := by_id.get(key)) is not None]


async def _fts(
    session_factory, edition_key: str, question: str, limit: int, ignore: frozenset[str] = frozenset(),
    page_bounds: tuple[int, int] | None = None
) -> list[Passage]:
    """Weighted-coverage full-text search.

    Each query term gets an IDF weight from its document frequency in this
    edition. A passage's score is the weight of the terms it contains; it must
    cover >= MIN_COVERAGE of the question's total weight. Terms that never occur
    in the book still count toward the total (capped at the strongest present
    term's weight), so a question about something the book doesn't discuss is
    not satisfied by one incidental common word. Ties are broken by
    PostgreSQL's cover-density rank normalised by term proximity.
    """
    terms = [t for t in query_terms(question) if t not in ignore][:_MAX_TERMS]
    if not terms:
        return []
    params: dict = {"edition": edition_key, "excluded": list(_EXCLUDED_TYPES)}
    flags = []
    for i, t in enumerate(terms):
        params[f"t{i}"] = f"{t}:*"
        flags.append(f"to_tsvector('simple', search_text) @@ to_tsquery('simple', :t{i})")
    params["q"] = " | ".join(f"{t}:*" for t in terms)
    scope = "edition_key = :edition AND content_type <> ALL(:excluded)"

    if page_bounds is not None:
        scope += " AND pdf_page_end >= :page_start AND pdf_page_start <= :page_end"
        params.update(page_start=page_bounds[0], page_end=page_bounds[1])

    df_sql = text(
        "SELECT count(*) AS n, "
        + ", ".join(f"count(*) FILTER (WHERE {f}) AS d{i}" for i, f in enumerate(flags))
        + f" FROM book_chunks WHERE {scope}"
    )
    cand_sql = text(
        "SELECT chunk_id, text, content_type, page_map, source_segments, "
        "pdf_page_start, pdf_page_end, "
        + ", ".join(f"({f}) AS m{i}" for i, f in enumerate(flags))
        # normalization 4 = divide by mean harmonic distance between matches:
        # rewards passages where the question's terms occur close together.
        + ", ts_rank_cd(to_tsvector('simple', search_text), to_tsquery('simple', :q), 4) AS r "
        f"FROM book_chunks WHERE {scope} "
        "AND to_tsvector('simple', search_text) @@ to_tsquery('simple', :q)"
    )
    async with session_factory() as session:
        dfrow = (await session.execute(df_sql, params)).one()
        rows = (await session.execute(cand_sql, params)).all()

    n = dfrow.n or 0
    dfs = [getattr(dfrow, f"d{i}") for i in range(len(terms))]
    present = [math.log((n + 1) / (d + 0.5)) for d in dfs if d]
    if not present:
        return []
    cap = max(present)
    weights = [math.log((n + 1) / (d + 0.5)) if d else cap for d in dfs]
    total = sum(weights)

    scored, backoff = [], []
    known_weight = sum(w for w, d in zip(weights, dfs) if d)
    for r in rows:
        covered = sum(w for i, w in enumerate(weights) if getattr(r, f"m{i}"))
        if covered / total >= MIN_COVERAGE:
            scored.append((covered, float(r.r), r))
        elif (sum(bool(getattr(r, f"m{i}")) for i in range(len(terms))) >= 2
              and sum(bool(d) for d in dfs) >= len(terms) * 0.6
              and covered / known_weight >= 0.5):
            # Topic backoff: at least two independent anchors and most query
            # vocabulary must exist in this book. It cannot admit a single
            # generic match for an otherwise unknown subject.
            backoff.append((covered, float(r.r), r))
    if not scored:
        scored = backoff
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [
        Passage(r.chunk_id, r.text, r.content_type, r.page_map, r.source_segments,
                r.pdf_page_start, r.pdf_page_end, covered)
        for covered, _, r in scored[:limit]
    ]


async def _vector_ranking(session_factory, edition_key: str, provider: EmbeddingProvider, question: str, limit: int):
    [qvec] = await provider.embed([question])
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(BookChunk).where(
                    BookChunk.edition_key == edition_key,
                    BookChunk.embedding_model == provider.name,
                    BookChunk.content_type.notin_(_EXCLUDED_TYPES),
                )
            )
        ).scalars().all()
    scored = sorted(((cosine(qvec, list(r.embedding)), r) for r in rows if r.embedding), key=lambda x: -x[0])
    return [
        Passage(r.chunk_id, r.text, r.content_type, r.page_map, r.source_segments,
                r.pdf_page_start, r.pdf_page_end, s)
        for s, r in scored[:limit]
    ]


async def retrieve(
    session_factory,
    edition_key: str,
    question: str,
    *,
    k: int = 5,
    provider: EmbeddingProvider | None = None,
    ignore_terms: frozenset[str] = frozenset(),
    page_bounds: tuple[int, int] | None = None,
) -> list[Passage]:
    """Top-k passages for a question within one edition (may be empty).

    `ignore_terms` (search-key form) are dropped from the query — used for the
    book's own title words, which name the book rather than the topic."""
    provider = provider or NoEmbeddings()
    lexical = constrain(await _fts(session_factory, edition_key, question, k * 4, ignore_terms, page_bounds), page_bounds)
    # Explicit compound topic words are a user-supplied search phrase, not a
    # model paraphrase. Preserve them when other conversational terms dominate.
    for left, right in re.findall(r"\b([^\W\d_]{3,})[-‑]([^\W\d_]{3,})\b", question)[:2]:
        anchors = query_terms(left + " " + right)
        if len(anchors) == 2 and not any(t in ignore_terms for t in anchors):
            compound = constrain(await _fts(session_factory, edition_key, left + " " + right,
                                            k * 4, ignore_terms, page_bounds), page_bounds)
            lexical = merge_rankings(lexical, compound, k=k * 4)
    if not provider.name:
        return lexical[:k]

    vector = await _vector_ranking(session_factory, edition_key, provider, question, k * 4)
    # Reciprocal-rank fusion over the LEXICAL candidates only: vectors re-rank,
    # they never admit a passage by themselves. Cosine always returns
    # *something*, so letting it add passages would make "nothing in the book
    # matches" impossible to detect and kill abstention.
    fused: dict[str, tuple[float, Passage]] = {}
    for rank, p in enumerate(lexical):
        fused[p.chunk_id] = (1 / (_RRF_K + rank), p)
    for rank, p in enumerate(vector):
        if p.chunk_id in fused:
            s, kept = fused[p.chunk_id]
            fused[p.chunk_id] = (s + 1 / (_RRF_K + rank), kept)
    ranked = sorted(fused.values(), key=lambda x: -x[0])
    return [p for _, p in ranked[:k]]


def merge_rankings(*rankings: list[Passage], k: int = 5) -> list[Passage]:
    """Equal-weight reciprocal-rank fusion; neither query can replace the other."""
    fused = {}
    for ranking in rankings:
        seen = set()
        for rank, passage in enumerate(ranking):
            if passage.chunk_id in seen:
                continue
            seen.add(passage.chunk_id)
            score, kept = fused.get(passage.chunk_id, (0.0, passage))
            fused[passage.chunk_id] = (score + 1 / (_RRF_K + rank + 1), kept)
    return [p for _, p in sorted(fused.values(), key=lambda value: -value[0])[:k]]

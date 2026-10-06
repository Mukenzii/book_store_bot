"""Validate a book's chunk JSONL and import it idempotently, with versioning.

Stable IDs come from an edition manifest (scripts/rag_editions/*.json); the
converter's book_id/edition_id are treated as illustrative and are only checked
for consistency and kept as `source_edition_id`.

Re-import semantics, all inside ONE transaction (readers see the old or the new
edition, never a mix):
  * identical content            -> "unchanged", no writes at all;
  * changed / added / removed    -> those chunks are updated / inserted /
    deleted, `content_version` is bumped, unchanged chunks keep their row,
    version and embedding;
  * a different source PDF hash  -> refused unless allow_source_change, because
    a different PDF under the same edition key is almost certainly a mistake.
Embeddings are only computed for new/changed chunks or when the provider model
differs from the stored one.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, select, update

from bot.models import BookChunk, BookEdition
from bot.rag.embeddings import EmbeddingProvider, NoEmbeddings
from bot.rag.normalize import search_key

SUPPORTED_SCHEMA_MAJOR = "1."


class IngestError(ValueError):
    """The input file or manifest is not safe to import."""


@dataclass(frozen=True)
class EditionManifest:
    edition_key: str
    book_key: str
    catalog_title: str
    source_sha256: str
    input_book_id: str
    input_edition_id: str
    expected_chunk_count: int | None = None
    language: str | None = None

    @classmethod
    def load(cls, path: str | Path) -> "EditionManifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        try:
            return cls(
                edition_key=data["edition_key"],
                book_key=data["book_key"],
                catalog_title=data["catalog_title"],
                source_sha256=data["source_sha256"].lower(),
                input_book_id=data["input_book_id"],
                input_edition_id=data["input_edition_id"],
                expected_chunk_count=data.get("expected_chunk_count"),
                language=data.get("language"),
            )
        except KeyError as exc:
            raise IngestError(f"manifest missing field {exc}") from exc


@dataclass
class ParsedChunk:
    chunk_id: str
    source_chunk_id: str
    seq: int
    content_type: str
    text: str
    text_sha256: str
    pdf_page_start: int
    pdf_page_end: int
    page_map: list
    source_segments: list

    def fingerprint(self) -> list:
        return [self.text_sha256, self.content_type, self.page_map, self.source_segments, self.seq]


@dataclass
class ParsedEdition:
    chunks: list[ParsedChunk]
    file_sha256: str
    content_sha256: str
    source_title: str
    schema_version: str
    page_count: int | None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_chunks(path: str | Path, manifest: EditionManifest) -> ParsedEdition:
    """Parse + validate a chunk JSONL. Raises IngestError on anything unsafe."""
    raw = Path(path).read_bytes()
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise IngestError(f"file is not UTF-8: {exc}") from exc

    chunks: list[ParsedChunk] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    title = schema = ""
    page_count = None
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IngestError(f"line {lineno}: invalid JSON ({exc.msg})") from exc
        where = f"line {lineno}"

        schema = str(rec.get("schema_version", ""))
        if not schema.startswith(SUPPORTED_SCHEMA_MAJOR):
            raise IngestError(f"{where}: unsupported schema_version {schema!r}")
        if rec.get("book_id") != manifest.input_book_id or rec.get("edition_id") != manifest.input_edition_id:
            raise IngestError(f"{where}: book_id/edition_id do not match the manifest")
        if str(rec.get("source_sha256", "")).lower() != manifest.source_sha256:
            raise IngestError(f"{where}: source_sha256 does not match the manifest's PDF hash")

        source_id = rec.get("chunk_id")
        if not source_id or source_id in seen_ids:
            raise IngestError(f"{where}: missing or duplicate chunk_id {source_id!r}")
        seen_ids.add(source_id)
        key = source_id.rsplit(":", 1)[-1]
        if key in seen_keys:
            raise IngestError(f"{where}: duplicate chunk key {key!r}")
        seen_keys.add(key)

        text = rec.get("text")
        if not isinstance(text, str) or not text.strip():
            raise IngestError(f"{where}: empty text")
        text_sha = _sha(text.encode("utf-8"))
        if rec.get("text_sha256") and rec["text_sha256"] != text_sha:
            raise IngestError(f"{where}: text_sha256 does not match the text")

        segments = rec.get("source_segments") or []
        if not segments:
            raise IngestError(f"{where}: no source_segments")
        for seg in segments:
            start, end = seg.get("start_char"), seg.get("end_char")
            if not (isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(text)):
                raise IngestError(f"{where}: source_segment offsets out of range")
            if not isinstance(seg.get("pdf_page"), int):
                raise IngestError(f"{where}: source_segment without pdf_page")

        title = rec.get("title") or title
        page_count = rec.get("source_page_count", page_count)
        chunks.append(
            ParsedChunk(
                chunk_id=key,
                source_chunk_id=source_id,
                seq=len(chunks) + 1,
                content_type=rec.get("content_type") or "body",
                text=text,
                text_sha256=text_sha,
                pdf_page_start=int(rec.get("pdf_page_start") or segments[0]["pdf_page"]),
                pdf_page_end=int(rec.get("pdf_page_end") or segments[-1]["pdf_page"]),
                page_map=rec.get("page_map") or [],
                source_segments=segments,
            )
        )

    if not chunks:
        raise IngestError("no chunks in file")
    if manifest.expected_chunk_count is not None and len(chunks) != manifest.expected_chunk_count:
        raise IngestError(
            f"expected {manifest.expected_chunk_count} chunks, found {len(chunks)}"
        )
    content_sha = _sha(
        json.dumps(
            [[c.chunk_id, *c.fingerprint()] for c in chunks], ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
    )
    return ParsedEdition(chunks, _sha(raw), content_sha, title, schema, page_count)


@dataclass
class ImportReport:
    edition_key: str
    status: str  # created | updated | unchanged
    content_version: int
    added: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0
    embedded: int = 0
    enabled: bool = False
    dry_run: bool = False
    notes: list[str] = field(default_factory=list)


async def import_edition(
    manifest: EditionManifest,
    parsed: ParsedEdition,
    session_factory,
    *,
    provider: EmbeddingProvider | None = None,
    enable: bool | None = None,
    allow_source_change: bool = False,
    dry_run: bool = False,
) -> ImportReport:
    provider = provider or NoEmbeddings()
    incoming = {c.chunk_id: c for c in parsed.chunks}

    async with session_factory() as session:
        edition = await session.get(BookEdition, manifest.edition_key)
        if edition and edition.source_sha256 != manifest.source_sha256 and not allow_source_change:
            raise IngestError(
                f"edition {manifest.edition_key} was imported from a different PDF "
                f"({edition.source_sha256[:12]}…); refusing without allow_source_change"
            )
        rows = (
            await session.scalars(select(BookChunk).where(BookChunk.edition_key == manifest.edition_key))
        ).all()
        existing = {r.chunk_id: r for r in rows}

    added = [c for k, c in incoming.items() if k not in existing]
    removed = [k for k in existing if k not in incoming]
    changed = [
        c
        for k, c in incoming.items()
        if k in existing
        and [existing[k].text_sha256, existing[k].content_type, existing[k].page_map,
             existing[k].source_segments, existing[k].seq] != c.fingerprint()
    ]
    changed_ids = {c.chunk_id for c in changed}
    content_changed = bool(added or changed or removed) or (
        edition is not None and edition.content_sha256 != parsed.content_sha256
    )
    version = 1 if edition is None else edition.content_version + (1 if content_changed else 0)

    # Which chunks need a (new) vector from the configured provider.
    to_embed: list[ParsedChunk] = []
    if provider.name:
        for k, c in incoming.items():
            row = existing.get(k)
            if row is None or k in changed_ids or row.embedding_model != provider.name:
                to_embed.append(c)

    new_enabled = enable if enable is not None else (edition.enabled if edition else False)
    # An allowed PDF change with identical chunks still has to be recorded —
    # the stored source hash is the provenance of every answer.
    source_changed = edition is not None and edition.source_sha256 != manifest.source_sha256
    report = ImportReport(
        edition_key=manifest.edition_key,
        status="created" if edition is None else (
            "updated" if content_changed or source_changed else "unchanged"
        ),
        content_version=version,
        added=len(added),
        changed=len(changed),
        removed=len(removed),
        unchanged=len(incoming) - len(added) - len(changed),
        embedded=len(to_embed),
        enabled=new_enabled,
        dry_run=dry_run,
    )
    nothing_to_write = (
        edition is not None
        and not content_changed
        and not source_changed
        and not to_embed
        and new_enabled == edition.enabled
    )
    if dry_run or nothing_to_write:
        return report

    vectors: dict[str, list[float]] = {}
    if to_embed:
        embs = await provider.embed([c.text for c in to_embed])
        vectors = {c.chunk_id: v for c, v in zip(to_embed, embs)}

    async with session_factory() as session:
        async with session.begin():
            ed = await session.get(BookEdition, manifest.edition_key)
            if ed is None:
                ed = BookEdition(edition_key=manifest.edition_key, imported_at=func.now())
                session.add(ed)
            ed.book_key = manifest.book_key
            ed.catalog_title = manifest.catalog_title
            ed.source_title = parsed.source_title
            ed.language = manifest.language
            ed.source_edition_id = manifest.input_edition_id
            ed.source_sha256 = manifest.source_sha256
            ed.content_sha256 = parsed.content_sha256
            ed.content_version = version
            ed.schema_version = parsed.schema_version
            ed.chunk_count = len(incoming)
            ed.page_count = parsed.page_count
            ed.enabled = new_enabled
            ed.updated_at = func.now()

            if removed:
                await session.execute(
                    delete(BookChunk).where(
                        BookChunk.edition_key == manifest.edition_key, BookChunk.chunk_id.in_(removed)
                    )
                )
            for c in added:
                session.add(_row(manifest.edition_key, c, version, vectors.get(c.chunk_id), provider.name))
            for c in changed:
                values = _values(c, version)
                values["embedding"] = vectors.get(c.chunk_id)
                values["embedding_model"] = (provider.name or None) if c.chunk_id in vectors else None
                await session.execute(
                    update(BookChunk)
                    .where(BookChunk.edition_key == manifest.edition_key, BookChunk.chunk_id == c.chunk_id)
                    .values(**values)
                )
            # Unchanged chunks that only needed a vector for the current provider.
            for cid, vec in vectors.items():
                if cid in existing and cid not in changed_ids:
                    await session.execute(
                        update(BookChunk)
                        .where(BookChunk.edition_key == manifest.edition_key, BookChunk.chunk_id == cid)
                        .values(embedding=vec, embedding_model=provider.name)
                    )
    return report


def _values(c: ParsedChunk, version: int) -> dict:
    return {
        "source_chunk_id": c.source_chunk_id,
        "seq": c.seq,
        "content_type": c.content_type,
        "text": c.text,
        "search_text": search_key(c.text),
        "text_sha256": c.text_sha256,
        "pdf_page_start": c.pdf_page_start,
        "pdf_page_end": c.pdf_page_end,
        "page_map": c.page_map,
        "source_segments": c.source_segments,
        "content_version": version,
    }


def _row(edition_key: str, c: ParsedChunk, version: int, vec, model: str) -> BookChunk:
    return BookChunk(
        edition_key=edition_key,
        chunk_id=c.chunk_id,
        embedding=vec,
        embedding_model=(model or None) if vec is not None else None,
        **_values(c, version),
    )

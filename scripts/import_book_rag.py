"""Import one book edition's chunk JSONL for book-content Q&A (RAG).

The full-book JSONL is NOT kept in the repo — pass its path. Stable IDs come
from the edition manifest in scripts/rag_editions/.

    # validate + show what would change, no writes
    python -m scripts.import_book_rag \\
        --manifest scripts/rag_editions/qulogim_senda_qizim.json \\
        --chunks /path/to/qulogim_senda_qizim.full.chunks.jsonl --dry-run

    # write (asks for --yes after printing the target database)
    python -m scripts.import_book_rag --manifest ... --chunks ... --yes [--enable]

Options:
  --embeddings none|hashing|openai   vectors for hybrid retrieval (default none)
  --allow-paid                       required for --embeddings openai
  --enable / --disable               serve answers from this edition
  --allow-source-change              accept a different PDF hash for the edition

Re-running with the same file is a no-op ("unchanged"). Only changed chunks are
rewritten; the whole update is one transaction.
"""

import argparse
import asyncio
import re
import sys

from sqlalchemy import select, text

from bot.config import settings
from bot.database import engine, init_db, session_factory
from bot.models import Book
from bot.rag.embeddings import PaidEmbeddingsNotAllowed, get_provider
from bot.rag.ingest import EditionManifest, IngestError, import_edition, parse_chunks


def _title_key(s: str) -> str:
    return re.sub(r"[^\w]", "", (s or "").lower().replace("‘", "").replace("’", "").replace("'", ""))


async def _catalog_has(title: str) -> bool:
    async with session_factory() as session:
        titles = (await session.scalars(select(Book.title))).all()
    return any(_title_key(t) == _title_key(title) for t in titles)


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--chunks", required=True)
    ap.add_argument("--embeddings", default="none", choices=["none", "hashing", "openai"])
    ap.add_argument("--allow-paid", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="confirm writing to the printed database")
    ap.add_argument("--allow-source-change", action="store_true")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--enable", dest="enable", action="store_true", default=None)
    grp.add_argument("--disable", dest="enable", action="store_false")
    args = ap.parse_args(argv)

    try:
        manifest = EditionManifest.load(args.manifest)
        parsed = parse_chunks(args.chunks, manifest)
    except IngestError as exc:
        print(f"REJECTED: {exc}")
        return 2
    print(
        f"Validated {len(parsed.chunks)} chunks · schema {parsed.schema_version} · "
        f"file sha256 {parsed.file_sha256[:12]}… · content sha256 {parsed.content_sha256[:12]}…"
    )
    print(f"Edition {manifest.edition_key} ← «{parsed.source_title}»")
    print(f"Target database: {settings.db_host}:{settings.db_port}/{settings.db_name}")

    if not args.dry_run and not args.yes:
        print("Not writing: re-run with --yes to confirm this database (or --dry-run).")
        return 1

    client = None
    if args.embeddings == "openai":
        from bot.ai import _get_client

        client = _get_client()
    try:
        provider = get_provider(
            args.embeddings, allow_paid=args.allow_paid, client=client,
            model=settings.rag_openai_embedding_model,
        )
    except PaidEmbeddingsNotAllowed as exc:
        print(f"REFUSED: {exc}")
        return 2

    if args.dry_run:
        # A dry run must not write anything — not even schema DDL.
        async with session_factory() as session:
            exists = await session.scalar(text("SELECT to_regclass('public.book_chunks')"))
        if exists is None:
            print(f"DRY RUN — tables not created yet: all {len(parsed.chunks)} chunks would be added.")
            await engine.dispose()
            return 0
    else:
        await init_db()  # tables + FTS index (idempotent)
    if not await _catalog_has(manifest.catalog_title):
        print(f"WARNING: catalogue has no book titled «{manifest.catalog_title}» in this database.")

    try:
        report = await import_edition(
            manifest, parsed, session_factory,
            provider=provider, enable=args.enable,
            allow_source_change=args.allow_source_change, dry_run=args.dry_run,
        )
    except IngestError as exc:
        print(f"REJECTED: {exc}")
        return 2
    finally:
        await engine.dispose()

    tag = "DRY RUN — " if report.dry_run else ""
    print(
        f"{tag}{report.status.upper()} · version {report.content_version} · "
        f"+{report.added} ~{report.changed} -{report.removed} ={report.unchanged} · "
        f"embedded {report.embedded} · enabled={report.enabled}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))

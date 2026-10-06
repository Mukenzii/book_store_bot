"""PostgreSQL integration tests: importer reruns/updates, retrieval, end-to-end
citations, and store/catalogue regressions.

Runs ONLY against a dedicated throwaway database whose name ends in "_ragtest"
(created if missing); every test drops and recreates all tables there. Skips if
no PostgreSQL is reachable.
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import tests  # noqa: F401 — safe env first
import bot.database as database
import bot.repository as repository
from bot.config import settings
from bot.models import Base, BookChunk, BookEdition, Store
from bot.rag import qa, retrieval
from bot.rag.embeddings import HashingEmbeddings
from bot.rag.ingest import EditionManifest, IngestError, import_edition, parse_chunks
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from tests.fixtures import synthetic_book as fx
from tests.test_rag_qa import FakeLLM

SF = None  # session factory bound to the test DB


def setUpModule():
    global SF
    if not settings.db_name.endswith("_ragtest"):
        raise unittest.SkipTest(f"refusing to run DB tests against {settings.db_name!r}")

    async def ensure_db():
        import asyncpg

        conn = await asyncpg.connect(
            user=settings.db_user, password=settings.db_password,
            host=settings.db_host, port=settings.db_port, database="postgres", timeout=5,
        )
        try:
            if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", settings.db_name):
                await conn.execute(f'CREATE DATABASE "{settings.db_name}"')
        finally:
            await conn.close()

    try:
        asyncio.run(ensure_db())
    except Exception as exc:  # noqa: BLE001
        raise unittest.SkipTest(f"PostgreSQL not reachable: {exc}")

    # NullPool: no connection outlives a test's event loop.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    SF = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    database.engine = engine
    database.session_factory = SF
    repository.session_factory = SF


class DBTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with database.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text(database.RAG_FTS_INDEX_SQL))
            await conn.execute(text("ALTER TABLE stores ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false"))
        self.tmp = Path(tempfile.mkdtemp())

    def manifest(self, **changes) -> EditionManifest:
        return EditionManifest.load(fx.write_manifest(self.tmp / f"m{len(changes)}.json", **changes))

    def parsed(self, manifest, records=None):
        path = fx.write_jsonl(self.tmp / "b.jsonl", records if records is not None else fx.make_records())
        return parse_chunks(path, manifest)

    async def do_import(self, manifest=None, records=None, **kw):
        manifest = manifest or self.manifest()
        return await import_edition(manifest, self.parsed(manifest, records), SF, **kw)

    async def chunks(self) -> dict[str, BookChunk]:
        async with SF() as s:
            rows = (await s.scalars(select(BookChunk).where(BookChunk.edition_key == fx.MANIFEST["edition_key"]))).all()
        return {r.chunk_id: r for r in rows}

    async def edition(self) -> BookEdition:
        async with SF() as s:
            return await s.get(BookEdition, fx.MANIFEST["edition_key"])


class ImporterTest(DBTestCase):
    async def test_first_import(self):
        rep = await self.do_import()
        self.assertEqual((rep.status, rep.content_version, rep.added), ("created", 1, 5))
        ed = await self.edition()
        self.assertEqual(ed.chunk_count, 5)
        self.assertFalse(ed.enabled)  # serving is opt-in
        rows = await self.chunks()
        self.assertEqual(rows["c00003"].text, fx.make_records()[2]["text"])  # original kept verbatim
        self.assertIn("tashvish", rows["c00003"].search_text)

    async def test_rerun_same_file_is_a_noop(self):
        await self.do_import()
        before_ed = await self.edition()
        before_ids = {k: r.id for k, r in (await self.chunks()).items()}
        rep = await self.do_import()
        self.assertEqual((rep.status, rep.content_version, rep.added, rep.changed, rep.removed),
                         ("unchanged", 1, 0, 0, 0))
        after_ed = await self.edition()
        self.assertEqual(before_ed.updated_at, after_ed.updated_at)  # no write happened
        self.assertEqual(before_ids, {k: r.id for k, r in (await self.chunks()).items()})

    async def test_changed_chunk_bumps_version_and_only_rewrites_that_chunk(self):
        await self.do_import()
        keep_id = (await self.chunks())["c00003"].id
        rep = await self.do_import(records=fx.make_records({"c00004": "Яхши дўст ҳамма вақт ростини айтади."}))
        self.assertEqual((rep.status, rep.content_version, rep.changed, rep.unchanged), ("updated", 2, 1, 4))
        rows = await self.chunks()
        self.assertEqual(rows["c00004"].content_version, 2)
        self.assertEqual(rows["c00003"].content_version, 1)
        self.assertEqual(rows["c00003"].id, keep_id)
        self.assertIn("ростини айтади", rows["c00004"].text)

    async def test_removed_chunk_is_deleted(self):
        await self.do_import()
        m = self.manifest(expected_chunk_count=4)
        rep = await self.do_import(manifest=m, records=fx.make_records(drop={"c00005"}))
        self.assertEqual((rep.removed, rep.content_version), (1, 2))
        self.assertNotIn("c00005", await self.chunks())

    async def test_different_source_pdf_is_refused_unless_allowed(self):
        await self.do_import()
        other = "c" * 64
        recs = fx.make_records()
        for r in recs:
            r["source_sha256"] = other
        m = self.manifest(source_sha256=other)
        with self.assertRaises(IngestError):
            await self.do_import(manifest=m, records=recs)
        rep = await self.do_import(manifest=m, records=recs, allow_source_change=True)
        self.assertEqual((await self.edition()).source_sha256, other)  # provenance recorded
        # Same chunks: metadata update only, content version unchanged.
        self.assertEqual((rep.status, rep.content_version, rep.changed), ("updated", 1, 0))

    async def test_dry_run_writes_nothing(self):
        rep = await self.do_import(dry_run=True)
        self.assertEqual((rep.status, rep.added, rep.dry_run), ("created", 5, True))
        self.assertIsNone(await self.edition())
        self.assertEqual(await self.chunks(), {})

    async def test_enable_flag_is_kept_on_rerun(self):
        await self.do_import(enable=True)
        await self.do_import()
        self.assertTrue((await self.edition()).enabled)
        await self.do_import(enable=False)
        self.assertFalse((await self.edition()).enabled)

    async def test_embeddings_only_where_needed(self):
        prov = HashingEmbeddings()
        self.assertEqual((await self.do_import(provider=prov)).embedded, 5)
        self.assertEqual((await self.do_import(provider=prov)).embedded, 0)
        rep = await self.do_import(provider=prov, records=fx.make_records({"c00004": "Янги матн дўстлик ҳақида."}))
        self.assertEqual(rep.embedded, 1)
        swapped = HashingEmbeddings(dim=128)  # different model name -> re-embed all
        rep = await self.do_import(provider=swapped, records=fx.make_records({"c00004": "Янги матн дўстлик ҳақида."}))
        self.assertEqual((rep.status, rep.embedded), ("unchanged", 5))
        self.assertEqual({r.embedding_model for r in (await self.chunks()).values()}, {swapped.name})


class RetrievalTest(DBTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.do_import(enable=True, provider=HashingEmbeddings())

    async def top(self, q, provider=None):
        res = await retrieval.retrieve(SF, fx.MANIFEST["edition_key"], q, k=3, provider=provider)
        return [p.chunk_id for p in res]

    async def test_cyrillic_and_latin_queries_find_the_same_passage(self):
        for q in (
            "Ташвиш билан қайғунинг фарқи нима?",
            "Tashvish bilan qayg'uning farqi nima?",
            "Tashvish bilan qaygʻuning farqi nima?",
            "tashvish va kaygu farki",            # no Uzbek letters
            "Ташвиш ва кайгу",                     # Cyrillic without қ/ғ keys
        ):
            with self.subTest(q=q):
                self.assertEqual((await self.top(q))[:1], ["c00003"])

    async def test_book_title_words_do_not_steer_retrieval(self):
        # "Синов китоби" also occurs in the front matter (c00001); with the
        # title terms ignored the topic decides.
        res = await retrieval.retrieve(SF, fx.MANIFEST["edition_key"], "«Синов китоби»да ташвиш ва қайғу",
                                       k=3, ignore_terms=frozenset({"sinov"}))
        self.assertEqual([p.chunk_id for p in res][:1], ["c00003"])
        self.assertNotIn("c00001", [p.chunk_id for p in res])

    async def test_inflected_query(self):
        self.assertEqual((await self.top("tashvishlarni qanday yengish kerak"))[:1], ["c00003"])

    async def test_table_of_contents_is_never_evidence(self):
        self.assertNotIn("c00002", await self.top("Мундарижа ташвиш қайғу"))

    async def test_publication_metadata_is_not_retrieved_or_carried_as_story_context(self):
        await self.do_import(records=fx.make_records({'c00001':'ISBN raqami 978-123-456. Nashriyot manzili.'}))
        self.assertEqual(await self.top('ISBN raqami'), [])
        self.assertEqual(await retrieval.context_passages(SF, fx.MANIFEST['edition_key'], ['c00001']), [])

    async def test_unknown_subject_cannot_enter_via_two_incidental_book_words(self):
        self.assertEqual(await self.top('tashvish qaygu kvant mikrosxema neytron proton algoritm'), [])

    async def test_unrelated_question_returns_nothing(self):
        self.assertEqual(await self.top("kvant fizikasi va qora tuynuklar"), [])

    async def test_hybrid_rerank_keeps_lexical_evidence(self):
        self.assertEqual((await self.top("Ҳақиқий дўст", provider=HashingEmbeddings()))[:1], ["c00004"])
        self.assertEqual(await self.top("kvant fizikasi", provider=HashingEmbeddings()), [])

    async def test_editions_are_isolated(self):
        other = self.manifest(edition_key="test.other", book_key="test.other", catalog_title="Boshqa")
        await self.do_import(manifest=other, records=fx.make_records({"c00004": "Ноёб сўз зумраддарахт фақат бу нашрда."}))
        self.assertEqual(await self.top("зумраддарахт"), [])
        res = await retrieval.retrieve(SF, "test.other", "zumraddaraxt", k=3)
        self.assertEqual([p.chunk_id for p in res], ["c00004"])

    async def test_only_enabled_editions_are_listed(self):
        other = self.manifest(edition_key="test.other", book_key="test.other", catalog_title="Boshqa")
        await self.do_import(manifest=other)  # not enabled
        self.assertEqual([e.edition_key for e in await retrieval.enabled_editions(SF)], [fx.MANIFEST["edition_key"]])

    async def test_context_evidence_is_current_and_scoped_to_edition(self):
        key = fx.MANIFEST["edition_key"]
        found = await retrieval.context_passages(SF, key, ["c00003", "c00002"])
        self.assertEqual([p.chunk_id for p in found], ["c00003"])
        self.assertEqual(await retrieval.context_passages(SF, "missing.edition", ["c00003"]), [])
        async with SF() as session:
            await session.execute(text("DELETE FROM book_chunks WHERE edition_key=:edition AND chunk_id='c00003'"), {"edition": key})
            await session.commit()
        self.assertEqual(await retrieval.context_passages(SF, key, ["c00003"]), [])

    async def test_end_to_end_answer_with_page_citations(self):
        llm = FakeLLM({"supported": True, "answer": "Kitobda farq tushuntiriladi.",
                       "citations": [{"passage": "P1", "quote": "Қайғу эса ўтиб кетган мусибат учун сиқилишдир."}]})
        res = await qa.answer_book_question(fx.MANIFEST["edition_key"], "Qayg'u nima?", 1,
                                            session_factory=SF, llm=llm, limiter=qa.DailyLimiter(10))
        self.assertEqual(res.status, "answered")
        self.assertEqual(res.citations[0].page_label(), "20-bet")

        llm = FakeLLM({"supported": True, "answer": "Do'st og'ir kunda yoningda bo'ladi.",
                       "citations": [{"passage": "P1", "quote": "Ҳақиқий дўст оғир кунда ёнингда туради"}]})
        res = await qa.answer_book_question(fx.MANIFEST["edition_key"], "Haqiqiy do'st qanday bo'ladi?", 1,
                                            session_factory=SF, llm=llm, limiter=qa.DailyLimiter(10))
        self.assertEqual(res.citations[0].page_label(), "PDF 45-sahifa")

    async def test_unsupported_question_abstains_without_model_call(self):
        llm = FakeLLM({"supported": True, "answer": "x", "citations": []})
        res = await qa.answer_book_question(fx.MANIFEST["edition_key"], "Kvant fizikasi nima?", 1,
                                            session_factory=SF, llm=llm, limiter=qa.DailyLimiter(10))
        self.assertEqual(res.status, "abstained")
        self.assertEqual(llm.calls, [])


class StoreRegressionTest(DBTestCase):
    """Book Q&A must not disturb stores / store availability behaviour."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with SF() as s:
            s.add_all([
                Store(name="Real do‘kon", latitude=41.31, longitude=69.24, phone="+998901112233, +998977654321"),
                Store(name="Uzoq do‘kon", latitude=40.0, longitude=71.0, phone="+998900000000"),
            ])
            await s.commit()
        self.test_store = await repository.get_or_create_test_store()

    async def test_test_store_hidden_from_customers_and_admin_list(self):
        near = await repository.find_nearest_stores(41.31, 69.24, 10)
        self.assertNotIn(self.test_store.id, [s.id for s in near])
        self.assertEqual(await repository.count_stores(), 2)
        self.assertNotIn(self.test_store.id, [s.id for s in await repository.list_stores(10, 0)])

    async def test_owner_phone_matching(self):
        owned = await repository.stores_owned_by_phone("977654321")
        self.assertEqual([s.name for s in owned], ["Real do‘kon"])

    async def test_store_books_are_deduplicated_and_listed(self):
        store = (await repository.list_stores(1, 0))[0]
        a = await repository.add_store_book(store.id, book_id=None, title="Qulog‘im senda, qizim!", author=None, added_by=1)
        b = await repository.add_store_book(store.id, book_id=None, title="Qulog'im senda qizim", author=None, added_by=1)
        self.assertIsNotNone(a)
        self.assertIsNone(b)  # same title, different apostrophe -> duplicate
        self.assertEqual([x.title for x in await repository.list_store_books(store.id)], ["Qulog‘im senda, qizim!"])


if __name__ == "__main__":
    unittest.main()

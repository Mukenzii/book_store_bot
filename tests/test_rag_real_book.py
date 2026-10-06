"""Opt-in checks against the REAL book file, which never enters the repo.

Set RAG_BOOK_JSONL to the full chunks file (e.g. mounted read-only). Without
it, these tests are skipped. Uses the committed manifest's stable IDs.
"""

import os
import unittest
from pathlib import Path

import tests  # noqa: F401 — safe env first
from bot.rag.citations import resolve
from bot.rag.ingest import EditionManifest, parse_chunks
from bot.rag.normalize import query_terms, search_key

MANIFEST = Path(__file__).resolve().parents[1] / "scripts" / "rag_editions" / "qulogim_senda_qizim.json"
BOOK = os.environ.get("RAG_BOOK_JSONL")


@unittest.skipUnless(BOOK and Path(BOOK).is_file(), "set RAG_BOOK_JSONL to run real-book checks")
class RealBookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = EditionManifest.load(MANIFEST)
        cls.parsed = parse_chunks(BOOK, cls.manifest)
        cls.by_id = {c.chunk_id: c for c in cls.parsed.chunks}

    def test_full_file_validates(self):
        self.assertEqual(len(self.parsed.chunks), 233)
        self.assertEqual(self.parsed.page_count, 400)

    def test_smoke_question_terms_hit_page_20_passage(self):
        terms = query_terms("Китобда ташвиш билан қайғунинг фарқи қандай тушунтирилган?")
        c = self.by_id["c00012"]
        key = search_key(c.text)
        self.assertTrue(all(t in key for t in ("tashvish", "kaygu")), terms)

    def test_smoke_citations_resolve_to_page_20(self):
        c = self.by_id["c00012"]
        for quote in ("Ташвиш (ҳали содир бўлмаган иш учун безовта бўлиш);",
                      "Қайғу (бўлиб ўтган мусибат учун сиқилиш);"):
            with self.subTest(quote=quote):
                cit = resolve(c.chunk_id, c.text, c.source_segments, quote)
                self.assertIsNotNone(cit)
                self.assertEqual(cit.pdf_pages, [20])
                self.assertEqual(cit.page_label(), "20-bet")

    def test_latin_query_matches_cyrillic_source(self):
        lat = query_terms("Kitobda tashvish bilan qayg'uning farqi qanday?")
        self.assertIn("tashvish", lat)
        self.assertIn("tashvish", search_key(self.by_id["c00012"].text))



@unittest.skipUnless(BOOK and Path(BOOK).is_file(), "set RAG_BOOK_JSONL to run real-book checks")
class RealBookRetrievalTest(unittest.IsolatedAsyncioTestCase):
    """Imports the real book into the throwaway *_ragtest DB and checks that the
    README smoke question reaches the page-20 passage in every script variant,
    and that off-topic questions retrieve nothing."""

    @classmethod
    def setUpClass(cls):
        from tests import test_rag_db

        if test_rag_db.SF is None:
            test_rag_db.setUpModule()  # may raise SkipTest if no PostgreSQL
        cls.db = test_rag_db

    async def test_smoke_question_and_off_topic(self):
        from sqlalchemy import text as sql

        import bot.database as database
        from bot.models import Base
        from bot.rag import retrieval
        from bot.rag.ingest import import_edition

        async with database.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(sql(database.RAG_FTS_INDEX_SQL))
        manifest = EditionManifest.load(MANIFEST)
        await import_edition(manifest, parse_chunks(BOOK, manifest), self.db.SF, enable=True)

        for q in (
            "Китобда ташвиш билан қайғунинг фарқи қандай тушунтирилган?",
            "Kitobda tashvish bilan qayg‘uning farqi qanday tushuntirilgan?",
            "tashvish bilan kaygu farki",
            "ташвиш ва кайгу фарки",
        ):
            with self.subTest(q=q):
                ids = [p.chunk_id for p in await retrieval.retrieve(self.db.SF, manifest.edition_key, q, k=5)]
                self.assertIn("c00012", ids)
        for q in (
            "жисмоний фаоллик, қайғу енгиллатиши, ҳаётий мисоллар",
            "jismoniy faollik qayg‘uni yengillatishi qanday hayotiy misollar bilan tushuntirilgan",
        ):
            with self.subTest(physical_activity=q):
                passages = await retrieval.retrieve(self.db.SF, manifest.edition_key, q, k=5)
                self.assertTrue(passages, "Natural-language question must not be rejected as unsupported")
                self.assertTrue(any(90 <= p.pdf_page_start <= 115 for p in passages))
        for q in ("kvant fizikasi va qora tuynuklar", "futbol jahon chempionati natijalari"):
            with self.subTest(q=q):
                self.assertEqual(await retrieval.retrieve(self.db.SF, manifest.edition_key, q, k=5), [])


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

import tests  # noqa: F401 — safe env first
from bot.rag.ingest import EditionManifest, IngestError, parse_chunks
from tests.fixtures import synthetic_book as fx


class ParseChunksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.manifest = EditionManifest.load(fx.write_manifest(self.tmp / "m.json"))

    def _parse(self, records, manifest=None):
        return parse_chunks(fx.write_jsonl(self.tmp / "b.jsonl", records), manifest or self.manifest)

    def test_valid_file(self):
        parsed = self._parse(fx.make_records())
        self.assertEqual(len(parsed.chunks), 5)
        self.assertEqual([c.chunk_id for c in parsed.chunks], list(fx.CHUNKS))
        self.assertEqual(parsed.chunks[2].source_chunk_id, f"{fx.EDITION_ID}:c00003")

    def test_content_hash_is_stable_and_sensitive(self):
        a = self._parse(fx.make_records()).content_sha256
        b = self._parse(fx.make_records()).content_sha256
        c = self._parse(fx.make_records({"c00004": "Бошқа матн бу ерда, тамомила янги."})).content_sha256
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def _expect_reject(self, records, needle, manifest=None):
        with self.assertRaises(IngestError) as cm:
            self._parse(records, manifest)
        self.assertIn(needle, str(cm.exception))

    def test_rejects_duplicate_chunk_id(self):
        recs = fx.make_records()
        recs[1]["chunk_id"] = recs[0]["chunk_id"]
        self._expect_reject(recs, "duplicate")

    def test_rejects_empty_text(self):
        recs = fx.make_records()
        recs[3]["text"] = "   "
        self._expect_reject(recs, "empty text")

    def test_rejects_text_hash_mismatch(self):
        recs = fx.make_records()
        recs[3]["text"] = recs[3]["text"] + "x"
        self._expect_reject(recs, "text_sha256")

    def test_rejects_wrong_source_pdf(self):
        recs = fx.make_records()
        for r in recs:
            r["source_sha256"] = "b" * 64
        self._expect_reject(recs, "PDF hash")

    def test_rejects_mismatched_edition_ids(self):
        recs = fx.make_records()
        recs[0]["edition_id"] = "someone_else"
        self._expect_reject(recs, "do not match the manifest")

    def test_rejects_bad_offsets(self):
        recs = fx.make_records()
        recs[2]["source_segments"][0]["end_char"] = 10_000
        self._expect_reject(recs, "offsets")

    def test_rejects_wrong_chunk_count(self):
        manifest = EditionManifest.load(fx.write_manifest(self.tmp / "m2.json", expected_chunk_count=233))
        self._expect_reject(fx.make_records(), "expected 233", manifest)

    def test_rejects_non_utf8(self):
        path = self.tmp / "bad.jsonl"
        path.write_bytes("Ташвиш".encode("cp1251"))
        with self.assertRaises(IngestError):
            parse_chunks(path, self.manifest)

    def test_rejects_unknown_schema(self):
        recs = fx.make_records()
        recs[0]["schema_version"] = "2.0"
        self._expect_reject(recs, "schema_version")

    def test_manifest_requires_stable_ids(self):
        path = self.tmp / "m3.json"
        data = dict(fx.MANIFEST)
        del data["edition_key"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(IngestError):
            EditionManifest.load(path)


if __name__ == "__main__":
    unittest.main()

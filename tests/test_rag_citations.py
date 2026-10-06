import unittest

import tests  # noqa: F401 — safe env first
from bot.rag.citations import locate, resolve
from tests.fixtures import synthetic_book as fx


def _chunk(key):
    return next(r for r in fx.make_records() if r["chunk_id"].endswith(key))


class LocateTest(unittest.TestCase):
    def test_exact(self):
        text = "Сабр ҳақида.\n\nТашвиш — ҳали бўлмаган иш."
        start, end = locate(text, "Ташвиш — ҳали бўлмаган иш")
        self.assertEqual(text[start:end], "Ташвиш — ҳали бўлмаган иш")

    def test_whitespace_variation_maps_back_to_original(self):
        text = "Сабр ҳақида.\n\nТашвиш   —\nҳали бўлмаган иш."
        start, end = locate(text, "Ташвиш — ҳали бўлмаган иш")
        self.assertEqual(text[start:end], "Ташвиш   —\nҳали бўлмаган иш")

    def test_rejects_fabricated_and_tiny_quotes(self):
        self.assertIsNone(locate("Ташвиш — ҳали бўлмаган иш.", "Бу китобда йўқ гап"))
        self.assertIsNone(locate("Ташвиш — ҳали бўлмаган иш.", "иш"))

    def test_translated_quote_is_not_accepted(self):
        self.assertIsNone(locate("Ташвиш — ҳали бўлмаган иш.", "Tashvish — hali bo'lmagan ish"))


class ResolveTest(unittest.TestCase):
    def test_cites_page_of_the_quoted_statement_not_the_chunk(self):
        rec = _chunk("c00003")  # spans PDF 19-20
        c = resolve("c00003", rec["text"], rec["source_segments"], "Қайғу эса ўтиб кетган мусибат учун сиқилишдир")
        self.assertEqual(c.pdf_pages, [20])
        self.assertEqual(c.paragraph_ids, ["p0020-para0002"])
        self.assertEqual(c.page_label(), "20-bet")

    def test_quote_on_page_19(self):
        rec = _chunk("c00003")
        c = resolve("c00003", rec["text"], rec["source_segments"], "Сабр ҳақида бир неча оғиз сўз")
        self.assertEqual(c.page_label(), "19-bet")

    def test_span_across_pages_gives_range(self):
        rec = _chunk("c00003")
        quote = "оғиз сўз айтамиз.\n\nТашвиш — ҳали"
        c = resolve("c00003", rec["text"], rec["source_segments"], quote)
        self.assertEqual(c.page_label(), "19–20-betlar")

    def test_missing_printed_page_falls_back_to_pdf_page(self):
        rec = _chunk("c00004")  # printed_page null (folio under artwork)
        c = resolve("c00004", rec["text"], rec["source_segments"], "Ҳақиқий дўст оғир кунда ёнингда туради")
        self.assertEqual(c.page_label(), "PDF 45-sahifa")

    def test_quote_returned_is_original_source_text(self):
        rec = _chunk("c00003")
        c = resolve("c00003", rec["text"], rec["source_segments"], "  «Қайғу эса ўтиб кетган мусибат»  ")
        self.assertEqual(c.quote, "Қайғу эса ўтиб кетган мусибат")


if __name__ == "__main__":
    unittest.main()

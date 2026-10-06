import unittest

import tests  # noqa: F401 — safe env first
from bot.rag.normalize import cyrillic_to_latin, query_terms, search_key, stem


class SearchKeyTest(unittest.TestCase):
    def test_cyrillic_and_latin_titles_match(self):
        self.assertEqual(search_key("Қулоғим сенда, қизим!"), search_key("Qulog‘im senda, qizim!"))

    def test_apostrophe_variants_are_equal(self):
        variants = ["Qulog'im", "Qulog‘im", "Qulog’im", "Qulogʻim", "Qulogʼim", "Qulog`im", "Qulogim"]
        self.assertEqual(len({search_key(v) for v in variants}), 1)

    def test_keyboard_fallbacks(self):
        # қ typed as к, ҳ typed as х
        self.assertEqual(search_key("Қуръон"), search_key("Куръон"))
        self.assertEqual(search_key("ҳадис"), search_key("хадис"))
        self.assertEqual(search_key("ҳадис"), search_key("hadis"))

    def test_digraphs_survive(self):
        self.assertEqual(search_key("ташвиш"), "tashvish")
        self.assertEqual(search_key("чой"), "choy")

    def test_ye_by_position(self):
        self.assertEqual(cyrillic_to_latin("ер"), "yer")
        self.assertEqual(cyrillic_to_latin("келди"), "keldi")

    def test_original_text_is_not_mutated(self):
        original = "Ташвиш — ҳали бўлмаган иш."
        search_key(original)
        self.assertEqual(original, "Ташвиш — ҳали бўлмаган иш.")


class QueryTermsTest(unittest.TestCase):
    def test_same_terms_for_both_scripts(self):
        cyr = query_terms("Китобда ташвиш билан қайғунинг фарқи қандай тушунтирилган?")
        lat = query_terms("Kitobda tashvish bilan qayg'uning farqi qanday tushuntirilgan?")
        self.assertEqual(cyr, lat)
        self.assertIn("tashvish", cyr)
        self.assertIn("kaygu", cyr)

    def test_stopwords_dropped(self):
        self.assertEqual(query_terms("kitobda nima haqida bor?"), [])

    def test_inflected_book_words_are_not_topics(self):
        # Real failure: "китобида" stemmed to "kitobi" and steered retrieval.
        for q in ("Китобида ташвиш ҳақида", "Kitobida tashvish haqida", "asarida tashvish"):
            self.assertEqual(query_terms(q), ["tashvish"], q)
        # a real topic word built on "kitob" survives (stemmed to its root)
        self.assertIn("kitobxon", query_terms("Kitobxonlik odati qachon shakllanadi?"))

    def test_three_letter_roots_survive_case_suffixes(self):
        self.assertEqual(stem('pulning'), 'pul')
        self.assertEqual(stem('pulga'), 'pul')
        self.assertEqual(query_terms('pulning pardaga oʻxshatilishi')[0], 'pul')

    def test_stem_keeps_short_roots(self):
        self.assertEqual(stem("tashvishlarni"), "tashvish")
        self.assertEqual(stem("uyga"), "uyga")  # stem would be < 3 chars


if __name__ == "__main__":
    unittest.main()

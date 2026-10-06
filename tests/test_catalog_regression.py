"""The catalogue assistant must behave exactly as before unless book-content Q&A
is explicitly offered — and even then it only ROUTES content questions."""

import json
import unittest
from types import SimpleNamespace
from unittest import mock

import tests  # noqa: F401 — safe env first
from bot import ai
from bot.models import Book

TITLE = "Qulog‘im senda, qizim!"


def _book():
    return Book(id=7, title=TITLE, author="Abdulloh Abdulmut’iy", genre="tarbiya",
                annotation="Qizlarga nasihatlar.", price="45 000 so'm", in_stock=True)


def _response(content=None, tool=None, args=None):
    calls = [SimpleNamespace(function=SimpleNamespace(name=tool, arguments=json.dumps(args or {})))] if tool else None
    msg = SimpleNamespace(content=content, tool_calls=calls, refusal=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class CatalogAssistantTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self, response, content_books=None):
        create = mock.AsyncMock(return_value=response)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with mock.patch.object(ai, "_get_client", return_value=client), \
             mock.patch("bot.repository.get_setting", mock.AsyncMock(return_value="Falaq Nashr")):
            ans = await ai.answer_question("savol", [_book()], content_books)
        return ans, create.call_args.kwargs

    async def test_default_has_only_store_finder_and_no_content_rule(self):
        ans, kw = await self._run(_response(content="Tavsiya: ..."))
        self.assertEqual([t["function"]["name"] for t in kw["tools"]], ["find_nearest_store"])
        system = kw["messages"][0]["content"]
        self.assertNotIn("KITOB MAZMUNI", system)
        self.assertEqual(ans.text, "Tavsiya: ...")
        self.assertIsNone(ans.book_question)

    async def test_price_never_reaches_the_model(self):
        _, kw = await self._run(_response(content="ok"))
        self.assertNotIn("45 000", kw["messages"][0]["content"])
        _, kw = await self._run(_response(content="ok"), content_books=[TITLE])
        self.assertNotIn("45 000", kw["messages"][0]["content"])

    async def test_content_tool_offered_only_for_enabled_titles(self):
        _, kw = await self._run(_response(content="ok"), content_books=[TITLE])
        tool = next(t for t in kw["tools"] if t["function"]["name"] == "answer_book_content")
        self.assertEqual(tool["function"]["parameters"]["properties"]["book_title"]["enum"], [TITLE])
        self.assertIn("KITOB MAZMUNI", kw["messages"][0]["content"])

    async def test_content_question_is_routed_not_answered(self):
        ans, _ = await self._run(
            _response(tool="answer_book_content", args={"book_title": TITLE, "question": "Tashvish nima?"}),
            content_books=[TITLE],
        )
        self.assertEqual(ans.book_question, (TITLE, "Tashvish nima?"))
        self.assertFalse(ans.find_store)
        self.assertEqual(ans.text, "")

    async def test_unknown_title_from_model_is_ignored(self):
        ans, _ = await self._run(
            _response(content="Katalog javobi", tool="answer_book_content",
                      args={"book_title": "Boshqa kitob", "question": "?"}),
            content_books=[TITLE],
        )
        self.assertIsNone(ans.book_question)
        self.assertEqual(ans.text, "Katalog javobi")

    async def test_where_to_buy_still_uses_store_finder(self):
        ans, _ = await self._run(_response(tool="find_nearest_store"), content_books=[TITLE])
        self.assertTrue(ans.find_store)
        self.assertIsNone(ans.book_question)

    async def test_ai_disabled_without_key(self):
        with mock.patch.object(ai, "_get_client", return_value=None):
            ans = await ai.answer_question("savol", [_book()], [TITLE])
        self.assertFalse(ans.find_store)
        self.assertIsNone(ans.book_question)


if __name__ == "__main__":
    unittest.main()

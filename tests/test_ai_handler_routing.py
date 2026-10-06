"""Chat-handler glue: content Q&A is only offered behind the feature flag, and a
routed content question goes to the grounded pipeline, not the catalogue."""

import unittest
from types import SimpleNamespace
from unittest import mock

import tests  # noqa: F401 — safe env first
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

from bot import ai
from bot.handlers import ai as handler
from bot.rag.qa import QAResult

EDITION = SimpleNamespace(catalog_title="Qulog‘im senda, qizim!", edition_key="falaq.qulogim-senda-qizim.2026-10.uz-cyrl")


def _message(text="savol"):
    return SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=1),
        from_user=SimpleNamespace(id=42),
        bot=SimpleNamespace(send_chat_action=mock.AsyncMock()),
        answer=mock.AsyncMock(),
        answer_photo=mock.AsyncMock(),
        answer_media_group=mock.AsyncMock(),
    )


class HandlerRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self, *, flag_on, answer):
        msg = _message()
        state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=42))
        ask = mock.AsyncMock(return_value=answer)
        qa_call = mock.AsyncMock(return_value=QAResult("answered", "GROUNDED ANSWER"))
        with mock.patch.object(handler.repo, "sample_books", mock.AsyncMock(return_value=[])), \
             mock.patch.object(handler.features, "enabled", return_value=flag_on), \
             mock.patch.object(handler.retrieval, "enabled_editions", mock.AsyncMock(return_value=[EDITION])), \
             mock.patch.object(handler.ai, "answer_question", ask), \
             mock.patch.object(handler.qa, "answer_book_question", qa_call):
            await handler.ask_ai(msg, state)
        return msg, ask, qa_call

    async def test_flag_off_catalogue_unchanged(self):
        msg, ask, qa_call = await self._run(flag_on=False, answer=ai.Answer("Katalog javobi"))
        # the released request: no content books, no history/spoiler/script rules
        self.assertEqual(len(ask.call_args.args), 2)
        self.assertEqual(ask.call_args.kwargs, {})
        qa_call.assert_not_awaited()
        self.assertIn("Katalog javobi", msg.answer.call_args.args[0])

    async def test_flag_off_does_not_refuse_book_content_questions(self):
        # With the flag off a named book's "kitobida…" question is a normal
        # catalogue answer, never the "book text not available" refusal.
        msg, ask, _ = await self._run(flag_on=False, answer=ai.Answer("Izoh bo‘yicha javob"))
        self.assertIn("Izoh bo‘yicha javob", msg.answer.call_args.args[0])

    async def test_flag_on_offers_enabled_editions(self):
        _, ask, _ = await self._run(flag_on=True, answer=ai.Answer("Katalog javobi"))
        self.assertEqual(ask.call_args.args[2], [EDITION.catalog_title])

    async def test_routed_content_question_uses_grounded_pipeline(self):
        msg, _, qa_call = await self._run(
            flag_on=True, answer=ai.Answer("", book_question=(EDITION.catalog_title, "Tashvish nima?"))
        )
        qa_call.assert_awaited_once()
        # retrieval/answer use the user's ORIGINAL words, not the routing paraphrase
        self.assertEqual(qa_call.call_args.args[:3], (EDITION.edition_key, "savol", 42))
        self.assertEqual(msg.answer.call_args.args[0], "GROUNDED ANSWER")

    async def test_where_to_buy_still_goes_to_store_finder(self):
        msg, _, qa_call = await self._run(flag_on=True, answer=ai.Answer("Do‘kon", find_store=True))
        qa_call.assert_not_awaited()
        self.assertEqual(msg.answer.call_args.args[0], "Do‘kon")


if __name__ == "__main__":
    unittest.main()

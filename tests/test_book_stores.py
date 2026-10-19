"""📚 Kitoblar: which stores have a book (book_stores feature)."""

import unittest
from types import SimpleNamespace
from unittest import mock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import tests  # noqa: F401 — safe env first
import bot.repository as repository
from bot import keyboards
from bot.handlers import books as handler
from bot.handlers import location
from bot.models import Book, Store
from bot.repository import StoreWithDistance
from tests import test_rag_db

setUpModule = test_rag_db.setUpModule


class AvailabilityQueriesTest(test_rag_db.DBTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with test_rag_db.SF() as s:
            self.near = Store(name="Yaqin", latitude=41.31, longitude=69.24)
            self.far = Store(name="Uzoq", latitude=40.0, longitude=71.0)
            self.none = Store(name="Kitobsiz", latitude=41.30, longitude=69.25)
            self.book = Book(title="Qulog‘im senda, qizim!")
            self.other = Book(title="Boshqa kitob")
            s.add_all([self.near, self.far, self.none, self.book, self.other])
            await s.commit()
        self.test_store = await repository.get_or_create_test_store()
        for store in (self.far, self.near, self.test_store):
            await repository.add_store_book(store.id, book_id=self.book.id, title=self.book.title, author=None, added_by=1)
        await repository.add_store_book(self.far.id, book_id=None, title="Erkin matn", author=None, added_by=1)

    async def test_books_in_stores_counts_real_stores_only(self):
        self.assertEqual([(b.title, n) for b, n in await repository.books_in_stores()],
                         [("Qulog‘im senda, qizim!", 2)])  # free-text and unlisted books excluded
        self.assertEqual((await repository.books_in_stores(include_test=True))[0][1], 3)

    async def test_nearest_with_book_filters_and_orders(self):
        stores = await repository.find_nearest_stores_with_book(41.31, 69.24, 10, self.book.id)
        self.assertEqual([s.name for s in stores], ["Yaqin", "Uzoq"])  # no "Kitobsiz", no test store
        with_test = await repository.find_nearest_stores_with_book(41.31, 69.24, 10, self.book.id, include_test=True)
        self.assertIn(self.test_store.id, [s.id for s in with_test])
        self.assertEqual(await repository.find_nearest_stores_with_book(41.31, 69.24, 10, self.other.id), [])


def _store(name="Yaqin"):
    return StoreWithDistance(1, name, "manzil", None, None, None, 41.3, 69.2, 0.4)


def _state():
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=42))


def _msg():
    return SimpleNamespace(answer=mock.AsyncMock(), answer_photo=mock.AsyncMock())


class MenuButtonTest(unittest.TestCase):
    def _texts(self, kb):
        return [b.text for row in kb.keyboard for b in row]

    def test_books_button_only_with_feature(self):
        with mock.patch.object(keyboards.features, "enabled", return_value=False):
            self.assertNotIn(keyboards.BOOKS_TEXT, self._texts(keyboards.request_location_kb(42)))
        with mock.patch.object(keyboards.features, "enabled", return_value=True):
            self.assertIn(keyboards.BOOKS_TEXT, self._texts(keyboards.request_location_kb(42)))
        self.assertNotIn(keyboards.BOOKS_TEXT, self._texts(keyboards.request_location_kb()))

    def test_book_list_paginates(self):
        items = [(SimpleNamespace(id=i, title=f"K{i}"), 1) for i in range(keyboards.PAGE_SIZE + 2)]
        first = keyboards.available_books_kb(items, 0).inline_keyboard
        self.assertEqual(len(first), keyboards.PAGE_SIZE + 1)  # books + ▶️ row
        self.assertEqual([b.text for b in first[-1]], ["▶️"])
        last = keyboards.available_books_kb(items, keyboards.PAGE_SIZE).inline_keyboard
        self.assertEqual([b.text for b in last[-1]], ["◀️"])


class FlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.book = SimpleNamespace(id=7, title="Qulog‘im senda, qizim!")
        patches = [
            mock.patch.object(handler.features, "enabled", return_value=True),
            mock.patch.object(handler.features, "in_test_env", return_value=False),
            mock.patch.object(handler, "send_book_card", mock.AsyncMock()),
            mock.patch.object(handler.repo, "get_book_by_id", mock.AsyncMock(return_value=self.book)),
            mock.patch.object(handler.repo, "find_nearest_stores_with_book",
                              mock.AsyncMock(return_value=[_store()])),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _callback(self, msg):
        return SimpleNamespace(from_user=SimpleNamespace(id=42), message=msg, answer=mock.AsyncMock())

    async def test_without_location_asks_for_it_and_remembers_book(self):
        msg, state = _msg(), _state()
        await handler.show_book(self._callback(msg), keyboards.AvailBook(book_id=7), state)
        self.assertEqual((await state.get_data())["book_id"], 7)
        self.assertIn("joylashuvingizni yuboring", msg.answer.call_args.args[0])

    async def test_with_location_lists_stores_that_have_it(self):
        msg, state = _msg(), _state()
        await state.update_data(lat=41.3, lon=69.2)
        await handler.show_book(self._callback(msg), keyboards.AvailBook(book_id=7), state)
        self.assertIn("bor eng yaqin 1 ta do‘kon", msg.answer.call_args.args[0])
        kb = msg.answer.call_args.kwargs["reply_markup"].inline_keyboard
        self.assertEqual(kb[0][0].callback_data, "store:1")

    async def test_location_after_book_choice_filters_then_forgets(self):
        state = _state()
        await state.update_data(book_id=7)
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=42), answer=mock.AsyncMock(),
            location=SimpleNamespace(latitude=41.3, longitude=69.2),
        )
        user = SimpleNamespace(phone="+998901112233")
        with mock.patch.object(location.repo, "get_user", mock.AsyncMock(return_value=user)), \
             mock.patch.object(location.features, "enabled", return_value=True), \
             mock.patch.object(location, "find_nearest_stores", mock.AsyncMock()) as plain:
            await location.handle_location(message, state)
            plain.assert_not_awaited()
            self.assertIn("«Qulog‘im senda, qizim!» bor", message.answer.call_args.args[0])
            self.assertIsNone((await state.get_data())["book_id"])

            # the next location share is a normal nearest-store search again
            plain.return_value = [_store("Oddiy")]
            await location.handle_location(message, state)
            plain.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

import re
from html import escape, unescape
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, InputMediaPhoto, Message

from bot import ai, features, conversation
from bot.rag.normalize import search_key
from bot.rag.language import in_script
from bot import repository as repo
from bot.config import settings
from bot.database import session_factory
from bot.rag import qa, retrieval
from bot.rag.embeddings import get_provider
from bot.keyboards import AI_ENTER_TEXT, AI_EXIT_TEXT, ai_chat_kb, request_location_kb
from bot.states import AiChat

router = Router()

# Book info images live here (shipped inside the image via `COPY . .`).
BOOK_IMAGES_DIR = Path(__file__).resolve().parents[2] / "book_images"
# How many book images to send per answer (avoid flooding the chat).
_MAX_IMAGES = 4
# Telegram photo/album caption limit.
_CAPTION_LIMIT = 1024


def _norm(s: str) -> str:
    """Lowercase and strip punctuation, so title matching ignores «», !, ' etc."""
    return re.sub(r"[^a-z0-9Ѐ-ӿ]", "", (s or "").lower())


_rag_provider = None


def _content_provider():
    """Embedding provider for book Q&A retrieval (config; "none" by default)."""
    global _rag_provider
    if _rag_provider is None:
        client = ai._get_client() if settings.rag_embedding_provider == "openai" else None
        _rag_provider = get_provider(
            settings.rag_embedding_provider,
            # Opting in via RAG_EMBEDDING_PROVIDER=openai authorises the small
            # per-question query embedding; bulk import still needs --allow-paid.
            allow_paid=True,
            client=client,
            model=settings.rag_openai_embedding_model,
        )
    return _rag_provider


def _fmt(text: str) -> str:
    """Render the model's Markdown-ish **bold** as HTML (the bot uses HTML mode)."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(text))

_INTRO = (
    "🤖 <b>Falaq Nashr AI yordamchisi</b>\n\n"
    "Qanday kitob qidiryapsiz? Menga savol bering — masalan:\n"
    "• «Bolalar uchun qanday kitoblaringiz bor?»\n"
    "• «Detektiv janridagi kitob tavsiya qiling»\n"
    "• «Falonchi muallifning kitoblari bormi?»\n\n"
    "Asosiy menyuga qaytish uchun «⬅️ Orqaga» tugmasini bosing."
)

_BACK = "Asosiy menyu. Joylashuvingizni yuboring 📍 yoki yana AI yordamchini oching 🤖"

_DISABLED = (
    "🤖 AI yordamchi hozircha ulanmagan. Tez orada ishga tushadi — hozircha "
    "joylashuvingizni yuboring, eng yaqin do‘konni topaman."
)


def _content_title(question, editions, previous):
    """Force evidence use for an identified book, leaving commerce to catalogue.

    The model still resolves the topic/query, but cannot bypass grounding by
    emitting a free-form catalogue answer for these high-confidence cases.
    """
    q = search_key(question)
    if re.search(r"\b(?:narx|kancha|kayer|sotib|buyurtma|yetkaz|price|buy|where|tsena|skolko)\w*\b|muallifi kim|kim yozgan|tavsiya kiling|kitob bormi", q):
        return None
    named = [t for t in editions if f" {search_key(t)} " in f" {q} "]
    if len(named) == 1:
        return named[0]
    if previous['book_title'] in editions and re.search(
        r"^(?:shu|buni|bunga|bu |uni|ular|osha|nega|yana|endi|kisk|why|those|this|it |eto|eti)|shu misol|uchta.*kadam|ikkita.*ish", q
    ):
        return previous['book_title']
    return None


@router.message(F.text == AI_ENTER_TEXT)
async def enter_ai(message: Message, state: FSMContext) -> None:
    if not settings.ai_enabled:
        await message.answer(_DISABLED, reply_markup=request_location_kb(message.from_user.id))
        return
    await state.clear()
    await state.set_state(AiChat.active)
    await message.answer(_INTRO, reply_markup=ai_chat_kb())


@router.message(AiChat.active, F.text == AI_EXIT_TEXT)
async def back_to_menu(message: Message, state: FSMContext) -> None:
    # User pressed "Back" — stop the agent and restore the main menu buttons.
    await state.clear()
    await message.answer(_BACK, reply_markup=request_location_kb(message.from_user.id))


@router.message(AiChat.active, F.text & ~F.text.startswith("/"))
async def ask_ai(message: Message, state: FSMContext) -> None:
    question = message.text.strip()
    if not question:
        return
    await message.bot.send_chat_action(message.chat.id, "typing")

    # The catalogue is small, so hand the model the WHOLE list every time and let
    # it pick the genre-appropriate books itself — keyword search returned the
    # wrong subset for vibe queries like "detective". (When the catalogue grows
    # past ai_max_books, switch this to semantic retrieval.)
    books = await repo.sample_books(settings.ai_max_books)

    # Book-content Q&A (RAG), conversation memory and the spoiler boundary are
    # still in test mode: everyone else gets the released catalogue assistant.
    if not features.enabled("book_qa", message.from_user.id):
        res = await ai.answer_question(question, books)
        if res.find_store:
            await state.clear()
            await message.answer(res.text, reply_markup=request_location_kb(message.from_user.id))
            return
        await _send_catalogue_reply(message, books, res.text)
        return

    editions = {e.catalog_title: e.edition_key for e in await retrieval.enabled_editions(session_factory)}

    previous = conversation.read(await state.get_data())
    # An explicitly named different book starts a new book topic. This also
    # prevents carrying the old edition into a catalogue-only book question.
    named = [b.title for b in books if len(search_key(b.title)) >= 5
             and f" {search_key(b.title)} " in f" {search_key(question)} "]
    quoted_book = re.search(r"«([^»]+)»\s*(?:kitob|roman|китоб|роман)", question, re.I)
    unknown_named = quoted_book and not any(search_key(quoted_book[1]) == search_key(b.title) for b in books)
    if unknown_named or any(t != previous["book_title"] for t in named):
        previous = {"history": [], "book_title": None, "topic": ""}
    # Apply the spoiler boundary to catalogue and grounded routes alike.
    if qa.spoiler_request(question):
        reply = qa.spoiler_reply(question)
        title = named[0] if len(named) == 1 else previous["book_title"]
        await conversation.remember(state, previous, question, reply,
                                    book_title=title if title in editions else None,
                                    topic=previous["topic"])
        await message.answer(reply, reply_markup=ai_chat_kb())
        return
    res = await ai.answer_question(
        question, books, list(editions) or None,
        history=previous["history"], active_title=previous["book_title"],
        force_content_title=_content_title(question, editions, previous),
    )

    # The catalogue model routed a question about a book's CONTENT: answer it
    # from the book's passages only (grounded, cited, may abstain).
    wrong_requested_book = bool(named and (len(named) != 1 or (res.book_question and res.book_question[0] != named[0])))
    unavailable_content = bool(named and named[0] not in editions and re.search(
        r"kitob(?:ida|idagi)|roman(?:ida|idagi)|asar(?:ida|idagi)|matn|mazmun", search_key(question)))
    if res.book_question and (unknown_named or wrong_requested_book or unavailable_content):
        reply = in_script("So‘ralgan kitob yoki qism matni menda mavjud emas. Boshqa qismdan javob bera olmayman.", question)
        await conversation.remember(state, {"history": []}, question, reply)
        await message.answer(escape(reply), reply_markup=ai_chat_kb())
        return
    if unavailable_content:
        reply = in_script("So‘ralgan kitob yoki qism matni menda mavjud emas.", question)
        await conversation.remember(state, {"history": []}, question, reply)
        await message.answer(escape(reply), reply_markup=ai_chat_kb())
        return
    if res.book_question and res.book_question[0] in editions and not unknown_named:
        # The routing model only chooses WHICH book. Retrieval and the answer
        # use the user's own words: a paraphrase can corrupt them (seen in
        # testing: "ташвиш" rewritten as "ташувиш", which then missed page 20).
        title = res.book_question[0]
        await message.bot.send_chat_action(message.chat.id, "typing")
        same_book = title == previous["book_title"]
        followup = not named and res.is_followup and bool(previous["history"]) and previous["book_title"] in (None, title)
        resolved = res.book_question[1] if followup else ""
        result = await qa.answer_book_question(
            editions[title],
            question,
            message.from_user.id,
            session_factory=session_factory,
            provider=_content_provider(),
            history=previous["history"] if followup else [],
            resolved_question=resolved, search_query=res.search_query,
            context_chunk_ids=previous.get("evidence", []) if followup else [],
            requested_title=named[0] if len(named) == 1 else title,
            scope_question=previous.get("topic", "") if followup else "",
        )
        await conversation.remember(
            state, previous if same_book else {"history": []}, question,
            unescape(re.sub(r"<[^>]+>", "", result.text)), book_title=title,
            topic=(previous.get("topic", "") + " " + (resolved or question))[-1200:] if followup else question, evidence=[c.chunk_id for c in result.citations],
        )
        await message.answer(result.text, reply_markup=ai_chat_kb())
        return

    # The model called our store-finder ("where can I buy?"): leave AI mode and
    # show the main menu so the "📍 Joylashuvni yuborish" button (existing
    # nearest-store flow) is available.
    if res.find_store:
        await state.clear()
        await message.answer(escape(in_script(res.text, question)), reply_markup=request_location_kb(message.from_user.id))
        return

    reply = in_script(res.text, question)
    if unknown_named and res.book_question:
        reply = in_script("Bu nomdagi kitob matni menda mavjud emas. Katalogimizdagi boshqa kitob haqida yordam bera olaman.", question)
    await conversation.remember(state, previous, question, reply)
    await _send_catalogue_reply(message, books, reply)


async def _send_catalogue_reply(message: Message, books, reply: str) -> None:
    body = _fmt(reply)

    # Collect the info images for the catalogue books the assistant actually named.
    answer_norm = _norm(reply)
    seen: set[int] = set()
    images: list[Path] = []
    for b in books:
        if len(images) >= _MAX_IMAGES:
            break
        if b.id in seen or not b.image or len(_norm(b.title)) < 5:
            continue
        if _norm(b.title) in answer_norm:
            path = BOOK_IMAGES_DIR / b.image
            if path.is_file():
                seen.add(b.id)
                images.append(path)

    # No image → just the text. The text stays in AI mode (Back button visible).
    if not images:
        await message.answer(body, reply_markup=ai_chat_kb())
        return

    # Image(s) + text in ONE message: photo/album with the answer as the caption.
    fits = len(reply) <= _CAPTION_LIMIT
    if len(images) == 1:
        await message.answer_photo(
            FSInputFile(images[0]),
            caption=body if fits else None,
            reply_markup=ai_chat_kb(),
        )
    else:
        media = [
            InputMediaPhoto(media=FSInputFile(p), caption=body if (i == 0 and fits) else None)
            for i, p in enumerate(images)
        ]
        await message.answer_media_group(media)
    # Rare fallback: answer too long for a caption — send it as its own message.
    if not fits:
        await message.answer(body, reply_markup=ai_chat_kb())

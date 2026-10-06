"""Resolve a model-supplied quote to exact pages via source_segments.

A citation is only accepted if the quote actually occurs in a retrieved passage
(exactly, or differing only in whitespace). Its character offsets are then
mapped through the chunk's `source_segments` (zero-based, end-exclusive) to the
paragraph(s) and page(s) of the cited statement itself — not the whole chunk's
page span. Printed page numbers are used when present; otherwise the PDF page.
"""

import re
import unicodedata
from dataclasses import dataclass

_WS = re.compile(r"\s+")
_CASE_KEY = str.maketrans({chr(i):chr(i).lower() for i in [*range(65,91),*range(0x400,0x530)] if len(chr(i).lower())==1})
_APOSTROPHE_KEY = str.maketrans({c: "'" for c in "‘’ʻʼʹ`´′"})


@dataclass
class Citation:
    chunk_id: str
    quote: str  # exact source text at [start, end)
    start: int
    end: int
    paragraph_ids: list[str]
    pdf_pages: list[int]
    printed_pages: list[str | None]

    def page_label(self) -> str:
        printed = [p for p in self.printed_pages if p]
        if printed and len(printed) == len(self.printed_pages):
            first, last = printed[0], printed[-1]
            return f"{first}-bet" if first == last else f"{first}–{last}-betlar"
        first, last = self.pdf_pages[0], self.pdf_pages[-1]
        return f"PDF {first}-sahifa" if first == last else f"PDF {first}–{last}-sahifalar"


def _collapse_with_map(s: str) -> tuple[str, list[int]]:
    """Whitespace-collapsed copy of s plus, per output char, its index in s."""
    out: list[str] = []
    idx: list[int] = []
    prev_ws = False
    for i, ch in enumerate(s):
        if ch.isspace():
            if not prev_ws and out:
                out.append(" ")
                idx.append(i)
            prev_ws = True
        else:
            out.append(ch)
            idx.append(i)
            prev_ws = False
    return "".join(out), idx


def _locate(passage_text: str, quote: str) -> tuple[int, int] | None:
    """[start, end) of quote inside passage_text, or None if not verbatim."""
    quote = unicodedata.normalize("NFC", (quote or "").strip()).strip("«»\"' ")
    if len(quote) < 8:  # too short to be meaningful evidence
        return None
    # Typography-only canonicalisation is one character to one character, so
    # offsets still refer to the untouched source. Apostrophes are NOT removed.
    source_key = passage_text.translate(_APOSTROPHE_KEY).translate(_CASE_KEY)
    quote = quote.translate(_APOSTROPHE_KEY).translate(_CASE_KEY)
    pos = source_key.find(quote)
    if pos >= 0:
        return pos, pos + len(quote)
    hay, idx = _collapse_with_map(source_key)
    needle = _WS.sub(" ", quote)
    pos = hay.find(needle)
    if pos < 0:
        # PDF extractors can break a word at a single physical line ending.
        # Permit joining ONLY that boundary; retain original source offsets and
        # return the actual source substring, never the model's edited quote.
        pattern = []
        for i, char in enumerate(quote):
            pattern.append(r"\s+" if char.isspace() else re.escape(char))
            if char.isalpha() and i + 1 < len(quote) and quote[i+1].isalpha():
                pattern.append(r"(?:\r?\n)?")
        match = re.search("".join(pattern), source_key)
        return match.span() if match else None
    return idx[pos], idx[pos + len(needle) - 1] + 1


def locate(passage_text: str, quote: str) -> tuple[int,int] | None:
    exact=_locate(passage_text,quote)
    if exact is not None:return exact
    # Model-added outer punctuation is not source content. Strip only the
    # boundaries on a failed match; letters and internal punctuation stay exact.
    return _locate(passage_text,(quote or '').strip("«»\"' .,;:!?…"))


def segments_for(source_segments: list[dict], start: int, end: int) -> list[dict]:
    """Segments overlapping [start, end); falls back to the nearest preceding."""
    hit = [s for s in source_segments if s["start_char"] < end and s["end_char"] > start]
    if hit:
        return hit
    before = [s for s in source_segments if s["start_char"] <= start]
    return [before[-1]] if before else source_segments[:1]


def resolve(chunk_id: str, passage_text: str, source_segments: list[dict], quote: str) -> Citation | None:
    span = locate(passage_text, quote)
    if span is None:
        return None
    start, end = span
    segs = segments_for(source_segments, start, end)
    pdf_pages: list[int] = []
    printed: list[str | None] = []
    for s in segs:
        if s["pdf_page"] not in pdf_pages:
            pdf_pages.append(s["pdf_page"])
            printed.append(s.get("printed_page"))
    return Citation(
        chunk_id=chunk_id,
        quote=passage_text[start:end],
        start=start,
        end=end,
        paragraph_ids=[s.get("paragraph_id", "") for s in segs],
        pdf_pages=pdf_pages,
        printed_pages=printed,
    )

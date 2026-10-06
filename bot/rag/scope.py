"""Narrative bounds from edition metadata, never from a model's guess."""
import json
import re
from dataclasses import replace
from pathlib import Path

from bot.rag.normalize import search_key


def opening_requested(question: str) -> bool:
    return bool(re.search(r'\b(?:boshida|boshlanishida|dastlab\w*|avvaliga|initial\w*|beginning)\b|v nachale', search_key(question)))


def opening_pages(edition) -> tuple[int, int] | None:
    root = Path(__file__).resolve().parents[2] / 'scripts' / 'rag_editions'
    for path in root.glob('*.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('edition_key') != edition.edition_key or data.get('source_sha256') != getattr(edition, 'source_sha256', None):
            continue
        sections = data.get('narrative_sections') or []
        if sections:
            first = sections[0]
            start, end = first['pdf_page_start'], first['pdf_page_end']
            if isinstance(start, int) and isinstance(end, int) and 1 <= start <= end:
                return start, end
    return None


def constrain(passages, pages):
    """Clip crossing chunks using character provenance, excluding later text."""
    if pages is None:
        return passages
    result = []
    for passage in passages:
        segments = [s for s in passage.source_segments if pages[0] <= s['pdf_page'] <= pages[1]]
        if not segments:
            continue
        parts, mapped, offset = [], [], 0
        for seg in segments:
            fragment = passage.text[seg['start_char']:seg['end_char']]
            if parts:
                parts.append('\n')
                offset += 1
            parts.append(fragment)
            mapped.append({**seg, 'start_char': offset, 'end_char': offset + len(fragment)})
            offset += len(fragment)
        result.append(replace(passage, text=''.join(parts), source_segments=mapped,
                              page_map=[p for p in passage.page_map if pages[0] <= p.get('pdf_page', 0) <= pages[1]],
                              pdf_page_start=min(s['pdf_page'] for s in segments),
                              pdf_page_end=max(s['pdf_page'] for s in segments)))
    return result

"""Search keys for Uzbek text written in Cyrillic or Latin, with any apostrophe.

The stored book text is never changed — this builds a separate, lossy key used
only for matching, so that a Latin query ("tashvish", "Qulog'im") finds Cyrillic
source text ("ташвиш", "Қулоғим") and every apostrophe variant (ʻ ʼ ' ’ ‘ `)
compares equal.

Key construction (applied identically to stored text and to queries):
  1. Unicode NFC + casefold.
  2. Uzbek Cyrillic -> Latin (official 1995 alphabet; е/ye by position).
  3. Drop every apostrophe-like mark (o‘ -> o, g‘ -> g, tutuq belgisi removed).
  4. Loose merges for keyboards without Uzbek letters: q -> k (қ typed as к),
     h -> x outside sh/ch (ҳ typed as х). Both sides are merged, so matching stays symmetric.
  5. Anything that is not a-z/0-9 becomes a space.

Known limitation: ў typed as у ("уз" for "ўз") becomes "uz" vs "oz"; o/u are
not merged because that would conflate many unrelated words.
"""

import re
import unicodedata

_VOWELS = set("аеёиоуўэюяaeiou")

_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x",
    "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ы": "i", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "ё": "yo", "ў": "o'", "қ": "q", "ғ": "g'",
    "ҳ": "h",
}

# Every apostrophe-like character seen in Uzbek Latin text and keyboards.
_APOSTROPHES = "'‘’ʻʼʹ`´′"
_APOS_RE = re.compile(f"[{re.escape(_APOSTROPHES)}]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
# h -> x, but not inside the digraphs sh / ch.
_LONE_H = re.compile(r"(?<![sc])h")


def cyrillic_to_latin(text: str) -> str:
    """Transliterate (already lower-cased) Uzbek Cyrillic to Latin."""
    out: list[str] = []
    prev = ""
    for ch in text:
        if ch == "е":
            # "ye" at a word start or after a vowel / hard or soft sign.
            at_start = not prev or not prev.isalpha()
            out.append("ye" if at_start or prev in _VOWELS or prev in "ъь" else "e")
        else:
            out.append(_CYR_TO_LAT.get(ch, ch))
        prev = ch
    return "".join(out)


def search_key(text: str) -> str:
    """Script- and apostrophe-insensitive matching key (see module docstring)."""
    if not text:
        return ""
    s = unicodedata.normalize("NFC", text).casefold()
    s = cyrillic_to_latin(s)
    s = _APOS_RE.sub("", s)
    s = _LONE_H.sub("x", s.replace("q", "k"))
    s = _NON_ALNUM.sub(" ", s)
    return " ".join(s.split())


# Uzbek inflectional suffixes, already in search-key form (q->k, h->x, no
# apostrophes). Longest first; at most two are stripped and a stem never drops
# below 3 characters, so short roots survive.
_SUFFIXES = sorted(
    {
        "larimizdan", "laringizdan", "larimizga", "laridan", "larining",
        "larning", "larini", "lariga", "larida", "lardan", "larga", "larda",
        "larni", "lari", "lar", "ning", "dagi", "dan", "tan", "ga", "ka", "da",
        "ta", "ni", "imiz", "ingiz", "miz", "ngiz", "im", "ing", "si", "mi",
        "dir", "lik", "likni", "likka", "chi", "gan", "kan", "ishi",
    },
    key=len,
    reverse=True,
)

# Question words and fillers that carry no topic (search-key form).
_STOPWORDS = {
    search_key(w)
    for w in (
        "roman romani romanida romanidagi romanda tushuntiring ayting sodda fikr fikri fikrini "
        "o‘xshatish o‘xshatishini qayta hikoya voqealarni ochmasdan keyingi holda tayangan "
        "va bu shu u ular bilan uchun ham yoki lekin qanday qanaqa nima nimani "
        "nega nechta qaysi qayerda kim kimlar haqida haqda bor yo'q emas ekan "
        "edi deb degan deyilgan aytilgan kitob kitobda kitobning kitobdagi "
        "muallif qilib qilingan qiladi bo'ladi bo'lgan mi mu ni da ga "
        # "the book / work / author" in any inflection — refers to the book itself
        "kitobi kitobida kitobidagi kitobini kitobni kitobga kitobdan kitoblar "
        "kitoblari asar asari asarida asarda muallifi muallifning "
        "китоби китобида китобидаги китобини китобни китобга китобдан асар асари "
        "асарида муаллифи "
        # question scaffolding — describes the question, not its topic
        "farq farqi farqli tushuntir tushuntirilgan tushuntiradi izoh izohlangan "
        "mazmun mazmuni ma'no ma'nosi yozilgan keltirilgan berilgan mumkin kerak "
        "qanaqa haqidagi xususida hayotiy misol misollar amaliy qadam qadamlar qisqa qisqacha ajratib "
        "фарқ фарқи тушунтирилган изоҳ мазмуни маъноси ёзилган келтирилган мумкин керак "
        "и в на с по о что как это который также "
        "ва бу шу у улар билан учун ҳам ёки лекин қандай нима нега қайси ким "
        "ҳақида бор йўқ эмас экан эди деб деган дейилган айтилган китоб китобда "
        "китобнинг"
    ).split()
}


def stem(token: str) -> str:
    """Strip up to two Uzbek suffixes from a search-key token (min stem 3)."""
    for _ in range(2):
        for suf in _SUFFIXES:
            if token.endswith(suf) and len(token) - len(suf) >= 3:
                token = token[: -len(suf)]
                break
        else:
            break
    return token


def query_terms(question: str) -> list[str]:
    """Distinct stemmed search terms for a question (stopwords dropped)."""
    seen: list[str] = []
    for tok in search_key(question).split():
        if len(tok) < 3 or tok in _STOPWORDS or tok.isdigit():
            continue
        st = stem(tok)
        if st not in _STOPWORDS and st not in seen:
            seen.append(st)
    return seen

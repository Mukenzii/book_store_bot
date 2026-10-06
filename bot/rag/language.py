"""Display-script conversion, separate from the deliberately lossy search key."""
import re


def answer_script(question: str) -> str:
    cyr = sum('\u0400' <= ch <= '\u04ff' for ch in question)
    lat = sum(ch.isascii() and ch.isalpha() for ch in question)
    return 'Cyrillic' if cyr > lat else 'Latin'


def answer_language(text: str) -> str:
    """The shop's default is Uzbek; recognise explicit English/Russian wording."""
    if re.search(r"\b(?:what|why|how|which|explain|the|and|are|does|has|towards|reading|books)\b", text, re.I):
        return 'English'
    if re.search(r"\b(?:что|как|почему|какой|какая|книге|книги|книгу|книга|объясни|согласно)\b", text, re.I):
        return 'Russian'
    return 'Uzbek'


_LAT = dict(zip('abvgdjziklmnoprstufxqh', 'абвгджзиклмнопрстуфхқҳ'))
_LAT.update({'c': 'с', 'w': 'в', 'e': 'е', 'y': 'й', 'sh': 'ш', 'ch': 'ч', 'yo': 'ё',
             'yu': 'ю', 'ya': 'я', 'ye': 'е', "o'": 'ў', "g'": 'ғ'})
_CYR = {v: k for k, v in _LAT.items()}
_CYR.update({'с': 's', 'в': 'v', 'е': 'e', 'э': 'e', 'ц': 'ts', 'щ': 'sh', 'ъ': "'", 'ь': '', 'ы': 'i'})


def in_script(text: str, question: str) -> str:
    """Convert mixed Uzbek output; preserve source quotations separately."""
    cyr = answer_script(question) == 'Cyrillic'
    if not any((ch.isascii() and ch.isalpha()) if cyr else ('\u0400' <= ch <= '\u04ff') for ch in text):
        return text
    text = re.sub('[‘’ʻʼ`]', "'", text)
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        key = ch.lower()
        step = 1
        value = ch
        if cyr and ch.isascii() and ch.isalpha():
            pair = text[i:i+2].lower()
            if pair in _LAT:
                key, step = pair, 2
            value = _LAT.get(key, ch)
            if key == 'e' and (i == 0 or not text[i-1].isalpha()):
                value = 'э'
        elif not cyr and key in _CYR:
            value = _CYR[key]
            if key == 'е' and (i == 0 or not text[i-1].isalpha() or text[i-1].lower() in 'аеёиоуўэюяъь'):
                value = 'ye'
        if cyr and ch == "'" and i > 0 and i + 1 < len(text) and text[i-1].isalpha() and text[i+1].isalpha():
            value = 'ъ'
        if ch.isupper():
            value = value.capitalize()
        out.append(value)
        i += step
    return ''.join(out)


def preserve_uzbek_spelling(text: str, reference: str) -> str:
    """Preserve unambiguous h/x orthography from source and user terminology.

    Retrieval deliberately folds these letters; display must not. Correct only
    an otherwise identical word, and leave ambiguous reference spellings alone.
    """
    pattern=re.compile(r"[A-Za-z]+(?:['‘’ʻʼ][A-Za-z]+)*")
    variants={}
    for match in pattern.finditer(in_script(reference,'Latin')):
        word=match.group().lower()
        if len(word)>=4:variants.setdefault(word.replace('h','x'),set()).add(word)
    def fix(match):
        word=match.group();choices=variants.get(word.lower().replace('h','x'),set())
        if len(choices)!=1 or word.lower() in choices:return word
        target=next(iter(choices))
        return target.capitalize() if word[0].isupper() else target
    return pattern.sub(fix,in_script(text,'Latin'))


def activity_label(text: str) -> str:
    """Turn a standalone Uzbek converb into an infinitive activity label.

    The source action is unchanged: -ab/-ib becomes -ash/-ish. Full sentences
    and other forms are left to the composer and independent verifier.
    """
    return re.sub(r'([A-Za-z]+[ai])b([.!]?)$',r'\1sh\2',text) if answer_script(text)=='Latin' else re.sub(r'([а-яА-ЯўқғҳЎҚҒҲ]+[аи])б([.!]?)$',r'\1ш\2',text)

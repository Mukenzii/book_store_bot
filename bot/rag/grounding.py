"""Question requirements and focused evidence windows, independent of answers."""
import re
from bot.rag.normalize import query_terms, search_key
from bot.rag.language import in_script


def request_profile(question: str, title: str = '') -> dict:
    q = search_key(question)
    if title:
        q = q.replace(search_key(title), " ")
    focus = re.search(r'\b([a-z]+)ning (?:fikr|maslahat|izoh|karash)\w*', q)
    subject = focus[1] if focus else ''
    subject_label = ''
    if not subject:
        named = re.search(r'(?:romanida|kitobida|asarida|романида|китобида|асарида)\s+([A-ZА-ЯЎҚҒҲ][\wʻ’ʼ\']+)', question)
        if named:
            subject = search_key(named[1])
            subject_label = in_script(named[1], "Latin")
    reason = bool(re.search(r'\b(?:nega|why|pochemu)\b|nima uchun',q))
    examples = bool(re.search(r'\bmisol\w*|\bexamples?\b|primer', q))
    comparison = bool(re.search(r'\bfark\w*|\bajrat\w*|\bdifference\b|\bcompare\b|raznits|razlich', q)) and not examples
    count = 2 if examples or comparison else 1
    if examples:
        if re.search(r'\b(?:uchta|uch|three|tri|3)\b', q): count=3
        elif re.search(r'\b(?:bitta|bir|one|odin|1)\b',q): count=1
    kind = 'examples' if examples else 'comparison' if comparison else 'reason' if reason else 'explanation'
    if comparison and not subject:
        parts = [{'id':'R1','request':'Explain the first side of the requested distinction, using its actual definition.'},
                 {'id':'R2','request':'Explain the other side of the requested distinction, using its actual definition.'}]
    elif examples:
        parts = [{'id':f'R{i+1}','request':f'Concrete activity/example {i+1}; distinct from the others. Do not substitute a benefit or a general principle.'} for i in range(count)]
    elif reason:
        parts = [{'id':'R1','request':'Explain the source-supported REASON for the attitude or outcome. Merely repeating the attitude or outcome does NOT answer why. Select evidence explaining the reason.'}]
    else:
        parts = [{'id':'R1','request':"Directly answer the current question" + (f" from the viewpoint of {subject}; do not substitute another speaker's reaction." if subject else '.') }]
    return {'kind':kind,'subject':subject,'subject_label':subject_label,'parts':parts}


def evidence_window(text: str, question: str, title: str = '', *, limit: int = 1800) -> str:
    """Choose a contiguous source window covering the question's topic anchors.

    Retain exact text and surrounding dialogue. Return all short passages.
    This is context selection, never rewriting source material.
    """
    if len(text) <= limit:
        return text
    ignored=set(query_terms(title))
    focus=request_profile(question,title)['subject']
    if focus:ignored.add(focus)
    terms=[t for t in query_terms(question) if t not in ignored]
    if not terms:return text[:limit]
    boundaries=[0]+[m.end() for m in re.finditer(r'\n\s*\n',text)]
    choices=[]
    for start in boundaries:
        end=min(len(text),start+limit)
        key=search_key(text[start:end])
        hits=sum(any(word.startswith(t) for word in key.split()) for t in terms)
        # More topic coverage first, then shorter text (useful near passage end).
        choices.append((hits, -(end-start), start, end))
    _,_,start,end=max(choices,key=lambda row:(row[0],row[1],-row[2]))
    # Back up to retain the immediately preceding speaker attribution.
    previous=max((b for b in boundaries if b<start),default=start)
    if start-previous<=250:start=previous
    return text[start:end]

_NAME = r'[A-ZА-ЯЎҚҒҲ][\wʻ’ʼ\']+'
_NOT_NAMES = {'u','uning','men','biz','yana','bir','shu','shunda','shundan','oradan','lekin','ammo','bu','endi','avvalo','moysafid'}


def _name(value):
    if value.endswith('ning'):value=value[:-4]
    elif value.endswith('нинг'):value=value[:-4]
    return value if search_key(value) not in _NOT_NAMES else None


def dialogue_spans(text):
    """Speaker hints from explicit attribution and unambiguous two-person turns."""
    paragraphs=list(re.finditer(r'[^\n]+(?:\n(?!\n)[^\n]+)*',text))
    anchors={}
    for i,m in enumerate(paragraphs):
        body=m.group().strip()
        if body.startswith(('—','–')):
            match=re.search(r'(?:dedi|деди|soʻradi|сўради)\s+('+_NAME+r')',body)
            if match and (name:=_name(match[1])):anchors[i]=name
        elif body.endswith(':') and i+1<len(paragraphs) and paragraphs[i+1].group().lstrip().startswith(('—','–')):
            match=re.search(r'('+_NAME+r')(?:ning|нинг)\s+(?:ovozi|овози)',body)
            if not match:match=re.search(r'('+_NAME+r')(?:\s+\w+){0,3}\s+(?:dedi|деди|aytdi|айтди)\s*:$',body)
            if not match:match=re.match('('+_NAME+r')',body)
            if match and (name:=_name(match[1])):anchors[i+1]=name
    actors={search_key(name):name for name in anchors.values()}
    previous=None;out=[]
    for i,m in enumerate(paragraphs):
        if not m.group().lstrip().startswith(('—','–')):continue
        actor=anchors.get(i);method='explicit'
        if not actor and previous and len(actors)==2:
            actor=next((name for key,name in actors.items() if key!=search_key(previous)),None)
            method='alternating two-person dialogue'
        previous=actor
        out.append({'start':m.start(),'end':m.end(),'speaker':actor,'method':method})
    return out


def citation_speaker(text,start,end):
    hits=[s for s in dialogue_spans(text) if s['start']<end and s['end']>start]
    names={s['speaker'] for s in hits if s['speaker']}
    return next(iter(names)) if len(names)==1 else None


def annotated_source(text):
    for span in reversed(dialogue_spans(text)):
        if span['speaker']:
            text=text[:span['start']]+f"[Speaker metadata: {span['speaker']} ({span['method']})]\n"+text[span['start']:]
    return text


def focused_sources(passages,question,title):
    profile=request_profile(question,title)
    candidates=passages
    if profile['subject']:
        matching=[p for p in passages if any(search_key(s['speaker'] or '')==profile['subject'] for s in dialogue_spans(p.text))]
        if matching:candidates=matching
    ignored=set(query_terms(title))|{profile['subject']}
    terms=[t for t in query_terms(question) if t not in ignored]
    ranked=[]
    for p in candidates:
        window=evidence_window(annotated_source(p.text),question,title)
        key=search_key(window).split()
        score=sum(any(w.startswith(t) for w in key) for t in terms)
        ranked.append((score,p,window))
    if profile['kind']=='examples' and ranked:
        best=max(s for s,_,_ in ranked)
        ranked=[r for r in ranked if r[0]==best]
    return [(p,window) for _,p,window in ranked[:3]]

import unittest
import tests
from bot.rag.citations import resolve
from bot.rag.grounding import request_profile, dialogue_spans, citation_speaker, annotated_source

DIALOGUE="""Dilnoza Jasurga qaradi:

— Men mashqni qiyin deb hisoblayman.

Jasur dedi:

— Mashq qilish bilan musobaqaga qatnashish bir narsa emas.

Dilnoza kuldi:

— Men uchun ikkalasi ham qiyin.

— Lekin ular turli faoliyatlar.
"""

class GroundingSixTest(unittest.TestCase):
    def test_equivalent_apostrophes_keep_original_text_and_offsets(self):
        source='Oldingi gap. Koʻrish va oʻqish. Keyingi gap.'
        quote="Ko'rish va o'qish."
        segments=[{'start_char':0,'end_char':len(source),'pdf_page':8}]
        cited=resolve('unit',source,segments,quote)
        self.assertIsNotNone(cited)
        self.assertEqual(source[cited.start:cited.end],cited.quote)
        self.assertEqual(cited.quote,'Koʻrish va oʻqish.')
        self.assertEqual(cited.pdf_pages,[8])
        self.assertIsNone(resolve('unit',source,segments,'Korish va oqish.'))
        self.assertIsNone(resolve('unit',source,segments,"Ko'rmaslik va o'qish."))

    def test_model_added_outer_punctuation_keeps_exact_source_clause(self):
        source='Oldin: «Bog‘ni sug‘orib, so‘ng dam ol», dedi.'
        segments=[{'start_char':0,'end_char':len(source),'pdf_page':3}]
        citation=resolve('unit',source,segments,'«Bog‘ni sug‘orib».')
        self.assertIsNotNone(citation)
        self.assertEqual(citation.quote,'Bog‘ni sug‘orib')
        self.assertEqual(source[citation.start:citation.end],citation.quote)

    def test_viewpoint_is_taken_from_question_not_selected_passage(self):
        for q in ('Kitobda Jasurning fikrini ayting.', 'Китобда Жасурнинг фикрини айтинг.'):
            self.assertEqual(request_profile(q)['subject'],'jasur')
        self.assertEqual(request_profile('«Sinov» kitobida Jasur ikki faoliyatni qanday farqlaydi?')['subject'],'jasur')

    def test_comparison_requires_both_sides_and_examples_are_concrete_parts(self):
        self.assertEqual(len(request_profile('Tushuncha bilan amaliyot farqi qanday?')['parts']),2)
        self.assertEqual(len(request_profile('Uchta amaliy misol keltiring.')['parts']),3)
        p=request_profile('«Sinov (1-qism)» kitobida qanday misollar berilgan?','Sinov (1-qism)')
        self.assertEqual(len(p['parts']),2)
        self.assertIn('Concrete activity',p['parts'][0]['request'])

    def test_dialogue_attribution_does_not_swap_reaction_and_explanation(self):
        spans=dialogue_spans(DIALOGUE)
        self.assertEqual([s['speaker'] for s in spans],['Dilnoza','Jasur','Dilnoza','Jasur'])
        for term,actor in [('Men mashqni','Dilnoza'),('Mashq qilish','Jasur'),('Men uchun','Dilnoza')]:
            start=DIALOGUE.index(term)
            self.assertEqual(citation_speaker(DIALOGUE,start,start+len(term)),actor)
        self.assertIn('Speaker metadata: Jasur',annotated_source(DIALOGUE))

    def test_three_person_dialogue_does_not_guess_unattributed_turn(self):
        text=DIALOGUE+'\nZafar dedi:\n\n— Boshqa fikrim bor.\n\n— Qanday fikr?'
        self.assertIsNone(dialogue_spans(text)[-1]['speaker'])

class EvidenceSelectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_speaker_retries_using_requested_viewpoint(self):
        import json
        from types import SimpleNamespace
        from bot.rag import qa,evidence_qa,retrieval
        text=DIALOGUE
        p=retrieval.Passage('dialogue',text,'body',[],[{'start_char':0,'end_char':len(text),'pdf_page':1}],1,1,1.)
        ed=SimpleNamespace(catalog_title='Sinov',edition_key='unit',language='uz-Latn')
        question='Sinov kitobida Jasur ikki faoliyatni qanday farqlaydi?'
        calls=[]
        replies=[
            {'supported':True,'spoiler_safe':True,'evidence':[{'parts':['R1'],'passage':'P1','quote':'Men uchun ikkalasi ham qiyin.'}]},
            {'supported':True,'spoiler_safe':True,'evidence':[{'parts':['R1'],'passage':'P1','quote':'Mashq qilish bilan musobaqaga qatnashish bir narsa emas.'}]},
            {'supported':True,'spoiler_safe':True,'claims':[{'parts':['R1'],'evidence':['E1'],'text':'Mashq qilish bilan musobaqaga qatnashish bir narsa emas.'}]},
            {'verdicts':[{'index':0,'entailed':True}],'coverage':[{'part':'R1','satisfied':True}],'spoiler_safe':True}]
        async def llm(messages):calls.append(messages);return json.dumps(replies.pop(0))
        messages,by_id=qa.build_messages(ed.catalog_title,question,[p])
        result=await evidence_qa.answer(ed,question,[p],by_id,messages,llm)
        self.assertEqual(result.status,'answered')
        self.assertEqual(len(calls),4)
        self.assertNotIn('qiyin',result.text)
        self.assertIn('Dilnoza',calls[1][-1]['content'])

    def test_question_name_keeps_display_spelling_separate_from_search_key(self):
        profile=request_profile('Китобида эмас, романида Ҳаё қандай қарайди?')
        self.assertEqual(profile['subject_label'],'Hayo')

    def test_internal_spelling_error_is_not_a_source_inflection(self):
        from bot.rag.evidence_qa import novel_terms
        evidence=[{'quote':'бўлиб ўтган мусибат учун сиқилиш','speaker':None}]
        self.assertIn('sikiilish',novel_terms('sikiilish',evidence))
        self.assertEqual(novel_terms('siqilish',evidence),[])


class DisplayOrthographyTest(unittest.TestCase):
    def test_display_uses_unambiguous_source_h_x_spelling(self):
        from bot.rag.language import preserve_uzbek_spelling
        self.assertEqual(preserve_uzbek_spelling('Halal beradi.','Халал беради.'),'Xalal beradi.')
        self.assertEqual(preserve_uzbek_spelling('Halal beradi.','halal xalal'),'Halal beradi.')


class TypographyAndGrammarTest(unittest.TestCase):
    def test_why_requires_a_reason_not_an_attitude_restatement(self):
        profile=request_profile('Нега у шундай қарайди?')
        self.assertEqual(profile['kind'],'reason')
        self.assertIn('Merely repeating',profile['parts'][0]['request'])

    def test_sentence_initial_capitalization_keeps_source_offsets(self):
        source='Avval dam olib, keyin mashq qilib.'
        segments=[{'start_char':0,'end_char':len(source),'pdf_page':3}]
        citation=resolve('unit',source,segments,'Keyin mashq qilib.')
        self.assertEqual(citation.quote,'keyin mashq qilib.')
        self.assertEqual(source[citation.start:citation.end],citation.quote)
    def test_activity_inflection_changes_form_without_changing_action(self):
        from bot.rag.language import activity_label
        self.assertEqual(activity_label('Rasm chizib.'),'Rasm chizish.')
        self.assertEqual(activity_label('Сайр қилиб.'),'Сайр қилиш.')
        self.assertEqual(activity_label('Ovqat tayyorlab.'),'Ovqat tayyorlash.')
        self.assertEqual(activity_label('U rasm chizadi.'),'U rasm chizadi.')

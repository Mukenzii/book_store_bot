"""Regression boundaries discovered in the bilingual, two-book user flow."""
import json
import re
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

import tests
from bot import ai
from bot.rag import qa, retrieval, scope
from bot.rag.language import in_script, answer_language
from tests.test_rag_qa import _passage, EDITION


class ScopeAndScriptTest(unittest.TestCase):
    def test_language_is_separate_from_script(self):
        self.assertEqual(answer_language('Hayo boshida qanday qaraydi?'), 'Uzbek')
        self.assertEqual(answer_language('Ҳаё бошида қандай қарайди?'), 'Uzbek')
        self.assertEqual(answer_language('Hayo has a negative attitude towards reading books.'), 'English')
        self.assertEqual(answer_language('Что сказано в книге?'), 'Russian')

    def test_opening_does_not_mean_first_shock(self):
        for q in ('Hayo boshida qanday qaraydi?', 'Ҳаё дастлаб қандай қарайди?', 'в начале романа'):
            self.assertTrue(scope.opening_requested(q))
        self.assertFalse(scope.opening_requested('Birinchi zarbadagi sabr nima?'))

    def test_manifest_is_bound_to_exact_source(self):
        ed = SimpleNamespace(edition_key='falaq.binafsha-shulasi-1.2026-08.revised.uz-latn',
            source_sha256='6f45be4773c99024e386f06e8b73c6a6c690129f3dd2bec5eabbfdb68afd38a9')
        self.assertEqual(scope.opening_pages(ed), (9, 54))
        ed.source_sha256 = 'other PDF'
        self.assertIsNone(scope.opening_pages(ed))

    def test_crossing_chunk_is_clipped_and_citations_rebased(self):
        p = replace(_passage('c00003'), text='Opening text. Later revelation.',
            source_segments=[{'start_char':0, 'end_char':13, 'pdf_page':54},
                             {'start_char':14, 'end_char':31, 'pdf_page':55}],
            pdf_page_start=54, pdf_page_end=55)
        clipped = scope.constrain([p], (9,54))
        self.assertEqual(clipped[0].text, 'Opening text.')
        self.assertEqual(clipped[0].pdf_page_end, 54)
        self.assertIsNone(qa.resolve(p.chunk_id, clipped[0].text, clipped[0].source_segments, 'Later revelation.'))

    def test_mixed_script_is_repaired_without_lossy_search_spelling(self):
        mixed = 'Kitобда darslik ва ўқиш ҳақида айтилади.'
        cyr = in_script(mixed, 'Кириллча')
        lat = in_script(mixed, 'Latin')
        self.assertEqual(cyr, 'Китобда дарслик ва ўқиш ҳақида айтилади.')
        self.assertEqual(lat, "Kitobda darslik va o'qish haqida aytiladi.")
        self.assertNotRegex(cyr, '[A-Za-z]')
        self.assertNotRegex(lat, '[\u0400-\u04ff]')

    def test_soft_line_break_keeps_actual_source_quote_and_offsets(self):
        source = "Majburan oʻqigan darsliklarni hisobga olma\nganda, birorta ham\nkitob oʻqimaganman."
        quote = "Majburan oʻqigan darsliklarni hisobga olmaganda, birorta ham kitob oʻqimaganman."
        citation = qa.resolve('x', source, [{'start_char':0,'end_char':len(source),'pdf_page':49}], quote)
        self.assertIsNotNone(citation)
        self.assertEqual(citation.quote, source)
        self.assertEqual(citation.pdf_pages, [49])
        self.assertIsNone(qa.resolve('x', source, [{'start_char':0,'end_char':len(source),'pdf_page':49}], 'Hech qanday kitob oʻqimaganman.'))

    def test_fusion_retains_original_query_and_rewards_agreement(self):
        a, b, c = [_passage(key) for key in ('c00003','c00004','c00005')]
        self.assertEqual([p.chunk_id for p in retrieval.merge_rankings([a,b],[c,b], k=3)],
                         [b.chunk_id,a.chunk_id,c.chunk_id])


class ClaimBoundaryTest(unittest.IsolatedAsyncioTestCase):
    quote='Ташвиш — ҳали бўлмаган иш учун олдиндан безовталанишдир.'
    def selection(self):
        return {'supported':True,'spoiler_safe':True,'evidence':[{'parts':['R1'],'passage':'P1','quote':self.quote}]}
    def composition(self):
        return {'supported':True,'spoiler_safe':True,'claims':[{'parts':['R1'],'evidence':['E1'],'text':self.quote}]}
    def verdict(self):
        return {'verdicts':[{'index':0,'entailed':True}],'coverage':[{'part':'R1','satisfied':True}],'spoiler_safe':True}
    async def ask(self, composition=None, question='Tashvish nima?', verdict=None, selection=None, sequence=None, **kwargs):
        selection=self.selection() if selection is None else selection
        composition=self.composition() if composition is None else composition
        verdict=self.verdict() if verdict is None else verdict
        async def respond(messages):
            content=messages[-1]['content']
            value=verdict if 'CLAIM VALIDATION' in content else composition if 'EVIDENCE COMPOSITION' in content else selection
            return json.dumps(value)
        llm=mock.AsyncMock(side_effect=sequence or respond)
        self.llm=llm
        with mock.patch.object(retrieval,'get_edition',mock.AsyncMock(return_value=EDITION)), mock.patch.object(retrieval,'retrieve',mock.AsyncMock(return_value=[_passage('c00003')])):
            return await qa.answer_book_question(EDITION.edition_key,question,42,session_factory=None,llm=llm,limiter=qa.DailyLimiter(100),**kwargs)
    async def test_only_individually_supported_claims_are_rendered(self):
        data=self.composition();data['answer']='UNMAPPED EXTRA CLAIM'
        result=await self.ask(data)
        self.assertEqual(result.status,'answered');self.assertNotIn('UNMAPPED',result.text)
    async def test_one_unsupported_claim_rejects_whole_response(self):
        for invalid in ({'text':'Unsupported','parts':['R1'],'evidence':[]}, {'text':'Unsupported','parts':['R1'],'evidence':['E99']}):
            data=self.composition();data['claims'].append(invalid)
            self.assertEqual((await self.ask(data)).status,'abstained')
    async def test_missing_comparison_side_cannot_pass(self):
        self.assertEqual((await self.ask(question='Tashvish bilan qayg‘u farqi?')).status,'abstained')
    async def test_independent_verifier_rejects_wrong_meaning_and_incomplete_coverage(self):
        for field in ('verdicts','coverage'):
            verdict=self.verdict();verdict[field][0]['entailed' if field=='verdicts' else 'satisfied']=False
            self.assertEqual((await self.ask(verdict=verdict)).status,'abstained')
    async def test_new_content_and_source_spelling_errors_fail_closed(self):
        for text in ('Tashvish faqat boylik bilan bog‘lanadi.', 'Tashvish hali bo‘lmagan ish uchun oldindan bezovtalanashdir.'):
            data=self.composition();data['claims'][0]['text']=text
            self.assertEqual((await self.ask(data,question='Sinov kitobida Jasur tashvishni qanday tushuntiradi?')).status,'abstained')
    async def test_missing_or_malformed_independent_verdict_fails_closed(self):
        for verdict in ({}, [], 'bad JSON', {'verdicts':[{'index':9,'entailed':True}]}, {'verdicts':[{'index':False,'entailed':True}]}):
            result=await self.ask(question='Ташвиш нима?',verdict=verdict)
            self.assertEqual(result.status,'error');self.assertNotRegex(result.text,'[A-Za-z]')
    async def test_malformed_verdict_gets_one_bounded_format_retry(self):
        seq=[json.dumps(v) for v in (self.selection(),self.composition(),{},self.verdict())]
        self.assertEqual((await self.ask(sequence=seq)).status,'answered')
        self.assertEqual(self.llm.await_count,4)
    async def test_english_drift_is_repaired_then_independently_verified(self):
        original=self.composition();original['claims'][0]['text']='The book describes worry about future events.'
        seq=[json.dumps(v) for v in (self.selection(),original,self.composition(),self.verdict())]
        result=await self.ask(sequence=seq)
        self.assertEqual(result.status,'answered');self.assertNotIn('The book',result.text)
        self.assertIn('COMPOSITION CORRECTION',self.llm.call_args_list[2].args[0][-1]['content'])
        self.assertIn('CLAIM VALIDATION',self.llm.call_args_list[3].args[0][-1]['content'])
    async def test_requested_title_is_enforced_before_retrieval(self):
        self.assertEqual((await self.ask(requested_title='Another book')).status,'unavailable')
    async def test_unknown_opening_bounds_fail_closed(self):
        self.assertEqual((await self.ask(question='Hayo boshida qanday qaraydi?')).status,'abstained')
    async def test_malformed_composition_fails_closed_in_question_script(self):
        for broken in ('not json','[]','null'):
            result=await self.ask(question='Ташвиш нима?',sequence=[json.dumps(self.selection()),broken])
            self.assertEqual(result.status,'error');self.assertNotRegex(result.text,'[A-Za-z]')
    async def test_cyrillic_fallbacks_are_fully_cyrillic(self):
        for question,kw in [('Китобда нима дейилган?',{'requested_title':'Other'}),('Китоб бошида нима дейилган?',{}),('ташвиш '*200,{})]:
            self.assertNotRegex((await self.ask(question=question,**kw)).text,'[A-Za-z]')


class EditionRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def test_available_volume_cannot_replace_explicit_unavailable_volume(self):
        from aiogram.fsm.context import FSMContext
        from aiogram.fsm.storage.memory import MemoryStorage
        from aiogram.fsm.storage.base import StorageKey
        from bot.handlers import ai as handler
        from tests.test_ai_handler_routing import _message
        one="Binafsha shu'lasi (1-qism)";two="Binafsha shu'lasi (2-qism)"
        for question in (f'«{two}» romanida Amin nima degan?',
                         '«Бинафша шуъласи (2-қисм)» романида Амин нима деган?'):
            storage=MemoryStorage();state=FSMContext(storage,StorageKey(bot_id=1,chat_id=1,user_id=42))
            msg=_message(question)
            with mock.patch.object(handler.repo,'sample_books',mock.AsyncMock(return_value=[SimpleNamespace(title=t) for t in (one,two)])), \
                 mock.patch.object(handler.features,'enabled',return_value=True), \
                 mock.patch.object(handler.retrieval,'enabled_editions',mock.AsyncMock(return_value=[SimpleNamespace(catalog_title=one,edition_key='volume1')])), \
                 mock.patch.object(handler.ai,'answer_question',mock.AsyncMock(return_value=ai.Answer('',book_question=(one,'Amin?')))), \
                 mock.patch.object(handler.qa,'answer_book_question',mock.AsyncMock()) as answer:
                await handler.ask_ai(msg,state)
                answer.assert_not_awaited()
                self.assertNotIn('1-',msg.answer.call_args.args[0])
                if 'Бинафша' in question:
                    self.assertNotRegex(msg.answer.call_args.args[0],'[A-Za-z]')
            await storage.close()

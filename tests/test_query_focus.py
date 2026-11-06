"""Conversational scaffolding must not become the cross-window lookup topic."""
from datetime import datetime
import unittest

from nkb import Brain
from nkb.companion.memory import record_turn
from nkb.organizer.state import semantic_recall
from nkb.retrieval.encoders import bigram
from nkb.retrieval.query import plan_query


class QueryFocusTests(unittest.TestCase):
    reference=datetime(2026,11,6,12).timestamp()

    def plan(self,text):return plan_query(text,self.reference)

    def test_clarification_reporting_and_polite_frames_keep_the_object(self):
        for prefix in ('我指的是','我的意思是','我是说','我说的是','我问的是','我想问的是',
                       '我的问题是','准确地说：','具体来说，','也就是说','换句话说：',
                       '你刚才说的是','你上回说的是','你说过的','请问','请问一下',
                       '请告诉我','可以告诉我','能不能告诉我'):
            with self.subTest(prefix=prefix):
                plan=self.plan(prefix+'海洋计划')
                self.assertEqual(plan.search,'海洋计划')
                self.assertFalse(plan.needs_clarification)
                self.assertFalse(plan.literal)

    def test_nested_frames_and_spacing_do_not_create_new_adjacent_bigrams(self):
        plan=self.plan('我的意思是： 你说的是 不加糖的咖啡')
        self.assertEqual(plan.search,'不加糖的咖啡')
        dated=self.plan('海洋今天计划')
        self.assertEqual(dated.search,'海洋 计划')
        self.assertNotIn('洋计',bigram(dated.search))

    def test_missing_objects_and_bare_follow_ups_do_not_guess_old_topics(self):
        for text in ('我指的是','我的意思是','我说的是这个','我指的是那个人','还有呢',
                     '然后呢','接下来呢','继续呢','你刚才说的是那个','换句话说：那件事'):
            with self.subTest(text=text):
                plan=self.plan(text)
                self.assertTrue(plan.needs_clarification)
                self.assertEqual(plan.public()['reason'],'missing_topic')

    def test_short_names_single_characters_and_negation_remain_searchable(self):
        for value in ('岚','苏轼','C++','GPT-5','不加糖的咖啡','不是苏辙','没有完成纸月亮'):
            with self.subTest(value=value):
                plan=self.plan('我指的是'+value)
                self.assertEqual(plan.search,value)
                self.assertFalse(plan.needs_clarification)
        self.assertEqual(self.plan('我指的不是苏辙').search,'不是苏辙')
        self.assertEqual(self.plan('我喜欢苏轼的词').search,'我喜欢苏轼的词')

    def test_quoted_short_phrases_are_literal_objects_not_discourse_or_time_cues(self):
        for phrase in ('我指的是','然后','岚','我','未完成','2026-02-30','昨天','现在'):
            for wrapped in ('“'+phrase+'”','搜索“'+phrase+'”','请找原话里包含“'+phrase+'”的记录'):
                with self.subTest(wrapped=wrapped):
                    plan=self.plan(wrapped)
                    self.assertTrue(plan.literal)
                    self.assertEqual(plan.search,phrase)
                    self.assertFalse(plan.needs_clarification)
                    self.assertFalse(plan.invalid_date)
                    self.assertFalse(plan.unfinished)
                    self.assertIsNone(plan.start)

    def test_explicit_unquoted_literal_requests_preserve_short_and_generic_objects(self):
        for text,wanted in (('搜索我指的是','我指的是'),('原话里包含然后的记录','然后'),
                            ('请查找岚','岚'),('搜索昨天','昨天'),('包含我指的是的原句','我指的是')):
            with self.subTest(text=text):
                plan=self.plan(text)
                self.assertTrue(plan.literal)
                self.assertEqual(plan.search,wanted)
                self.assertFalse(plan.needs_clarification)
        self.assertTrue(self.plan('搜索').needs_clarification)

    def test_quotation_does_not_erase_negation_outside_the_quotes(self):
        for text in ('我指的是“苏轼”，不是“苏辙”','我指的是“包含”，不是“含有”',
                     '查找包含“咖啡”而不是“茶”的原话'):
            with self.subTest(text=text):
                plan=self.plan(text)
                self.assertFalse(plan.literal)
                self.assertIn('不是',plan.search)
        plain=self.plan("I don't like coffee and won't drink it")
        self.assertFalse(plain.literal)
        self.assertEqual(plain.search,"I don't like coffee and won't drink it")

    def test_mentioning_source_words_and_normal_quoted_dialogue_are_not_literal_requests(self):
        for text,wanted in (('我指的是记忆库的原文','记忆库的原文'),
                            ('我说的是原话，不是摘要','原话，不是摘要'),
                            ('我指的是“清单”，为什么总背','清单 ，为什么总背'),
                            ('这段话包含两个主题','这段话包含两个主题')):
            with self.subTest(text=text):
                plan=self.plan(text)
                self.assertFalse(plan.literal)
                self.assertEqual(plan.search,wanted)
                self.assertFalse(plan.needs_clarification)
        self.assertFalse(self.plan('搜索“咖啡”，为什么查不到').literal)
        self.assertFalse(self.plan('搜索“咖啡”和“红茶”').literal)

    def test_contextual_frames_are_marked_without_claiming_a_window_or_object(self):
        for text in ('我指的是刚才QQ这个','我指的是“清单”，为什么总背','然后呢','那个'):
            with self.subTest(text=text):
                plan=self.plan(text)
                self.assertTrue(plan.contextual)
                self.assertTrue(plan.public()['contextual_query'])
        self.assertFalse(self.plan('搜索“我指的是”').contextual)
        self.assertFalse(self.plan('请问苏轼').contextual)

    def test_question_frames_keep_the_object_frequency_negation_and_quoted_titles(self):
        for text,wanted in (('我指的是为什么总背清单','总背清单'),
                            ('为何总是重复清单','总是重复清单'),
                            ('怎么会不喜欢咖啡','不喜欢咖啡'),
                            ('海洋计划是什么','海洋计划'),
                            ('海洋计划怎么样','海洋计划'),
                            ('海洋计划怎么回事','海洋计划'),
                            ('我指的是《为什么总背清单》这本书','为什么总背清单 这本书')):
            with self.subTest(text=text):
                plan=self.plan(text)
                self.assertEqual(plan.search,wanted)
                self.assertFalse(plan.needs_clarification)
        title=self.plan('《为什么总背清单》')
        self.assertTrue(title.literal)
        self.assertEqual(title.search,'为什么总背清单')
        self.assertEqual(self.plan('清单不是什么').search,'清单不是什么')

    def test_dates_unfinished_and_original_query_contract_are_preserved(self):
        original='昨天我指的是海洋计划'
        plan=self.plan(original)
        self.assertEqual(plan.search,'海洋计划')
        self.assertEqual(datetime.fromtimestamp(plan.start),datetime(2026,11,5))
        plan=self.plan('昨天原话里包含“我指的是”')
        self.assertEqual(plan.search,'我指的是');self.assertTrue(plan.literal)
        self.assertEqual(datetime.fromtimestamp(plan.start),datetime(2026,11,5))
        unfinished=self.plan('上次还没完成的约定')
        self.assertTrue(unfinished.unfinished)
        self.assertEqual(unfinished.search,'承诺 约定 待办')
        self.assertEqual(self.plan('以前和现在的海洋计划').intent,'comparison')

    def test_shared_frame_only_sources_do_not_match_an_absent_new_object(self):
        brain=Brain.new();brain.meta.update(library_id='synthetic',long_term_archive=True)
        for index,text in enumerate(('我指的是街角那家修车店。','我指的是冰箱里的酸奶。',
                                     '我指的是会议室投影仪。','我指的是小说的反派。')):
            record_turn(brain,text,'当时的合成回复','old-window-'+str(index),str(index))
        for query in ('我指的是','我指的是海洋计划','我的意思是海洋计划','然后呢'):
            with self.subTest(query=query):
                result=semantic_recall(brain,query)
                self.assertEqual(result['hits'],[])
                self.assertEqual(result['query'],query)
        literal=semantic_recall(brain,'搜索“我指的是”')
        self.assertEqual(len(literal['hits']),4)
        self.assertTrue(literal['query_understanding']['literal_query'])


if __name__=='__main__':unittest.main()

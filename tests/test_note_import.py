"""Real desktop data entry: preview, duplicate safety, editable records, and atomic writes."""
from __future__ import annotations
import copy
import unittest
from unittest.mock import patch

from nkb import Brain, Config
from nkb.errors import ValidationError
from nkb.ingest.notes import import_notes, plan_notes
from nkb.ingest.markdown import split_markdown
import test_http as fixtures


class ImportTests(unittest.TestCase):
    def test_preview_does_not_change_brain(self):
        b=Brain.new(); before=copy.deepcopy(b.to_dict())
        p=plan_notes(b,[{'name':'记忆.md','text':'# 一个想法\n这是一段完整内容。'}])
        self.assertEqual((p['added'],p['skipped'],p['read_only']),(1,0,True))
        self.assertEqual(b.to_dict(),before)

    def test_repeat_import_and_manual_correction_do_not_overwrite(self):
        b=Brain.new(); files=[{'name':'a.md','text':'# 标题\n旧正文'}]
        first=import_notes(b,files); nid=first['ids'][0]
        b.update(nid,text='用户修正的正文')
        second=import_notes(b,files)
        self.assertEqual((second['added'],second['skipped']),(0,1))
        self.assertEqual(b.nodes[nid]['text'],'用户修正的正文')
        self.assertEqual(len(b.nodes),1)

    def test_changed_source_creates_new_record(self):
        b=Brain.new(); import_notes(b,[{'name':'a.md','text':'# 标题\n第一版'}])
        r=import_notes(b,[{'name':'a.md','text':'# 标题\n第二版'}])
        self.assertEqual(r['added'],1)
        self.assertEqual({n['text'] for n in b.nodes.values()},{'第一版','第二版'})

    def test_explicit_wikilinks_only_and_whole_file_mode(self):
        b=Brain.new(); r=import_notes(b,[{'name':'咖啡.md','text':'手冲需要耐心。'},
            {'name':'清晨.md','text':'今天读了[[咖啡|做法]]。'},
            {'name':'风筝.md','text':'完全不同的主题。'}],mode='whole')
        by_label={n['label']:n['id'] for n in b.nodes.values()}
        self.assertEqual(r['linked'],1)
        self.assertEqual(b.neighbors(by_label['风筝']),[])
        self.assertEqual(b.neighbors(by_label['清晨'])[0][0],by_label['咖啡'])
        self.assertTrue(all(not n['event_recorded'] for n in b.nodes.values()))

    def test_ambiguous_link_is_not_guessed(self):
        b=Brain.new(); r=import_notes(b,[{'name':'a.md','text':'# 重名\n甲'},
            {'name':'b.md','text':'# 重名\n乙'}, {'name':'c.md','text':'# 引用\n[[重名]]'}])
        self.assertEqual(r['linked'],0)

    def test_validation_and_capacity_preflight_do_not_partially_import(self):
        b=Brain.new(config=Config(max_nodes=1)); before=copy.deepcopy(b.to_dict())
        with self.assertRaises(ValidationError):import_notes(b,[{'name':'a.md','text':'# 一\n甲\n# 二\n乙'}])
        self.assertEqual(b.to_dict(),before)
        with self.assertRaises(ValidationError):import_notes(b,[{'name':'a.md','text':'# 一\n甲'}, {'name':'b.exe','text':'bad'}])
        self.assertEqual(b.to_dict(),before)

    def test_no_silent_drop_after_forty_paragraphs(self):
        text='\n\n'.join('笔记段落'+str(i) for i in range(50))
        self.assertEqual(len(split_markdown(text)),50)
        b=Brain.new(); self.assertEqual(import_notes(b,[{'name':'a.txt','text':text}])['added'],50)


class DesktopWriteTests(unittest.TestCase):
    setUp=fixtures.HTTPTests.setUp
    tearDown=fixtures.HTTPTests.tearDown
    request=fixtures.HTTPTests.request

    def test_update_preserves_identity_and_persists(self):
        old=copy.deepcopy(self.brain.nodes[self.first])
        status, result, _=self.request('POST','/api/update',{'id':self.first,'label':'已修正标题','text':'已修正正文','meta':{'important':True},'session_id':None})
        self.assertEqual(status,200,result)
        new=Brain.open(self.path).nodes[self.first]
        for key in ['id','created','recalls','reinforced']:self.assertEqual(new[key],old[key])
        self.assertEqual(new['text'],'已修正正文')
        self.assertTrue(new['important'])

    def test_import_preview_repeat_and_reopen(self):
        payload={'files':[{'name':'a.md','text':'# 导入标题\n完整内容'}]}
        disk=self.path.read_bytes(); memory=copy.deepcopy(self.brain.to_dict())
        status, preview, _=self.request('POST','/api/import/preview',payload)
        self.assertEqual(status,200,preview)
        self.assertEqual(self.path.read_bytes(),disk); self.assertEqual(self.brain.to_dict(),memory)
        status, result, _=self.request('POST','/api/import',payload)
        self.assertEqual((status,result['added']),(200,1))
        status, repeat, _=self.request('POST','/api/import',payload)
        self.assertEqual((status,repeat['added'],repeat['skipped']),(200,0,1))
        self.assertEqual(Brain.open(self.path).nodes[result['ids'][0]]['text'],'完整内容')

    def test_write_failures_roll_back_entire_batch_and_edit(self):
        disk=self.path.read_bytes(); memory=copy.deepcopy(self.brain.to_dict())
        with patch.object(self.brain,'persist',side_effect=OSError('temporary disk failure')):
            status,_,_=self.request('POST','/api/import',{'files':[{'name':'a.md','text':'# 一\n甲\n# 二\n乙'}]})
            self.assertEqual(status,500)
            self.assertEqual(self.brain.to_dict(),memory)
            self.assertEqual(self.request('POST','/api/update',{'id':self.first,'text':'不应留下'})[0],500)
        self.assertEqual(self.path.read_bytes(),disk);self.assertEqual(self.brain.to_dict(),memory)

    def test_invalid_input_is_rejected_before_any_write(self):
        before=self.path.read_bytes()
        cases=[('/api/import',{'files':[{'name':'a.md','text':3}]}),
               ('/api/import',{'files':[{'name':'a.md','text':'# 一\n甲'},{'name':'b.exe','text':'bad'}]}),
               ('/api/update',{'id':self.first,'created':0}),
               ('/api/update',{'id':self.first,'session_id':''}),
               ('/api/update',{'id':self.first,'meta':[]})]
        for route,payload in cases:
            with self.subTest(route=route,payload=payload):self.assertEqual(self.request('POST',route,payload)[0],400)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.request('POST','/api/update',{'id':'missing','text':'x'})[0],404)

    def test_opening_html_from_another_page_does_not_expose_api(self):
        headers={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
        self.assertEqual(self.request('GET','/',headers=headers)[0],200)
        self.assertEqual(self.request('GET','/api/graph',headers=headers)[0],403)
        headers['Sec-Fetch-Dest']='iframe'
        self.assertEqual(self.request('GET','/',headers=headers)[0],403)


if __name__=='__main__': unittest.main()

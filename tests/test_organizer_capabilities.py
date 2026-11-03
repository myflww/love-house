"""Capability discovery and model choices use only synthetic HTTP responses."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

from nkb import Brain
from nkb.errors import ValidationError
from nkb.organizer import get_profile, save_profile
from nkb.organizer.capabilities import (CapabilityError, NoRedirect, capabilities_for,
    discover_models, effective_limits, models_endpoint, normalize_models)
from nkb.organizer.model import call_model, OrganizerError, transport
from nkb.organizer.model import model_options
import nkb.organizer.capabilities as capability_module
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost

KEY='SYNTHETIC-CAPABILITY-KEY-NEVER-A-REAL-SECRET'
CATALOG={'object':'list','data':[{'id':'cap-test-model','name':'测试模型','context_window':1048576,
    'max_output_tokens':393216,'effort':{'supported_levels':['low','high','max'],'default_level':'high'}}]}


class CapabilityTests(unittest.TestCase):
    def test_normalization_keeps_only_public_capabilities_and_never_echoes_key(self):
        raw=deepcopy(CATALOG);raw['secret']=KEY;raw['data'][0]['api_key']=KEY
        raw['data'].append({'id':KEY,'name':KEY})
        values=normalize_models(raw,secret=KEY)
        self.assertEqual(values,CATALOG['data'])
        self.assertNotIn(KEY,json.dumps(values))
        self.assertNotIn('api_key',json.dumps(values))

    def test_discovery_uses_get_and_caches_only_capabilities(self):
        base='https://cap-test.example/v1'
        captured=[]
        def send(request,*,timeout):
            captured.append(request)
            self.assertEqual(timeout,30)
            return CATALOG
        result=discover_models(base,KEY,send=send)
        self.assertEqual(captured[0].full_url,base+'/models')
        self.assertEqual(captured[0].get_method(),'GET')
        self.assertEqual(captured[0].get_header('Authorization'),'Bearer '+KEY)
        self.assertEqual(result['models'],CATALOG['data'])
        profile={'base_url':base,'model':'cap-test-model'}
        self.assertEqual(capabilities_for(profile),CATALOG['data'][0])
        self.assertEqual(effective_limits(profile),{'context_window':1048576,
            'max_output_tokens':393216,'max_input_chars':0})
        self.assertNotIn(KEY,json.dumps(result))

    def test_unsafe_urls_and_redirects_never_forward_credentials(self):
        for base in ('http://public.example/v1','https://'+'user:pass'+'@example.test/v1',
            'https://example.test/v1?key='+KEY,'https://example.test/connections/a/v1'):
            with self.subTest(base=base),self.assertRaises(ValidationError):models_endpoint(base)
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.test'))
        error=HTTPError('https://example.test',302,KEY,{},io.BytesIO(KEY.encode()))
        with self.assertRaises(CapabilityError) as caught:
            discover_models('https://redirect-models.example',KEY,send=Mock(side_effect=error))
        self.assertEqual(caught.exception.code,'redirect_blocked')
        self.assertNotIn(KEY,str(caught.exception))

    def test_auto_migrates_legacy_default_but_preserves_explicit_new_limits(self):
        brain=Brain.new();brain.meta['organizer_profile']={'max_input_chars':18000}
        self.assertEqual(get_profile(brain)['max_input_chars'],0)
        saved=save_profile(brain,max_input_chars=18000,max_output_tokens=8192,reasoning_effort='high')
        self.assertEqual(get_profile(brain),saved)
        self.assertEqual(saved['max_input_chars'],18000)
        self.assertEqual(saved['context_window'],0)
        for field in ('max_input_chars','context_window','max_output_tokens'):
            with self.assertRaises(ValidationError):save_profile(brain,**{field:-1})
        with self.assertRaises(ValidationError):save_profile(brain,context_window=8192,max_output_tokens=8192)
        limits=effective_limits({'base_url':'https://api.deepseek.com','model':'deepseek-flash','context_window':8192})
        self.assertEqual(limits['max_output_tokens'],4096)

    def test_explicit_deepseek_efforts_and_output_choices_reach_the_request(self):
        for effort in ('auto','none','low','high','max'):
            with self.subTest(effort=effort):
                requests=[]
                def send(request,**_kwargs):
                    requests.append(json.loads(request.data))
                    return {'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]}
                call_model({'base_url':'https://api.deepseek.com/v1','model':'deepseek-flash',
                    'reasoning_effort':effort,'max_output_tokens':8192},KEY,{},send=send)
                data=requests[0];self.assertEqual(data['max_tokens'],8192)
                if effort=='auto':self.assertNotIn('thinking',data)
                elif effort=='none':
                    self.assertEqual(data['thinking'],{'type':'disabled'})
                    self.assertNotIn('reasoning_effort',data)
                else:
                    self.assertEqual(data['thinking'],{'type':'enabled'})
                    self.assertEqual(data['reasoning_effort'],effort)
        for settings,code in (({'reasoning_effort':'medium'},'unsupported_effort'),
            ({'max_output_tokens':393217},'invalid_output_limit')):
            with self.assertRaises(OrganizerError) as caught:
                call_model({'base_url':'https://api.deepseek.com','model':'deepseek-flash',**settings},KEY,{},send=Mock())
            self.assertEqual(caught.exception.code,code)

    def test_large_legal_json_and_reasoning_are_not_limited_to_old_megabyte(self):
        content=json.dumps({'value':'原文'*600000},ensure_ascii=False)
        response={'choices':[{'message':{'content':content,'reasoning_content':'PRIVATE-REASONING'*100000},'finish_reason':'stop'}]}
        encoded=json.dumps(response,ensure_ascii=False).encode()
        opener=Mock();opener.open.return_value.__enter__=Mock(return_value=io.BytesIO(encoded))
        opener.open.return_value.__exit__=Mock(return_value=False)
        with patch('nkb.organizer.model.urllib.request.build_opener',return_value=opener):
            parsed=transport(Request('https://cap-test.example'),timeout=300)
        result=call_model({'base_url':'https://api.deepseek.com','model':'deepseek-flash'},KEY,{},send=lambda *_a,**_k:parsed)
        self.assertEqual(result['value'],'原文'*600000)
        self.assertNotIn('PRIVATE-REASONING',json.dumps(result))

    def test_context_error_is_classified_by_safe_code_only(self):
        raw=json.dumps({'error':{'code':'context_length_exceeded','message':KEY}}).encode()
        error=HTTPError('https://example.test',400,KEY,{},io.BytesIO(raw))
        with self.assertRaises(OrganizerError) as caught:
            call_model({'base_url':'https://example.test','model':'test'},KEY,{},send=Mock(side_effect=error))
        self.assertEqual(caught.exception.code,'context_length_exceeded')
        self.assertNotIn(KEY,str(caught.exception))


class CapabilityHostTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.host=MemoryHost(Path(self.temp.name),key_store=KeyStore(allow_keychain=False))
        self.host.organizer.stop()
    def tearDown(self):self.host.stop();self.temp.cleanup()
    def configure(self):
        self.host.organizer_settings('default',{'provider_mode':'separate','base_url':'https://cap-host.example/v1',
            'model':'cap-test-model','api_key':KEY,'save_key':False})
    def test_current_library_form_uses_saved_key_and_returns_no_credentials(self):
        self.configure()
        with patch('nkb.organizer.capabilities.models_transport',return_value=CATALOG) as send:
            result=self.host.organizer_models('default',{'provider_mode':'separate','model':'cap-test-model'})
        self.assertEqual(send.call_args.args[0].get_header('Authorization'),'Bearer '+KEY)
        self.assertNotIn(KEY,json.dumps(result))
        self.assertEqual(self.host.organizer_view('default')['model_capabilities'],CATALOG['data'][0])
    def test_changed_endpoint_cannot_take_saved_key_to_another_host(self):
        self.configure()
        with patch('nkb.organizer.capabilities.models_transport') as send:
            with self.assertRaises(CapabilityError):
                self.host.organizer_models('default',{'provider_mode':'separate','base_url':'https://foreign.example/v1'})
        send.assert_not_called()
    def test_other_library_connection_cannot_supply_model_credentials(self):
        other=self.host.manager.create_library('另一记忆库')['id']
        connection=self.host.new_connection({'name':'另一库API','host':'api','library_id':other,
            'provider':{'base_url':'https://foreign.example','model':'x','api_key':KEY,'save_key':False}})
        with patch('nkb.organizer.capabilities.models_transport') as send:
            with self.assertRaises(ValidationError):
                self.host.organizer_models('default',{'provider_mode':'connection','connection_id':connection['connection']['id']})
        send.assert_not_called()
    def test_connection_mode_ignores_hidden_separate_model_field(self):
        connection=self.host.new_connection({'name':'本库API','host':'api','library_id':'default',
            'provider':{'base_url':'https://cap-host.example','model':'cap-test-model','api_key':KEY,'save_key':False}})
        with patch('nkb.organizer.capabilities.models_transport',return_value=CATALOG):
            result=self.host.organizer_models('default',{'provider_mode':'connection',
                'connection_id':connection['connection']['id'],'model':'SHOULD-NOT-OVERRIDE'})
        self.assertEqual(result['selected_model'],'cap-test-model')
    def test_custom_capabilities_survive_restart_without_keys_or_memory(self):
        self.configure()
        self.host.transact('default',lambda brain:brain.add('私人记忆','PRIVATE-MEMORY-MUST-NOT-BE-IN-CAPABILITY-CACHE'))
        raw=deepcopy(CATALOG);raw['data'][0]['api_key']=KEY
        raw['data'].append({'id':KEY,'name':KEY})
        with patch('nkb.organizer.capabilities.models_transport',return_value=raw):
            self.host.organizer_models('default',{'provider_mode':'separate'})
        cache=Path(self.temp.name)/'model-capabilities.json'
        content=cache.read_text(encoding='utf-8')
        self.assertNotIn(KEY,content)
        self.assertNotIn('PRIVATE-MEMORY',content)
        self.assertNotIn('api_key',content)
        self.host.stop()
        with patch.dict(capability_module._CATALOGS,{},clear=True):
            self.host=MemoryHost(Path(self.temp.name),key_store=KeyStore(allow_keychain=False))
            self.host.organizer.stop()
            view=self.host.organizer_view('default')
            self.assertEqual(view['model_capabilities'],CATALOG['data'][0])
            self.assertEqual(model_options(view['settings'])['max_tokens'],393216)


if __name__=='__main__':unittest.main()

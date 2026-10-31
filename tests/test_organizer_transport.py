"""Bounded organizer transport with synthetic credentials and no network calls."""
from __future__ import annotations

import json
import socket
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from nkb.errors import ValidationError
from nkb.organizer.model import NoRedirect, OrganizerError, call_model, transport
from nkb.organizer.rules import SYSTEM_GUIDANCE


KEY = 'FAKE-ORGANIZER-TRANSPORT-KEY-NOT-A-REAL-SECRET'
PAYLOAD = {'version': 1, 'raw': [{'id': 'synthetic-one', 'text': '测试原话：周六一起看海。'}]}
RESULT = {'version': 1, 'operations': []}


def profile(base='https://api.deepseek.com/v1', model='deepseek-flash'):
    return {'base_url': base, 'model': model}


def response(content=None, *, finish='stop'):
    return {'choices': [{'message': {'content': json.dumps(RESULT) if content is None else content},
                         'finish_reason': finish}]}


class OrganizerTransportTests(unittest.TestCase):
    def request_data(self, settings=None, credential=KEY, reply=None):
        captured = []
        def send(request, *, timeout):
            captured.append((request, timeout))
            return response() if reply is None else reply
        result = call_model(settings or profile(), credential, PAYLOAD, send=send)
        self.assertEqual(result, RESULT)
        self.assertEqual(len(captured), 1)
        request, timeout = captured[0]
        self.assertEqual(timeout, 45)
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Authorization'), 'Bearer '+KEY)
        self.assertNotIn(KEY.encode(), request.data)
        return request, json.loads(request.data)

    def test_official_supported_models_disable_thinking_but_keep_bounded_json_contract(self):
        for model in ('deepseek-flash', 'deepseek-v4-pro', 'deepseek-chat'):
            for base in ('https://api.deepseek.com', 'https://api.deepseek.com/v1',
                         'https://API.DEEPSEEK.COM:443/v1/chat/completions'):
                with self.subTest(model=model, base=base):
                    request, data = self.request_data(profile(base, model))
                    self.assertTrue(request.full_url.endswith('/chat/completions'))
                    self.assertEqual(data['model'], model)
                    self.assertEqual(data['thinking'], {'type': 'disabled'})
                    self.assertFalse(data['stream'])
                    self.assertEqual(data['max_tokens'], 4096)
                    self.assertEqual(data['response_format'], {'type': 'json_object'})
                    self.assertEqual(data['messages'][0], {'role': 'system', 'content': SYSTEM_GUIDANCE})
                    self.assertEqual(data['messages'][1]['role'], 'user')
                    self.assertEqual(json.loads(data['messages'][1]['content']), PAYLOAD)

    def test_compatible_gateways_lookalike_hosts_and_local_servers_keep_original_schema(self):
        for base in ('https://compatible-provider.example/v1', 'https://api.deepseek.com.example/v1',
                     'https://deepseek.com/v1', 'https://api.deepseek.com./v1',
                     'https://api.deepseek.com:8443/v1', 'http://127.0.0.1:18321/v1'):
            with self.subTest(base=base):
                _, data = self.request_data(profile(base))
                self.assertNotIn('thinking', data)
                self.assertEqual(set(data), {'model', 'messages', 'stream', 'max_tokens', 'response_format'})

    def test_unknown_or_reasoning_only_models_do_not_receive_vendor_toggle(self):
        for model in ('deepseek-reasoner', 'deepseek-flash-custom', 'vendor/deepseek-flash',
                      'DEEPSEEK-FLASH', 'unknown-model'):
            with self.subTest(model=model):
                _, data = self.request_data(profile(model=model))
                self.assertNotIn('thinking', data)

    def test_runtime_credential_endpoint_and_model_are_the_only_resolved_vendor_boundary(self):
        _, enabled = self.request_data(profile('https://another-provider.example/v1', 'another-model'),
            {'api_key': KEY, 'base_url': 'https://api.deepseek.com/v1', 'model': 'deepseek-flash'})
        self.assertEqual(enabled['thinking'], {'type': 'disabled'})
        for overrides in ({'base_url': 'https://another-provider.example/v1'}, {'model': 'another-model'},
                          {'base_url': 'http://localhost:18321/v1', 'model': 'deepseek-flash'}):
            with self.subTest(overrides=overrides):
                _, data = self.request_data(profile(), {'api_key': KEY, **overrides})
                self.assertNotIn('thinking', data)

    def test_invalid_or_credential_bearing_endpoints_fail_without_transport(self):
        for base in ('http://api.deepseek.com/v1', 'https://'+KEY+'@api.deepseek.com/v1',
                     'https://api.deepseek.com/v1?key='+KEY, 'https://api.deepseek.com/v1#api-key'):
            with self.subTest(base=base):
                send = Mock(side_effect=AssertionError('No network request is permitted'))
                with self.assertRaises(ValidationError) as caught:
                    call_model(profile(), {'api_key': KEY, 'base_url': base}, PAYLOAD, send=send)
                send.assert_not_called()
                self.assertNotIn(KEY, str(caught.exception))

    def test_missing_or_invalid_credentials_and_model_still_fail_before_send(self):
        for credential, settings, expected in [('', profile(), 'missing_credential'),
                (KEY+'\ninvalid', profile(), 'invalid_credential'),
                ({'api_key': KEY, 'model': ''}, profile(), 'missing_model')]:
            with self.subTest(code=expected):
                send = Mock()
                with self.assertRaises(OrganizerError) as caught:
                    call_model(settings, credential, PAYLOAD, send=send)
                self.assertEqual(caught.exception.code, expected)
                send.assert_not_called()

    def test_length_finish_is_rejected_even_if_returned_content_looks_like_valid_json(self):
        with self.assertRaises(OrganizerError) as caught:
            call_model(profile(), KEY, PAYLOAD, send=lambda *_args, **_kwargs: response(finish='length'))
        self.assertEqual(caught.exception.code, 'truncated_output')

    def test_private_reasoning_is_ignored_and_only_final_json_is_read(self):
        reply = response()
        reply['choices'][0]['message']['reasoning_content'] = 'PRIVATE-REASONING-NOT-MEMORY'
        _, data = self.request_data(reply=reply)
        self.assertNotIn('PRIVATE-REASONING-NOT-MEMORY', json.dumps(data))

    def test_malformed_chat_response_is_output_failure_rather_than_network_failure(self):
        for reply in ({}, {'choices': []}, {'choices': [{'message': {}}]}, {'choices': 'invalid'}):
            with self.subTest(reply=reply):
                with self.assertRaises(OrganizerError) as caught:
                    call_model(profile(), KEY, PAYLOAD, send=lambda *args, **kwargs: reply)
                self.assertEqual(caught.exception.code, 'invalid_output')

    def test_invalid_secret_echo_or_oversized_output_still_cannot_be_applied(self):
        for content, expected in ((42, 'invalid_output'), ('x'*100001, 'invalid_output'),
                                  (json.dumps({'leak': KEY}), 'invalid_output'), ('invalid JSON', 'invalid_output')):
            with self.subTest(expected=expected, content_type=type(content).__name__):
                with self.assertRaises(OrganizerError) as caught:
                    call_model(profile(), KEY, PAYLOAD,
                               send=lambda *_args, content=content, **_kwargs: response(content))
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn(KEY, str(caught.exception))

    def test_existing_http_timeout_and_connection_error_codes_remain_sanitized(self):
        for error, expected in ((HTTPError('https://example.invalid', 302, KEY, {}, None), 'redirect_blocked'),
                               (HTTPError('https://example.invalid', 401, KEY, {}, None), 'provider_authentication'),
                               (TimeoutError(KEY), 'timeout'), (socket.timeout(KEY), 'timeout'),
                               (URLError(KEY), 'provider_error')):
            with self.subTest(expected=expected):
                with self.assertRaises(OrganizerError) as caught:
                    call_model(profile(), KEY, PAYLOAD, send=Mock(side_effect=error))
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn(KEY, str(caught.exception))

    def test_response_byte_budget_and_redirect_handler_still_fail_closed(self):
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=Mock(read=Mock(return_value=b'x'*(1024*1024+1))))
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch('nkb.organizer.model.urllib.request.build_opener', return_value=opener):
            with self.assertRaises(OrganizerError) as caught:
                transport(Request('https://example.invalid'), timeout=45)
        self.assertEqual(caught.exception.code, 'invalid_output')
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.invalid'))


if __name__ == '__main__':
    unittest.main()

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from product_content_platform.studio.azure import AzureServiceError, AzureServices
from product_content_platform.studio.copywriting import CopyPlan, CopyPreparationError, copy_directive, prepare_copy, validate_copy


class CopywritingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / 'reference.png'
        Image.new('RGB',(32,32),'blue').save(self.image)
        self.request = {'enabled':True,'purpose':'marketing','title':'','body':'','facts':[],'market':'domestic_zh','kind':'generate'}
        self.package = {'copy_request':self.request,'references':[{'role':'product','path':str(self.image),'media_type':'image/png'}],'requested_output':{'width':1024,'height':1024},'prompt':'Preserve the original product.'}
        self.plan = {'lines':[{'role':'title','text':'外观细节','basis':'neutral'},{'role':'label','text':'蓝色外观','basis':'visual','evidence':'图 1 表面为蓝色','reference_indices':[1]}]}
        self.approved = {'approved':True,'issues':[]}

    def tearDown(self):
        self.temp.cleanup()

    def responder(self, *items):
        return Mock(side_effect=[json.dumps(item,ensure_ascii=False) for item in items])

    def services(self, responder):
        service = AzureServices.__new__(AzureServices)
        service.endpoint = 'https://test.openai.azure.com/openai/v1/images/edits'
        service.model = 'image-test'
        service.json_response = responder
        service.auth_headers = Mock(return_value={'api-key':'fixture'})
        return service

    def response(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'data':[{'b64_json':base64.b64encode(self.image.read_bytes()).decode()}]}).encode()
        return response

    def test_approved_copy_is_reused_without_repeating_llm_calls(self):
        responder = self.responder(self.plan,self.approved)
        first = prepare_copy(self.package,self.root,responder)
        second = prepare_copy(self.package,self.root,responder)
        self.assertEqual(first,second)
        self.assertEqual(2,responder.call_count)

    def test_changed_evidence_cannot_reuse_old_approval(self):
        prepare_copy(self.package,self.root,self.responder(self.plan,self.approved))
        Image.new('RGB',(32,32),'red').save(self.image)
        with self.assertRaisesRegex(CopyPreparationError,'不一致'):
            prepare_copy(self.package,self.root,Mock())

    def test_background_skips_copy_models_and_locks_empty_text(self):
        self.request['enabled'] = False
        responder = Mock(side_effect=AssertionError('textless image should not call a copy model'))
        plan = prepare_copy(self.package,self.root,responder)
        self.assertEqual([],plan.lines)
        self.assertIn('清单为空时不添加任何营销文字',copy_directive(plan))

    def test_invalid_fact_and_reference_numbers_are_rejected(self):
        for patch_line in [dict(basis='fact',fact_indices=[1]),dict(basis='visual',reference_indices=[2])]:
            raw = {'lines':[self.plan['lines'][0],{**self.plan['lines'][1],**patch_line}]}
            with self.assertRaises(CopyPreparationError):
                validate_copy(CopyPlan.model_validate(raw),self.request,1)

    def test_explicit_title_cannot_be_silently_rewritten(self):
        self.request['title']='用户写的标题'
        with self.assertRaisesRegex(CopyPreparationError,'保留本图标题'):
            validate_copy(CopyPlan.model_validate(self.plan),self.request,1)

    def test_explicit_body_cannot_be_silently_removed(self):
        self.request['body']='用户写的正文'
        with self.assertRaisesRegex(CopyPreparationError,'保留本图正文'):
            validate_copy(CopyPlan.model_validate(self.plan),self.request,1)

    def test_rejected_claim_never_sends_an_image_request(self):
        reject={'approved':False,'issues':['不能由静态图片证明操作灵敏']}
        responder=self.responder(self.plan,reject,self.plan,reject)
        service=self.services(responder)
        with patch('urllib.request.urlopen') as send:
            with self.assertRaisesRegex(AzureServiceError,'尚未调用生图') as raised:
                service.generate(self.package,self.root)
        self.assertTrue(raised.exception.outcome_known)
        self.assertFalse((self.root/'approved-copy.json').exists())
        send.assert_not_called()

    def test_copy_service_failure_is_known_and_does_not_send_image(self):
        service=self.services(Mock(side_effect=RuntimeError('unavailable')))
        with patch('urllib.request.urlopen') as send:
            with self.assertRaises(AzureServiceError) as raised:
                service.generate(self.package,self.root)
        self.assertTrue(raised.exception.outcome_known)
        send.assert_not_called()

    def test_only_approved_copy_is_sent_and_receipt_survives_recovery(self):
        responder=self.responder(self.plan,self.approved)
        service=self.services(responder)
        with patch('urllib.request.urlopen',return_value=self.response()) as send:
            result=service.generate(self.package,self.root)
        payload=send.call_args.args[0].data.decode('utf-8',errors='ignore')
        self.assertIn('最终文字清单',payload)
        self.assertIn('只能逐字绘制',payload)
        self.assertEqual('蓝色外观',result['provenance']['copy_plan']['lines'][1]['text'])
        service.json_response=Mock(side_effect=AssertionError('must reuse received response'))
        with patch('urllib.request.urlopen',side_effect=AssertionError('must not repeat a received image')):
            recovered=service.generate(self.package,self.root)
        self.assertEqual(result,recovered)

    def test_failed_draft_can_be_corrected_before_any_image_charge(self):
        reject={'approved':False,'issues':['待修改']}
        responder=self.responder(self.plan,reject,self.plan,self.approved)
        self.assertEqual(2,len(prepare_copy(self.package,self.root,responder).lines))
        self.assertEqual(4,responder.call_count)

    def test_non_text_ai_edit_can_preserve_an_empty_text_list(self):
        self.request.update(kind='ai_edit',allow_empty=True,edit_instruction='只调整光线')
        empty={'lines':[]}
        self.assertEqual([],prepare_copy(self.package,self.root,self.responder(empty,self.approved)).lines)

    def test_copy_receipt_write_failure_stops_before_image_submission(self):
        service=self.services(self.responder(self.plan,self.approved))
        with patch.object(Path,'write_text',side_effect=OSError('disk full')), patch('urllib.request.urlopen') as send:
            with self.assertRaises(AzureServiceError) as raised:
                service.generate(self.package,self.root)
        self.assertTrue(raised.exception.outcome_known)
        send.assert_not_called()

    def test_repair_rechecks_evidence_without_replanning_approved_text(self):
        self.plan['lines'][0]['text'] = '用户在 AI 修改中确定的标题'
        self.request.update(kind='repair', source_copy=self.plan, allow_empty=True)
        responder = self.responder(self.approved)
        plan = prepare_copy(self.package, self.root, responder)
        self.assertEqual(self.plan['lines'][0]['text'], plan.lines[0].text)
        self.assertEqual(1, responder.call_count)
        self.assertIn('独立核验候选文案', responder.call_args.args[0][0]['content'])

    def test_repair_stops_if_existing_copy_loses_fact_approval(self):
        self.request.update(kind='repair', source_copy=self.plan, allow_empty=True)
        responder = self.responder({'approved':False,'issues':['参考图不足以支持这项特点']})
        service = self.services(responder)
        with patch('urllib.request.urlopen') as send:
            with self.assertRaisesRegex(AzureServiceError, '参考图不足以支持') as raised:
                service.generate(self.package, self.root)
        self.assertTrue(raised.exception.outcome_known)
        self.assertEqual(1, responder.call_count)
        send.assert_not_called()

    def test_copy_service_http_errors_are_actionable_without_provider_body(self):
        service = AzureServices.__new__(AzureServices)
        service.review_endpoint = 'https://test.openai.azure.com/openai/v1/responses'
        service.review_token_provider = None
        for status in [400, 401, 403, 404, 429]:
            with self.subTest(status=status):
                error = RuntimeError(f'HTTP {status}: secret-token and private prompt')
                with patch('product_content_platform.studio.azure.call_azure_chat_review', side_effect=error):
                    with self.assertRaisesRegex(RuntimeError, f'HTTP {status}') as raised:
                        service.json_response([])
                self.assertNotIn('secret-token', str(raised.exception))
                self.assertNotIn('private prompt', str(raised.exception))


if __name__=='__main__':
    unittest.main()

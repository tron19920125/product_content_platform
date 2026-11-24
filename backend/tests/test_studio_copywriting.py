from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from product_content_platform.studio.azure import AzureServiceError, AzureServices
from product_content_platform.studio.catalog import DraftContent, Tool
from product_content_platform.studio.copywriting import CopyPlan, CopyPreparationError, copy_directive, prepare_copy, validate_copy
from product_content_platform.studio.creations import Creations
from product_content_platform.studio.execution import package_job, package_review
from product_content_platform.studio.quality import Finding, Review
from product_content_platform.studio.settings import StudioSettings
from product_content_platform.studio.workspace import StudioWorkspace


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
        plan = prepare_copy(self.package,self.root,responder).plan
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
        self.assertEqual(2,len(prepare_copy(self.package,self.root,responder).plan.lines))
        self.assertEqual(4,responder.call_count)

    def test_non_text_ai_edit_can_preserve_an_empty_text_list(self):
        self.request.update(kind='ai_edit',allow_empty=True,edit_instruction='只调整光线')
        empty={'lines':[]}
        self.assertEqual([],prepare_copy(self.package,self.root,self.responder(empty,self.approved)).plan.lines)

    def test_copy_receipt_write_failure_stops_before_image_submission(self):
        service=self.services(self.responder(self.plan,self.approved))
        with patch.object(Path,'write_text',side_effect=OSError('disk full')), patch('urllib.request.urlopen') as send:
            with self.assertRaises(AzureServiceError) as raised:
                service.generate(self.package,self.root)
        self.assertTrue(raised.exception.outcome_known)
        send.assert_not_called()

    def test_repair_rechecks_evidence_without_replanning_approved_text(self):
        self.plan['lines'][0]['text'] = '用户在 AI 修改中确定的标题'
        self.plan['visual_instruction'] = '上一轮标题再缩小一档'
        self.request.update(kind='repair', source_copy=self.plan, allow_empty=True)
        responder = self.responder(self.approved)
        plan = prepare_copy(self.package, self.root, responder).plan
        self.assertEqual(self.plan['lines'][0]['text'], plan.lines[0].text)
        self.assertEqual('', plan.visual_instruction)
        self.assertNotIn(self.plan['visual_instruction'], json.dumps(responder.call_args.args[0], ensure_ascii=False))
        self.assertEqual(1, responder.call_count)
        self.assertIn('独立核验候选文案', responder.call_args.args[0][0]['content'])

    def test_repair_stops_if_existing_copy_loses_fact_approval(self):
        self.request.update(kind='repair', source_copy=self.plan, allow_empty=True)
        responder = self.responder({'approved':False,'failure_kind':'facts','issues':['参考图不足以支持这项特点。']})
        service = self.services(responder)
        with patch('urllib.request.urlopen') as send:
            with self.assertRaisesRegex(AzureServiceError, '补充商品事实与来源或清晰参考图') as raised:
                service.generate(self.package, self.root)
        self.assertTrue(raised.exception.outcome_known)
        self.assertNotIn('。。', str(raised.exception))
        self.assertEqual(1, responder.call_count)
        send.assert_not_called()

    def test_layout_conflict_has_localized_action_without_repeated_punctuation(self):
        self.request.update(kind='ai_edit', source_copy=self.plan, edit_instruction='缩小字号并保持当前字号')
        reject = {'approved':False, 'failure_kind':'scope', 'issues':['visual_instruction 和当前要求冲突。 。']}
        service = self.services(self.responder(self.plan, reject, self.plan, reject))
        with patch('urllib.request.urlopen') as send:
            with self.assertRaisesRegex(AzureServiceError, '修改范围或排版要求存在冲突') as raised:
                service.generate(self.package, self.root)
        message = str(raised.exception)
        self.assertIn('在图片详情', message)
        self.assertIn('当前选图仍可使用', message)
        for unexpected in ('visual_instruction', '。。', '。 。', '补充商品事实'):
            self.assertNotIn(unexpected, message)
        self.assertTrue(raised.exception.outcome_known)
        send.assert_not_called()

    def test_edit_cannot_add_product_claim_without_evidence(self):
        self.request.update(kind='ai_edit', edit_instruction='在标题添加「支持 99.9% 杀菌」')
        unsubstantiated = {'lines':[{'role':'title', 'text':'支持 99.9% 杀菌', 'basis':'fact'}]}
        service = self.services(self.responder(unsubstantiated, unsubstantiated))
        with patch('urllib.request.urlopen') as send:
            with self.assertRaisesRegex(AzureServiceError, '补充商品事实与来源或清晰参考图') as raised:
                service.generate(self.package, self.root)
        self.assertNotIn('排版要求存在冲突', str(raised.exception))
        send.assert_not_called()

    def test_scope_audit_can_remove_a_conflicting_suggestion_before_sending_image(self):
        suggestion = '再缩小字号。'
        self.request.update(kind='repair', edit_instruction='保留字号，只换字体。', review_actions=[suggestion])
        reject = {'approved':False, 'failure_kind':'scope', 'issues':['建议会修改用户要求保留的字号。']}
        service = self.services(self.responder({'keep':[1]}, self.plan, reject, self.plan, self.approved))
        with patch('urllib.request.urlopen', return_value=self.response()) as send:
            result = service.generate(self.package, self.root)
        self.assertEqual([], result['provenance']['edit_scope']['review_actions'])
        self.assertNotIn(suggestion, send.call_args.args[0].data.decode('utf-8', errors='ignore'))

    def test_aplus_typography_edit_and_repair_use_current_image_and_compatible_actions(self):
        workspace = StudioWorkspace(StudioSettings(self.root / 'workspace'))
        creations = Creations(workspace)
        product = workspace.upload_image('product.png', 'product', self.image.read_bytes())
        current_file = self.root / 'current.png'
        Image.new('RGB', (32, 32), 'grey').save(current_file)
        current_asset = workspace.upload_image('current.png', 'style', current_file.read_bytes())
        draft = workspace.create_draft(Tool.A_PLUS)
        content = draft['content']
        old_layout = '上一轮再缩小字号一档并增加留白'
        content.update(product_asset_ids=[product['id']], requirements='整组增加旧留白', facts=[
            {'name':'容量', 'value':'10 kg', 'source':'规格书第 2 页'},
        ])
        page = content['pages'][0]
        page.update(title='旧版标题', visual_goal='旧模块要求缩小标题字号')
        draft = workspace.save_draft(draft['id'], DraftContent.model_validate(content), expected_revision=draft['revision'])
        submit = {'expected_revision':draft['revision'], 'mode':'codex', 'page_ids':[page['id']]}
        original = creations.submit(draft['id'], submit_key='first', **submit)
        conflicting = '再缩小标题字号 15%，并增加标题左侧留白。'
        compatible = '标题字距略微收紧。'
        instruction = '保持当前字号、位置和留白，只改标题字体、字重和字距。'
        existing = {'lines':[{'role':'title','text':'容量 10 kg','basis':'fact','evidence':'规格书第 2 页','fact_indices':[1]}]}
        version = creations.complete(creations.claim(original['id'])['id'], asset_id=current_asset['id'],
                                     review=Review(status='completed', findings=[
                                         Finding(kind='suggestion', message='字号与留白', action=conflicting),
                                         Finding(kind='suggestion', message='字距', action=compatible),
                                     ]), provenance={'copy_plan':{**existing, 'visual_instruction':old_layout}})

        for kind in ('ai_edit', 'repair'):
            with self.subTest(kind=kind):
                if kind == 'repair':
                    operation = creations.repair(version['id'], submit_key=kind, instruction=instruction)
                else:
                    operation = creations.submit(draft['id'], submit_key=kind, source_version_id=version['id'],
                                                 instruction=instruction, review_actions=[conflicting, compatible], **submit)
                job = creations.claim(operation['id'])
                package = package_job(job, workspace)
                self.assertEqual(current_asset['id'], package['references'][0]['asset_id'])
                responder = self.responder({'keep':[2]}, {**existing, 'visual_instruction':old_layout}, self.approved)
                service = self.services(responder)
                with patch('urllib.request.urlopen', return_value=self.response()) as send:
                    result = service.generate(package, self.root / kind)
                payload = send.call_args.args[0].data.decode('utf-8', errors='ignore')
                self.assertIn(current_file.read_bytes(), send.call_args.args[0].data)
                self.assertIn(instruction, payload)
                self.assertIn(compatible, payload)
                self.assertIn('容量 10 kg', payload)
                self.assertIn('规格书第 2 页', payload)
                audit_inputs = '\n'.join(part['text'] for part in responder.call_args.args[0][1]['content'] if part['type'] == 'text')
                self.assertIn(instruction, audit_inputs)
                self.assertIn(compatible, audit_inputs)
                self.assertIn('"fact_indices": [1]', audit_inputs)
                for retired in (old_layout, conflicting, content['requirements'], page['title'], page['visual_goal']):
                    self.assertNotIn(retired, payload)
                    self.assertNotIn(retired, audit_inputs)
                revised = creations.complete(job['id'], asset_id=current_asset['id'], review=Review(), provenance=result['provenance'])
                review_brief = package_review({'id':'r', 'attempt':1, 'version':revised}, workspace)['brief']
                self.assertEqual([compatible], review_brief['review_actions'])
                self.assertNotIn('visual_goal', review_brief)
                self.assertEqual(version['id'], creations.snapshot(draft['id'])['selections'][0]['version_id'])

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

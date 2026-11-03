from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from product_content_platform.studio.azure import AzureServices
from product_content_platform.studio.briefs import PURPOSE_DIRECTIONS
from product_content_platform.studio.catalog import A_PLUS_PURPOSES, SUITE_PURPOSES, DraftContent, Tool
from product_content_platform.studio.creations import Creations
from product_content_platform.studio.execution import package_job, package_review
from product_content_platform.studio.quality import Review
from product_content_platform.studio.settings import StudioSettings
from product_content_platform.studio.workspace import StudioWorkspace


class BriefTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = StudioWorkspace(StudioSettings(Path(self.temp.name)))
        self.creations = Creations(self.workspace)
        image = io.BytesIO()
        Image.new('RGB', (32, 32), 'white').save(image, 'PNG')
        self.product = self.workspace.upload_image('product.png', 'product', image.getvalue())
        self.draft = self.workspace.create_draft(Tool.ECOM_SUITE)
        self.draft['content']['product_asset_ids'] = [self.product['id']]
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.draft = self.workspace.save_draft(self.draft['id'], DraftContent.model_validate(self.draft['content']), expected_revision=self.draft['revision'])

    def job(self, index=0, **kwargs):
        operation = self.creations.submit(self.draft['id'], submit_key=f'job-{self.draft["revision"]}-{index}', expected_revision=self.draft['revision'], mode='codex', page_ids=[self.draft['content']['pages'][index]['id']], **kwargs)
        return self.creations.claim(operation['id'])

    def review_package(self, index=2):
        job = self.job(index)
        version = self.creations.complete(job['id'], asset_id=self.product['id'], review=Review(), provenance={})
        return package_review({'id':'review', 'attempt':1, 'version':version}, self.workspace)

    def test_all_catalog_purposes_have_distinct_direction(self):
        self.assertEqual(set(SUITE_PURPOSES) | set(A_PLUS_PURPOSES), set(PURPOSE_DIRECTIONS))
        self.assertEqual(len(PURPOSE_DIRECTIONS), len(set(PURPOSE_DIRECTIONS.values())))

    def test_default_suite_defines_different_layout_and_copy_tasks(self):
        prompts = []
        for index in range(3):
            job = self.job(index)
            prompts.append(package_job(job, self.workspace)['prompt'])
            self.creations.complete(job['id'], asset_id=self.product['id'], review=Review(), provenance={})
        self.assertIn('商品占主要视觉面积', prompts[0])
        self.assertIn('中远景', prompts[1])
        self.assertIn('不自动套用营销主图的大标题', prompts[1])
        self.assertIn('局部放大', prompts[2])
        self.assertIn('禁止只用', prompts[2])

    def test_whole_suite_carries_sibling_roles_even_for_parallel_jobs(self):
        operation = self.creations.submit(self.draft['id'], submit_key='all', expected_revision=self.draft['revision'], mode='codex')
        prompt = package_job(self.creations.claim(operation['id']), self.workspace)['prompt']
        self.assertIn('整组分工', prompt)
        for label in ['营销主图', '场景图', '卖点图']:
            self.assertIn(label, prompt)

    def test_empty_facts_fallback_does_not_invent_performance(self):
        prompt = package_job(self.job(2), self.workspace)['prompt']
        self.assertIn('未提供可引用的规格事实', prompt)
        self.assertIn('仅以商品参考中清楚可见', prompt)
        self.assertIn('不能从同类商品常识', prompt)

    def test_explicit_page_copy_and_fact_source_survive_packaging(self):
        self.draft['content']['facts'] = [{'name':'容量','value':'10 kg','source':'规格书第 2 页'}]
        self.draft['content']['pages'][2].update(title='容量 10 kg',body='旋钮与显示面板',visual_goal='左图右文')
        self.save()
        package = self.review_package()
        self.assertEqual('容量 10 kg', package['brief']['title'])
        self.assertEqual('规格书第 2 页', package['facts'][0]['source'])
        self.assertTrue(package['brief']['check_copywriting'])

    def test_background_only_takes_precedence_and_preserves_saved_copy(self):
        self.draft['content']['text_mode'] = 'background_only'
        self.draft['content']['pages'][2]['title'] = '保留待排版'
        self.save()
        prompt = package_job(self.job(2), self.workspace)['prompt']
        self.assertIn('此文字模式优先', prompt)
        self.assertNotIn('用户指定标题：保留待排版', prompt)
        self.assertEqual('保留待排版', self.workspace.get_draft(self.draft['id'])['content']['pages'][2]['title'])

    def test_ai_edit_places_target_first_and_does_not_recompose(self):
        job = self.job(0)
        version = self.creations.complete(job['id'], asset_id=self.product['id'], review=Review(), provenance={})
        self.draft['content']['requirements'] = '修改测试'
        self.save()
        package = package_job(self.job(0,source_version_id=version['id'],instruction='只修改标题颜色'), self.workspace)
        self.assertEqual('edit_target', package['references'][0]['role'])
        self.assertIn('输入图片 1：待修改', package['prompt'])
        self.assertIn('不要求借此重新设计整页', package['prompt'])

    def test_review_uses_original_task_after_draft_changes(self):
        self.draft['content']['pages'][2]['body'] = '原始卖点文案'
        self.save()
        job = self.job(2)
        version = self.creations.complete(job['id'], asset_id=self.product['id'], review=Review(), provenance={})
        self.draft['content']['pages'][2]['body'] = '后来改动'
        self.save()
        package = package_review({'id':'r','attempt':1,'version':version}, self.workspace)
        self.assertEqual('原始卖点文案', package['brief']['body'])
        self.assertEqual('selling_point', package['brief']['purpose'])
        self.assertIn('所有可见文字', package['instruction'])
        self.assertIn('具体问题和依据', package['instruction'])

    def test_review_cannot_silently_skip_native_copy_without_facts(self):
        package = self.review_package()
        services = AzureServices.__new__(AzureServices)
        response = Review(status='completed',summary='商品主体清楚。').model_dump_json()
        with patch.object(services, 'json_response', return_value=response) as call:
            with self.assertRaisesRegex(RuntimeError,'未检查图中文字'):
                services.review(package)
        self.assertIn('selling_point', json.dumps(call.call_args.args[0], ensure_ascii=False))
        self.assertEqual([], package['facts'])

    def test_textless_scene_does_not_require_invented_copy(self):
        package = self.review_package(1)
        self.assertFalse(package['brief']['check_copywriting'])
        self.assertIn('不自动套用', package['brief']['text_rule'])
        services = AzureServices.__new__(AzureServices)
        with patch.object(services,'json_response', return_value=Review(status='completed',summary='自然场景，主体完整。').model_dump_json()):
            self.assertEqual('自然场景，主体完整。',services.review(package).summary)

    def test_review_returns_actionable_selling_point_feedback_without_scores(self):
        package = self.review_package()
        services = AzureServices.__new__(AzureServices)
        response = {'status':'completed','summary':'主体清楚，卖点表达需要补充。','copy_observation':'只有口号，缺少具体特点。','findings':[{'kind':'error','message':'未解释具体特点','evidence':'画面只有一句生活口号，无特点标签或细节说明','action':'保留商品主体，按确认的外观特点补充对应标签。'}]}
        with patch.object(services,'json_response', return_value=json.dumps(response)):
            result = services.review(package)
            self.assertNotIn('score', result.public())
            self.assertEqual(1, len(result.repair_actions))

    def test_review_checks_approved_copy_after_ai_adds_or_removes_text(self):
        for index, plan in [(1, {'lines':[{'role':'title','text':'用户新增的标题','basis':'neutral'}]}), (2, {'lines':[]})]:
            with self.subTest(index=index):
                job = self.job(index)
                version = self.creations.complete(job['id'], asset_id=self.product['id'], review=Review(), provenance={'copy_plan':plan})
                package = package_review({'id':'r','attempt':1,'version':version}, self.workspace)
                self.assertEqual(plan, package['brief']['approved_copy'])
                self.assertEqual(bool(plan['lines']), package['brief']['check_copywriting'])

    def test_repair_uses_source_copy_instead_of_original_page_text_mode(self):
        for index, plan in [(1, {'lines':[{'role':'title','text':'新增标题','basis':'neutral'}]}), (2, {'lines':[]})]:
            with self.subTest(index=index):
                job = self.job(index)
                job['kind'] = 'repair'
                job['operation']['snapshot']['instruction'] = '根据参考修复右上 Logo 的第二个字母缺失，保留其他内容。'
                job['source_version'] = {'base_asset_id':self.product['id'], 'provenance':{'copy_plan':plan}, 'review':{'findings':[{'kind':'error','message':'Logo 缺字','evidence':'右上 Logo 的第二个字母缺失'}]}}
                package = package_job(job, self.workspace)
                self.assertEqual(bool(plan['lines']), package['copy_request']['enabled'])
                self.assertEqual(plan, package['copy_request']['source_copy'])
                self.assertEqual('', package['copy_request']['title'])
                self.assertIn('右上 Logo 的第二个字母缺失', package['prompt'])


if __name__ == '__main__':
    unittest.main()

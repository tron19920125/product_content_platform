from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import time
import unittest
import urllib.error
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image, ImageOps

from product_content_platform.studio.api import create_app
from product_content_platform.studio.azure import AzureServices, AzureServiceError, load_azure_environment
from product_content_platform.studio.catalog import DraftContent, Tool
from product_content_platform.studio.creations import Creations
from product_content_platform.studio.quality_tasks import QualityChecks
from product_content_platform.studio.settings import StudioSettings
from product_content_platform.studio.worker import StudioWorker, WorkspaceLease
from product_content_platform.studio.workspace import StudioWorkspace


class AzureStudioTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            'AZURE_AUTH_MODE': 'static', 'AZURE_OPENAI_API_KEY': 'test-secret',
            'AZURE_OPENAI_IMAGE_ENDPOINT': 'https://example.openai.azure.com/openai/v1/images/generations',
            'AZURE_OPENAI_IMAGE_DEPLOYMENT': 'gpt-image-2',
        }, clear=True)
        self.env.start()
        self.services = AzureServices()
        self.workspace = StudioWorkspace(StudioSettings(self.root / 'data'))
        self.creations = Creations(self.workspace)
        self.quality = QualityChecks(self.workspace, self.creations)
        self.worker = StudioWorker(self.workspace, self.creations, self.quality, self.services)
        buffer = io.BytesIO()
        Image.new('RGB', (128, 128), 'white').save(buffer, 'PNG')
        self.png = buffer.getvalue()
        asset = self.workspace.upload_image('product.png', 'product', self.png)
        draft = self.workspace.create_draft(Tool.MARKETING)
        draft['content']['product_asset_ids'] = [asset['id']]
        self.draft = self.workspace.save_draft(draft['id'], DraftContent.model_validate(draft['content']), expected_revision=1)
        self.package = {'references': [{'role': 'product', 'path': str(self.workspace.asset_file(asset['id'], preview=False)[0])}],
                        'requested_output': {'width': 2048, 'height': 2048}, 'prompt': 'Test product identity.'}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def submit(self, mode='codex', key='test'):
        return self.creations.submit(self.draft['id'], submit_key=key, expected_revision=self.draft['revision'], mode=mode)

    def response(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'data': [{'b64_json': base64.b64encode(self.png).decode()}]}).encode()
        return response

    def test_explicit_environment_does_not_execute_or_inherit_legacy_data(self):
        path = self.root / 'config.env'
        path.write_text('PCP_DATA_ROOT=legacy\nPCP_STUDIO_DATA_ROOT=legacy\nAZURE_TEST="$(not-executed)"\nAZURE_OPENAI_API_KEY=ignored\n', encoding='utf-8')
        load_azure_environment(path)
        self.assertNotIn('PCP_DATA_ROOT', os.environ)
        self.assertNotIn('PCP_STUDIO_DATA_ROOT', os.environ)
        self.assertEqual('$(not-executed)', os.environ['AZURE_TEST'])
        self.assertEqual('test-secret', os.environ['AZURE_OPENAI_API_KEY'])

    def test_automatic_claim_excludes_demo_and_stopped_operations(self):
        demo = self.submit('demo', 'demo')
        stopped = self.submit(key='stopped')
        self.creations.stop(stopped['id'])
        live = self.submit(key='live')
        self.assertEqual(live['id'], self.creations.claim(mode='codex')['operation_id'])
        self.assertIsNone(self.creations.claim(mode='codex'))
        self.assertEqual(demo['id'], self.creations.claim(mode='demo')['operation_id'])

    def test_real_response_saved_once_and_reused_without_network(self):
        directory = self.root / 'output'
        with patch('urllib.request.urlopen', return_value=self.response()) as send:
            first = self.services.generate(self.package, directory)
            second = self.services.generate(self.package, directory)
        self.assertEqual(1, send.call_count)
        self.assertEqual(self.png, first['path'].read_bytes())
        self.assertEqual(first, second)
        request = send.call_args.args[0]
        self.assertIn(b'2048x2048', request.data)
        self.assertIn(self.png, request.data)

    def test_timeout_is_unknown_and_never_retried(self):
        self.submit()
        job = self.creations.claim(mode='codex')
        with patch('urllib.request.urlopen', side_effect=TimeoutError('private detail')) as send:
            self.worker._run_image(job)
        self.assertEqual(1, send.call_count)
        result = self.creations.snapshot(self.draft['id'])
        self.assertEqual('unknown', result['operations'][0]['jobs'][0]['status'])
        self.assertNotIn('private detail', result['operations'][0]['jobs'][0]['error'])
        self.assertIsNone(self.creations.claim(mode='codex'))

    def test_webp_is_sent_as_png_preserving_alpha_orientation_originals_and_edit_order(self):
        webp = self.root / 'product.webp'
        original = Image.new('RGBA', (96, 64), (25, 50, 75, 120))
        original.putpixel((3, 4), (255, 0, 0, 255))
        exif = Image.Exif()
        exif[274] = 6
        original.save(webp, 'WEBP', lossless=True, exif=exif)
        before = webp.read_bytes()
        with Image.open(webp) as uploaded:
            expected = ImageOps.exif_transpose(uploaded).convert('RGBA')
        target = Path(self.package['references'][0]['path'])
        jpeg = self.root / 'style.jpg'
        Image.new('RGB', (80, 80), 'red').save(jpeg, 'JPEG')
        jpeg_before = jpeg.read_bytes()
        package = {**self.package, 'references': [
            {'role': 'product', 'path': str(webp)},
            {'role': 'style', 'path': str(jpeg)},
            {'role': 'edit_target', 'path': str(target)},
        ]}
        with patch('urllib.request.urlopen', return_value=self.response()) as send:
            self.services.generate(package, self.root / 'webp-output')
        self.assertEqual(1, send.call_count)
        request = send.call_args.args[0]
        multipart = BytesParser(policy=policy.default).parsebytes(
            ('Content-Type: ' + request.get_header('Content-type') + '\r\n\r\n').encode() + request.data)
        images = [part for part in multipart.iter_parts() if part.get_filename()]
        self.assertEqual(['image/png', 'image/png', 'image/jpeg'], [part.get_content_type() for part in images])
        self.assertEqual(self.png, images[0].get_payload(decode=True))
        with Image.open(io.BytesIO(images[1].get_payload(decode=True))) as converted:
            self.assertEqual('PNG', converted.format)
            self.assertEqual(expected.size, converted.size)
            self.assertEqual(expected.tobytes(), converted.convert('RGBA').tobytes())
            self.assertFalse(converted.getexif())
        self.assertEqual(jpeg_before, images[2].get_payload(decode=True))
        self.assertEqual(before, webp.read_bytes())
        self.assertEqual(self.png, target.read_bytes())

    def test_unreadable_reference_fails_before_any_external_request(self):
        broken = self.root / 'broken.webp'
        broken.write_bytes(b'not an image')
        package = {**self.package, 'references': [{'role': 'product', 'path': str(broken)}]}
        with patch('urllib.request.urlopen') as send:
            with self.assertRaisesRegex(AzureServiceError, '重新上传') as caught:
                self.services.generate(package, self.root / 'broken-output')
        self.assertTrue(caught.exception.outcome_known)
        self.assertFalse(caught.exception.blocks_service)
        send.assert_not_called()

    def test_http_rejections_are_specific_without_recording_raw_provider_details(self):
        cases = [
            ({'code': 'invalid_image_format', 'param': 'image', 'message': 'test-secret'}, 'reference_image', '参考图', False),
            ({'code': 'invalid_value', 'param': 'size', 'message': 'test-secret'}, 'output_size', '输出尺寸', False),
            ({'code': 'BadRequest', 'innererror': {'code': 'ResponsibleAIPolicyViolation'}, 'message': 'test-secret'}, 'content_policy', '内容审核', False),
            ({'code': 'invalid_value', 'param': 'model', 'message': 'test-secret'}, 'model_configuration', '部署名称', True),
            ({'code': 'test-secret', 'param': 'private-url', 'message': 'test-secret'}, 'http_error', 'HTTP 400', False),
        ]
        for index, (detail, category, expected, blocks) in enumerate(cases):
            with self.subTest(category=category):
                directory = self.root / f'rejection-{index}'
                request_id = 'df8f6874-ed03-4e02-b642-c4ef5538f726'
                error = urllib.error.HTTPError('private-url', 400, 'test-secret', {'apim-request-id': request_id},
                    io.BytesIO(json.dumps({'error': detail}).encode()))
                with patch('urllib.request.urlopen', side_effect=error) as send:
                    with self.assertRaisesRegex(AzureServiceError, expected) as caught:
                        self.services.generate(self.package, directory)
                self.assertTrue(caught.exception.outcome_known)
                self.assertEqual(blocks, caught.exception.blocks_service)
                self.assertEqual(1, send.call_count)
                diagnostic = (directory / 'error.json').read_text(encoding='utf-8')
                self.assertEqual(category, json.loads(diagnostic)['category'])
                self.assertEqual(request_id, json.loads(diagnostic)['request_id'])
                self.assertNotIn('test-secret', diagnostic + str(caught.exception))
                self.assertNotIn('private-url', diagnostic + str(caught.exception))

    def test_bad_error_body_and_diagnostic_write_failure_keep_rejection_retryable(self):
        for body in (b'not JSON', b'{"error": []}', b'{"error": {"param": []}}'):
            with self.subTest(body=body):
                error = urllib.error.HTTPError('private-url', 400, 'test-secret', {}, io.BytesIO(body))
                with patch('urllib.request.urlopen', side_effect=error) as send, patch.object(Path, 'write_text', side_effect=OSError('disk full')):
                    with self.assertRaisesRegex(AzureServiceError, 'HTTP 400') as caught:
                        self.services.generate(self.package, self.root / 'bad-body')
                self.assertTrue(caught.exception.outcome_known)
                self.assertEqual(1, send.call_count)

    def test_reference_rejection_is_local_to_job_and_explicit_retry_can_succeed(self):
        self.submit()
        job = self.creations.claim(mode='codex')
        self.worker.state = 'ready'
        error = urllib.error.HTTPError('private-url', 400, 'Bad Request', {},
            io.BytesIO(b'{"error":{"code":"invalid_image_format","param":"image"}}'))
        with patch('urllib.request.urlopen', side_effect=error):
            self.worker._run_image(job)
        self.assertEqual('ready', self.worker.state)
        self.assertEqual('', self.worker.error)
        failed = self.creations.snapshot(self.draft['id'])['operations'][0]['jobs'][0]
        self.assertEqual('failed', failed['status'])
        self.assertIn('参考图', failed['error'])
        self.assertIsNone(self.creations.claim(mode='codex'))
        self.creations.retry(job['id'])
        retry = self.creations.claim(mode='codex')
        self.assertEqual(job['id'], retry['id'])
        self.worker.error = 'stale error'
        with patch('urllib.request.urlopen', return_value=self.response()) as send:
            self.worker._run_image(retry)
        self.assertEqual(1, send.call_count)
        self.assertEqual('', self.worker.error)
        self.assertEqual('done', self.creations.snapshot(self.draft['id'])['operations'][0]['jobs'][0]['status'])

    def test_auth_rejection_is_actionable_and_pauses_executor_without_exposing_secrets(self):
        self.submit()
        job = self.creations.claim(mode='codex')
        error = urllib.error.HTTPError('private-url', 401, 'test-secret', {}, io.BytesIO(b'test-secret'))
        with patch('urllib.request.urlopen', side_effect=error):
            self.worker._run_image(job)
        self.assertEqual('error', self.worker.state)
        self.assertIn('认证', self.worker.error)
        self.assertNotIn('test-secret', self.worker.error)
        self.assertEqual('failed', self.creations.snapshot(self.draft['id'])['operations'][0]['jobs'][0]['status'])

    def test_received_image_is_recovered_after_restart_without_resubmission(self):
        self.submit()
        job = self.creations.claim(mode='codex')
        directory = self.workspace.settings.data_root / 'production' / job['id']
        with patch('urllib.request.urlopen', return_value=self.response()):
            self.services.generate(self.package, directory)
        self.creations.recover()
        with patch('urllib.request.urlopen', side_effect=AssertionError('must not call Azure')) as send:
            self.worker._recover_saved_results()
        self.assertEqual(0, send.call_count)
        results = self.creations.snapshot(self.draft['id'])
        self.assertEqual('done', results['operations'][0]['jobs'][0]['status'])
        self.assertEqual('azure-openai', results['versions'][0]['provenance']['provider'])

    def test_one_executor_lease_per_workspace(self):
        first = WorkspaceLease(self.root)
        try:
            with self.assertRaisesRegex(RuntimeError, '已有自动执行器'):
                WorkspaceLease(self.root)
        finally:
            first.close()
        WorkspaceLease(self.root).close()

    def test_lifespan_executes_pending_job_and_reports_live_health(self):
        self.submit()
        with patch('urllib.request.urlopen', return_value=self.response()) as send:
            with TestClient(create_app(StudioSettings(self.workspace.settings.data_root, generation_provider='azure'))) as client:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    result = client.get(f"/api/studio/drafts/{self.draft['id']}/results").json()
                    if result['versions']:
                        break
                    time.sleep(.05)
                self.assertEqual('done', result['operations'][0]['jobs'][0]['status'])
                health = client.get('/api/health').json()
                self.assertTrue(health['generation_available'])
                self.assertTrue(health['azure_configured'])
                self.assertNotIn('test-secret', json.dumps(health))
        self.assertEqual(1, send.call_count)

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from product_content_platform.studio.api import create_app
from product_content_platform.studio.catalog import Tool, default_draft
from product_content_platform.studio.settings import StudioSettings


class HistoryLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(StudioSettings(Path(self.temp.name)))
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def save(self, content, identifier=None, revision=0):
        return self.client.put(f'/api/studio/drafts/{identifier or uuid4()}',
            json={'expected_revision': revision, 'content': content})

    def history(self):
        return self.client.get('/api/studio/history').json()

    def defaults(self, tool=Tool.MARKETING):
        return default_draft(tool).model_dump(mode='json')

    def test_initial_save_is_atomic_and_retries_do_not_duplicate_or_overwrite(self):
        content = self.defaults()
        content['product_name'] = 'Only one draft'
        identifier = str(uuid4())
        first = self.save(content, identifier)
        self.assertEqual(200, first.status_code)
        self.assertEqual(1, first.json()['revision'])
        self.assertEqual(first.json(), self.save(content, identifier).json())
        changed = {**content, 'product_name': 'Updated input'}
        self.assertEqual(200, self.save(changed, identifier, 1).status_code)
        self.assertEqual(409, self.save(content, identifier).status_code)
        self.assertEqual(1, len(self.history()))
        self.assertEqual('Updated input', self.history()[0]['content']['product_name'])
        self.assertEqual('draft', self.history()[0]['history_kind'])

    def test_invalid_initial_save_does_not_leave_an_empty_record(self):
        content = self.defaults()
        content['product_asset_ids'] = ['missing-asset']
        self.assertEqual(422, self.save(content).status_code)
        self.assertEqual([], self.client.get('/api/studio/drafts').json())

    def test_old_default_records_are_hidden_without_deleting_them(self):
        identifiers = []
        for tool in Tool:
            identifiers.append(self.client.post('/api/studio/drafts', json={'tool': tool.value}).json()['id'])
        self.assertEqual([], self.history())
        self.assertEqual([], self.client.get('/api/studio/drafts?resume=true').json())
        self.assertEqual(5, len(self.client.get('/api/studio/drafts').json()))
        for identifier in identifiers:
            self.assertEqual(200, self.client.get(f'/api/studio/drafts/{identifier}').status_code)

    def test_unnamed_input_parameter_changes_and_reference_only_drafts_are_kept(self):
        content = self.defaults()
        edits = [{'requirements': 'Some instructions'}, {'output': {'ratio': '1:1', 'resolution': '1k'}},
                 {'facts': [{'name': '', 'value': '', 'source': ''}]}]
        for patch_data in edits:
            self.assertEqual(200, self.save({**content, **patch_data}).status_code)
        image = io.BytesIO()
        Image.new('RGB', (20, 20)).save(image, format='PNG')
        asset = self.client.post('/api/studio/assets?filename=product.png&usage=product', content=image.getvalue()).json()
        self.save({**content, 'product_asset_ids': [asset['id']]})
        self.assertEqual(4, len(self.history()))
        self.assertTrue(all(row['history_kind'] == 'draft' for row in self.history()))

    def test_generation_moves_the_same_record_out_of_resumable_drafts_even_on_failure(self):
        draft = self.client.post('/api/studio/demo/drafts', json={'tool': 'marketing_main_image'}).json()
        response = self.client.post(f"/api/studio/drafts/{draft['id']}/generate",
            json={'submit_key': 'history-flow', 'expected_revision': draft['revision'], 'mode': 'codex'})
        self.assertEqual(202, response.status_code)
        job = self.app.state.creations.claim(mode='codex')
        self.app.state.creations.fail(job['id'], message='Test rejection', outcome_known=True)
        row = self.history()[0]
        self.assertEqual(draft['id'], row['id'])
        self.assertEqual('generation', row['history_kind'])
        self.assertEqual('failed', row['history_status'])
        self.assertEqual([], self.client.get('/api/studio/drafts?resume=true').json())
        self.client.post(f"/api/studio/jobs/{job['id']}/retry")
        self.assertEqual(1, len(self.history()))
        self.app.state.creations.stop(job['operation_id'])
        self.assertEqual('generation', self.history()[0]['history_kind'])
        self.assertEqual('stopped', self.history()[0]['history_status'])

    def test_plan_failure_is_retained_and_validation_failure_remains_a_draft(self):
        draft = self.save(self.defaults(Tool.A_PLUS)).json()
        with patch.object(self.app.state.planner, 'plan', side_effect=RuntimeError('Test service offline')):
            response = self.client.post(f"/api/studio/drafts/{draft['id']}/plan", json={'expected_revision': 1})
        self.assertEqual(503, response.status_code)
        row = self.history()[0]
        self.assertEqual('generation', row['history_kind'])
        self.assertEqual('plan_failed', row['history_status'])
        self.assertTrue(row['planning_error'])
        invalid = self.defaults(Tool.A_PLUS)
        invalid['facts'] = [{'name': 'size', 'value': '', 'source': ''}]
        other = self.save(invalid).json()
        response = self.client.post(f"/api/studio/drafts/{other['id']}/plan", json={'expected_revision': 1})
        self.assertEqual(422, response.status_code)
        self.assertEqual('draft', next(row for row in self.history() if row['id'] == other['id'])['history_kind'])

    def test_existing_plan_versions_are_formal_records_even_when_restored_to_defaults(self):
        content = default_draft(Tool.A_PLUS)
        draft = self.save(content.model_dump(mode='json')).json()
        self.app.state.workspace.record_plan(draft['id'], content, label='Existing plan')
        self.assertEqual('generation', self.history()[0]['history_kind'])
        self.assertEqual('planned', self.history()[0]['history_status'])

    def test_planning_cannot_be_deleted_or_submitted_twice_and_recovers_after_restart(self):
        draft = self.save(self.defaults(Tool.A_PLUS)).json()
        self.app.state.workspace.begin_planning(draft['id'], expected_revision=1)
        self.assertEqual('planning', self.history()[0]['history_status'])
        response = self.client.post(f"/api/studio/drafts/{draft['id']}/plan", json={'expected_revision': 1})
        self.assertEqual(409, response.status_code)
        response = self.client.post(f"/api/studio/drafts/{draft['id']}/lifecycle", json={'action': 'trash'})
        self.assertEqual(422, response.status_code)
        self.app.state.creations.recover()
        self.assertEqual('plan_unknown', self.history()[0]['history_status'])

    def test_hidden_empty_record_is_still_visible_in_recycle_bin_and_restorable(self):
        draft = self.client.post('/api/studio/drafts', json={'tool': 'scene_image'}).json()
        self.client.post(f"/api/studio/drafts/{draft['id']}/lifecycle", json={'action': 'trash'})
        trash = self.client.get('/api/studio/history?trash=true').json()
        self.assertEqual([draft['id']], [row['id'] for row in trash])
        self.client.post(f"/api/studio/drafts/{draft['id']}/lifecycle", json={'action': 'restore'})
        self.assertEqual([], self.history())


if __name__ == '__main__':
    unittest.main()

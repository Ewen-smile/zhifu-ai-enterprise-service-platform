import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

APP_PATH = Path(__file__).resolve().parents[1] / 'app.py'
spec = importlib.util.spec_from_file_location('zhifu_v21_under_test', APP_PATH)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class FakeResponse:
    def __init__(self, body): self.body = json.dumps(body).encode('utf-8')
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, _): return self.body

class CategoryTests(unittest.TestCase):
    def test_extract_known_label(self):
        self.assertEqual(app.split_ai_answer('步骤一。\n[[ZHIFU_CATEGORY:账号权限]]'), ('步骤一。', '账号权限'))
    def test_extract_with_whitespace(self):
        self.assertEqual(app.split_ai_answer('你好\n [[ZHIFU_CATEGORY: 办公网络 ]] \n'), ('你好','办公网络'))
    def test_unrecognized_label_is_not_trusted(self):
        self.assertEqual(app.split_ai_answer('你好\n[[ZHIFU_CATEGORY:未知类别]]'), ('你好', None))
    def test_no_label_is_backward_compatible(self):
        self.assertEqual(app.split_ai_answer('旧版无分类问答'), ('旧版无分类问答', None))
    def test_dify_answer_return_shape(self):
        mock_json={'answer':'请按步骤处理。\n[[ZHIFU_CATEGORY:办公软件]]','conversation_id':'conv_demo_01'}
        with patch.object(app.urllib.request, 'urlopen',return_value=FakeResponse(mock_json)), patch.object(app,'DIFY_API_KEY','app-FAKE'):
            response = app.dify_answer('Word 无法打开','')
        self.assertEqual(response['answer'], '请按步骤处理。')
        self.assertEqual(response['category'], '办公软件')
        self.assertEqual(response['category_source'], 'dify_classifier')
        self.assertEqual(response['conversation_id'], 'conv_demo_01')
    def test_old_answer_still_works(self):
        with patch.object(app.urllib.request, 'urlopen',return_value=FakeResponse({'answer':'正常回答','conversation_id':'x'})),patch.object(app,'DIFY_API_KEY','app-FAKE'):
            response = app.dify_answer('问','')
        self.assertIsNone(response['category'])
        self.assertEqual(response['category_source'], 'not_provided')

if __name__ == '__main__': unittest.main()

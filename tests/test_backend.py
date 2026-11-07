"""Run: python3 -m unittest discover -s tests -v (from upgrade package root)."""
import io
import json
import unittest
from unittest.mock import patch
import app


class AnswerCleaningTests(unittest.TestCase):
    def test_closed_think_and_category(self):
        answer = '<think>敏感的模型思考\n不得显示</think>\n\n**处理步骤**\n1. 联系 IT。\n[[ZHIFU_CATEGORY:账号权限]]'
        cleaned, cat = app.split_ai_answer(answer)
        self.assertEqual(cat, '账号权限')
        self.assertNotIn('敏感', cleaned)
        self.assertNotIn('<think>', cleaned)
        self.assertIn('**处理步骤**', cleaned)

    def test_multiple_reasoning_blocks(self):
        cleaned, cat = app.split_ai_answer('开始<think>x</think>继续<THINK>y</THINK>结束\n[[ZHIFU_CATEGORY:办公网络]]')
        self.assertEqual(cleaned, '开始继续结束')
        self.assertEqual(cat, '办公网络')

    def test_unclosed_think_dropped(self):
        cleaned, cat = app.split_ai_answer('可见建议\n<think>不应泄漏的内容\n[[ZHIFU_CATEGORY:账号权限]]')
        self.assertEqual(cleaned, '可见建议')
        self.assertEqual(cat, '账号权限')

    def test_stray_close_tag(self):
        cleaned, cat = app.split_ai_answer('</think>\n正常回答')
        self.assertEqual(cleaned, '正常回答')
        self.assertIsNone(cat)

    def test_unrecognized_category_ignored(self):
        cleaned, cat = app.split_ai_answer('正常回答\n[[ZHIFU_CATEGORY:机密信息]]')
        self.assertEqual(cleaned, '正常回答')
        self.assertIsNone(cat)

    def test_plain_answer_unchanged(self):
        cleaned, cat = app.split_ai_answer('## 排查步骤\n- 查看设置\n- 联系 IT')
        self.assertEqual(cleaned, '## 排查步骤\n- 查看设置\n- 联系 IT')
        self.assertIsNone(cat)

    def test_dify_mocked_pipeline(self):
        content = json.dumps({'answer':'<think>略</think>\n1. **联系 IT**\n[[ZHIFU_CATEGORY:账号权限]]', 'conversation_id':'test-cid'}).encode('utf-8')
        with patch.object(app.urllib.request, 'urlopen', return_value=io.BytesIO(content)):
            result = app.dify_answer('密码忘记了', '')
        self.assertEqual(result['source'], 'dify')
        self.assertEqual(result['category'], '账号权限')
        self.assertEqual(result['category_source'], 'dify_classifier')
        self.assertNotIn('think', result['answer'])
        self.assertNotIn('ZHIFU_CATEGORY', result['answer'])
        self.assertIn('**联系 IT**', result['answer'])


if __name__ == '__main__':
    unittest.main()

# 智服 AI｜30 题自动化评测工具

**来源：本次最终上传的 V4.0 包。** `run_eval.py` 与 `testcases.json` 保留源文件内容；历史评测结果、会话日志、Excel 结果导出已从公开版移除。

评测器只访问后端 `/api/health` 和 `/api/chat`，不会创建工单或更新知识库。需要 Python 3.9+，没有第三方依赖。

先在其他终端启动并配置好 Dify 的 V4.0 服务，然后从仓库根目录执行：

```bash
python3 zhifu_ai_batch_eval/run_eval.py --dry-run
python3 zhifu_ai_batch_eval/run_eval.py         # 先跑 5 题
python3 zhifu_ai_batch_eval/run_eval.py --all   # 跑全部 30 题
```

支持 `--ids T18,T22`、`--redo`、`--delay 3`、`--base-url` 等参数，完整用法见 `--help`。脚本会自动创建 `zhifu_ai_batch_eval/eval_output/` 保存历史记录、Excel、HTML、CSV；此目录被 `.gitignore` 排除，请勿提交。

若 Dify 没有配置，脚本会停止以免把本地规则检索当成 LLM 结果；只有显式设置 `--allow-local` 才允许本地模式测试。多轮题在同一会话连续调用。**脚本统计的是分类与预期的符合情况，不会自动可靠判断幻觉、事实准确率或 RAG Top-3 命中。**

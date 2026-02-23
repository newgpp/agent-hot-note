# agent-hot-note

热点笔记生成服务（Phase 3，LangGraph + 真实 DeepSeek + Tavily + Fallback + Extract，异步实现）。

## 0. 架构模式（Anthropic 对照）

本项目对应 Anthropic《Building effective agents》里的 **Workflow** 模式，而不是完全自治的 Agent。

具体包含两种模式组合：

- **Prompt Chaining**：`research -> write -> edit` 固定顺序执行。
- **Routing**：先将 topic 路由到 `general/job/finance`，再使用对应域名配置进行检索。

参考链接：

- https://www.anthropic.com/engineering/building-effective-agents

## 1. 环境要求

- Python 3.11
- `pip` 可用

## 2. 安装依赖

推荐使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

安装运行依赖：

```bash
pip install -e .
```

安装开发/测试依赖：

```bash
pip install -e ".[dev]"
```

## 3. 启动项目

在项目根目录执行：

```bash
uvicorn agent_hot_note.api.app:app --reload
```

## 3.1 环境变量

先创建 `.env`（可参考 `.env.example`）：

```bash
cp .env.example .env
```

关键配置：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL=https://api.deepseek.com`
- `OPENAI_MODEL=deepseek-chat`
- `TAVILY_API_KEY`
- `FALLBACK_MIN_RESULTS`
- `FALLBACK_MIN_AVG_SUMMARY_CHARS`
- `FALLBACK_MAX_TITLE_DUP_RATIO`
- `TAVILY_EXTRACT_ENABLED`
- `TAVILY_EXTRACT_MAX_URLS`
- `TOPIC_DEFAULT_PROFILE`
- `TOPIC_DOMAIN_PROFILES`

`TOPIC_DOMAIN_PROFILES` 支持为不同话题配置不同抓取域名（当前默认：`general/job/finance`）：

- `general`: 小红书/知乎/B站
- `job`: Boss直聘/猎聘/前程无忧/智联/拉勾/看准
- `finance`: 东方财富/同花顺/证券时报/中证网

服务启动后：

- 健康检查：`GET http://127.0.0.1:8000/healthz`
- 生成接口：`POST http://127.0.0.1:8000/generate`

## 4. 接口调用示例

```bash
curl -X POST "http://127.0.0.1:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{"topic":"AI 笔记"}'
```

可选地手动指定话题分类（覆盖自动分类）：

```bash
curl -X POST "http://127.0.0.1:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{"topic":"Python Agent工程师技能要求","topic_profile":"job"}'
```

返回结构示例：

```json
{
  "markdown": "...",
  "meta": {
    "stages": ["research", "write", "edit"],
    "requested_topic_profile": "job",
    "topic_profile": "job",
    "query": "AI 笔记",
    "queries": ["AI 笔记", "AI 笔记", "AI 笔记"],
    "fallback_triggered": true,
    "fallback_reason": "summary_too_short",
    "fallback_queries": ["AI 笔记", "AI 笔记", "AI 笔记"],
    "fallback_domains": [["xiaohongshu.com"], ["zhihu.com", "bilibili.com"], []],
    "extracted_urls": ["https://xiaohongshu.com/p/xxx"],
    "extract_failed_urls": []
  }
}
```

## 4.1 关键日志

- `fallback.evaluate` / `fallback.attempt` / `fallback.resolved`
- `extract.candidates` / `extract.applied` / `extract.failed`
- `tavily.extract.request` / `tavily.extract.response`
- `llm.request.full` / `llm.response.full` / `llm.error`

## 5. 运行测试

```bash
python3 -m pytest -q
```

只跑某个测试文件：

```bash
python3 -m pytest tests/test_api.py -q
python3 -m pytest tests/test_workflow.py -q
```

## 6. Router 提示词评估

目标：评估 `_classify_topic_profile` 对 `general/job/finance` 的分类效果。

### 6.1 准备评估集

- 示例文件：`eval/router_labeled.sample.jsonl`
- 每行一个 JSON，字段：
  - `topic`：待分类话题
  - `gold_profile`：人工标注分类（`general/job/finance`）
  - `note`：可选备注

### 6.2 运行评估

```bash
python3 scripts/eval_router.py \
  --input eval/router_labeled.sample.jsonl
```

运行后会生成：

- `eval/reports/router_eval_<timestamp>.md`
- `eval/reports/router_eval_<timestamp>.json`

### 6.3 指标解释

- `accuracy`：总体分类准确率
- `per-class precision/recall/f1`：按分类维度看误判方向
- `confusion matrix`：查看 `general/job/finance` 之间最容易混淆的路径

建议基线：

- 总体准确率 >= 90%
- `job` 与 `finance` 的召回率 >= 85%

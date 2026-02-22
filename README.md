# agent-hot-note

热点笔记生成服务（Phase 3，真实 DeepSeek + Tavily + Fallback + Extract，异步实现）。

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
- `FALLBACK_PRIMARY_DOMAINS`
- `FALLBACK_SECONDARY_DOMAINS`
- `TAVILY_EXTRACT_ENABLED`
- `TAVILY_EXTRACT_MAX_URLS`
- `TAVILY_EXTRACT_ALLOWED_DOMAINS`

服务启动后：

- 健康检查：`GET http://127.0.0.1:8000/healthz`
- 生成接口：`POST http://127.0.0.1:8000/generate`

## 4. 接口调用示例

```bash
curl -X POST "http://127.0.0.1:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{"topic":"AI 笔记"}'
```

返回结构示例：

```json
{
  "markdown": "...",
  "meta": {
    "stages": ["research", "write", "edit"],
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
python3 -m pytest tests/test_crew.py -q
```

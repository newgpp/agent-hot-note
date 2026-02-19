# agent-hot-note

热点笔记生成服务（Phase 1，Mock 版本，异步实现）。

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
    "query": "AI 笔记"
  }
}
```

## 5. 运行测试

```bash
python3 -m pytest -q
```

只跑某个测试文件：

```bash
python3 -m pytest tests/test_api.py -q
python3 -m pytest tests/test_crew.py -q
```

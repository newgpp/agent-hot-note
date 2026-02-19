# DEV_NOTES.md --- agent-hot-note（三阶段实现版）

> 项目目标：分阶段实现 FastAPI + CrewAI + DeepSeek + Tavily 的可扩展
> Agent 服务\
> 原则：先跑流程 → 再接真实能力 → 最后做工程优化

------------------------------------------------------------------------

# 最新进度（2026-02-19）

## ✅ 今日完成

- 已改为 **纯 CrewAI 执行链**（`research -> write -> edit`），不再走外层 MockLLM 三阶段 fallback。
- 已实现 **CrewAI 内部 Mock**：通过 mock `litellm.completion` 返回固定结果，保持接口可离线联调。
- 已修复 CrewAI ReAct 解析报错：mock 输出统一改为 `Thought + Final Answer` 格式。
- 已增加运行稳定性设置：
  - `OTEL_SDK_DISABLED=true`（禁用 telemetry）
  - `CREWAI_STORAGE_DIR=.crewai`（本地可写存储目录）
- 依赖与运行环境已锁定到当前方案：
  - Python 要求：`>=3.11`
  - `fastapi==0.115.8`
  - `uvicorn==0.34.0`
  - `pydantic==2.10.6`
  - `crewai==0.100.0`
  - `pytest==8.3.4`

## 🔜 明天继续

- 在 Python 3.11 虚拟环境完整跑一轮 API + pytest。
- 评估是否把 `litellm` mock 抽成独立模块，减少 `SequentialCrew` 复杂度。
- 开始推进 Phase 2（接 DeepSeek + Tavily）并保留本地 mock 开关。

------------------------------------------------------------------------

# Phase 1：搭建骨架（全部 Mock，实现最小闭环）

## 🎯 目标

-   学习 CrewAI 基本流程
-   跑通 FastAPI 接口
-   不依赖真实 LLM 或 Tavily

## ✅ 实现内容

### 1. 项目结构

agent-hot-note/ src/agent_hot_note/ api/ service/ crew/ providers/
llm/mock.py search/mock.py pipeline/ tests/

### 2. FastAPI

接口：

POST /generate\
GET /healthz

### 3. Crew 流程（sequential）

research → write → edit

### 4. Mock 实现

MockLLM： - 返回固定字符串 - 模拟三阶段调用

MockSearch： - 返回固定 search results 结构

### 5. 返回格式

Markdown 输出：

# 标题（3个）

# 正文

# 标签（10个）

### 6. Phase 1 DoD

-   /generate 正常返回 Markdown
-   日志显示 research/write/edit
-   单元测试可运行
-   无需任何 API key

------------------------------------------------------------------------

# Phase 2：接入真实 DeepSeek + Tavily

## 🎯 目标

替换 Mock，实现真实能力

## ✅ 实现内容

### 1. LLM Provider

新增：

providers/llm/deepseek.py

读取 .env：

OPENAI_API_KEY OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat

使用 OpenAI 兼容方式初始化 LLM

### 2. Tavily Provider

新增：

providers/search/tavily.py

使用 TavilyClient.search：

search_depth="advanced" max_results=5

### 3. 替换策略

通过环境变量控制：

USE_MOCK=0 或 1

### 4. Phase 2 DoD

-   配置 .env 后能真实生成内容
-   返回 meta 包含 queries
-   出错不崩溃（返回结构化错误）

------------------------------------------------------------------------

# Phase 3：优化 fallback + 增加记忆

## 🎯 目标

提升稳定性和可复用性

------------------------------------------------------------------------

## 3.1 Fallback 优化

实现：pipeline/fallback.py

策略：

1.  site:xiaohongshu.com {topic}
2.  若结果少 → 多域名 fallback：
    -   zhihu
    -   bilibili
    -   通用 query

质量判断规则： - 结果数量 \< 2 → fallback - 摘要过短 → fallback -
标题重复率高 → fallback

meta 必须返回：

fallback_triggered: true/false queries: \[...\]

------------------------------------------------------------------------

## 3.2 记忆机制（轻量版）

目录：memory/

### 1️⃣ Topic Memory

存储：

topic_hash → 最终 Markdown + 要点

命中时直接返回或增强生成

### 2️⃣ Pattern Memory

存储爆款结构模板：

-   标题模板
-   钩子句模板
-   结构模板

来源：editor 修改清单自动提取

存储形式：

jsonl 或 sqlite

------------------------------------------------------------------------

## Phase 3 DoD

-   fallback 自动触发并可解释
-   同 topic 可命中缓存
-   输出更稳定（格式校验）

------------------------------------------------------------------------

# 最终架构结构

agent_hot_note/ api/ service/ crew/ providers/ llm/ mock.py deepseek.py
search/ mock.py tavily.py pipeline/ fallback.py postprocess.py memory/
store.py

------------------------------------------------------------------------

# 运行方式

uvicorn agent_hot_note.api.app:app --reload

------------------------------------------------------------------------

结束。

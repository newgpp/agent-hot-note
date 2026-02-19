import asyncio
import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CrewOutput:
    research: str
    draft: str
    edited: str
    search_results: dict[str, Any]


class SequentialCrew:
    """Sequential crew powered by CrewAI with internal deterministic mock LLM."""

    async def run(self, topic: str) -> CrewOutput:
        logger.info("research")
        research, draft, edited, search_results = await asyncio.to_thread(self._run_with_crewai, topic)
        return CrewOutput(research=research, draft=draft, edited=edited, search_results=search_results)

    def _run_with_crewai(self, topic: str) -> tuple[str, str, str, dict[str, Any]]:
        os.environ.setdefault("OTEL_SDK_DISABLED", "true")
        os.environ.setdefault("CREWAI_STORAGE_DIR", ".crewai")
        Path(os.environ["CREWAI_STORAGE_DIR"]).mkdir(parents=True, exist_ok=True)

        from crewai import Agent, Crew, Process, Task

        search_results = self._mock_search_results(topic)
        search_context = "\n".join(
            [f"- {item.get('title', '')}: {item.get('content', '')}" for item in search_results.get("results", [])]
        )
        agent = Agent(
            role="Hot Note Strategist",
            goal="Generate practical and concise Chinese hot-note content",
            backstory="You are a content strategist focused on actionable short-form notes.",
            llm="openai/gpt-4o-mini",
            verbose=False,
            allow_delegation=False,
        )

        research_task = Task(
            description=(
                "Analyze topic: {topic}. Based on search snippets below, provide concise research conclusions in Chinese.\n"
                f"Search snippets:\n{search_context}"
            ),
            expected_output="A concise Chinese research summary with insights and key angles.",
            agent=agent,
        )

        logger.info("write")
        write_task = Task(
            description="Write the main body in Chinese with clear sections, based on research.",
            expected_output="A structured Chinese draft with sections and practical guidance.",
            agent=agent,
            context=[research_task],
        )

        logger.info("edit")
        edit_task = Task(
            description="Polish the draft. Output 3 title ideas and 10 tags in Chinese.",
            expected_output="Chinese edits including 3 titles and 10 tags.",
            agent=agent,
            context=[write_task],
        )

        crew = Crew(
            agents=[agent],
            tasks=[research_task, write_task, edit_task],
            process=Process.sequential,
            verbose=False,
        )
        with self._mock_litellm_completion():
            result = crew.kickoff(inputs={"topic": topic})
        task_outputs = getattr(result, "tasks_output", None) or getattr(crew, "tasks_output", None)
        if not task_outputs or len(task_outputs) < 3:
            raise RuntimeError("CrewAI did not return all stage outputs")

        research = self._stringify_task_output(task_outputs[0])
        draft = self._stringify_task_output(task_outputs[1])
        edited = self._stringify_task_output(task_outputs[2])
        return research, draft, edited, search_results

    @staticmethod
    def _stringify_task_output(task_output: Any) -> str:
        raw = getattr(task_output, "raw", None)
        if raw is not None:
            return str(raw).strip()
        return str(task_output).strip()

    @staticmethod
    def _mock_search_results(topic: str) -> dict[str, Any]:
        return {
            "query": topic,
            "results": [
                {
                    "title": f"{topic} 趋势观察",
                    "url": "https://example.com/trend",
                    "content": f"{topic} 在近期讨论中热度提升，用户关注点集中在实用方法与对比。",
                },
                {
                    "title": f"{topic} 实操总结",
                    "url": "https://example.com/practice",
                    "content": f"关于 {topic} 的内容偏好是短结论 + 可直接复制的步骤。",
                },
            ],
        }


    @contextmanager
    def _mock_litellm_completion(self):
        import litellm
        from litellm.types.utils import ModelResponse

        original_completion = litellm.completion
        stage_counter = {"value": 0}

        def mocked_completion(**params: Any):
            messages = params.get("messages", [])
            prompt = self._extract_prompt(messages=messages)
            topic = self._extract_topic(prompt)
            stage = self._detect_stage(prompt, stage_counter)
            content = self._build_stage_content(stage=stage, topic=topic)
            return ModelResponse(
                model=str(params.get("model", "openai/gpt-4o-mini")),
                choices=[{"message": {"role": "assistant", "content": content}}],
            )

        litellm.completion = mocked_completion
        try:
            yield
        finally:
            litellm.completion = original_completion

    @staticmethod
    def _build_stage_content(stage: str, topic: str) -> str:
        if stage == "research":
            answer = f"研究结论：主题「{topic}」可从痛点、方法、案例三段展开。共参考 2 条结果。"
            return f"Thought: I now can give a great answer\n\nFinal Answer: {answer}"
        if stage == "write":
            answer = "\n".join(
                [
                    "## 亮点拆解",
                    f"{topic} 的核心价值在于更快产出可执行结果，适合想要快速上手的人群。",
                    "## 实操路径",
                    "先定义目标，再用最小步骤验证，最后按反馈迭代。",
                    "## 避坑建议",
                    "不要一次塞太多信息，保持一条主线更容易获得高互动。",
                ]
            )
            return f"Thought: I now can give a great answer\n\nFinal Answer: {answer}"
        answer = "\n".join(
            [
                "标题1：3步搭建你的高效流程",
                "标题2：从0到1跑通最小闭环",
                "标题3：减少试错的实战清单",
                "标签：效率,方法论,实操,复盘,热点,内容创作,增长,清单,教程,经验",
            ]
        )
        return f"Thought: I now can give a great answer\n\nFinal Answer: {answer}"

    @staticmethod
    def _detect_stage(prompt: str, stage_counter: dict[str, int]) -> str:
        lowered = prompt.lower()
        if "polish" in lowered or "title ideas" in lowered or "10 tags" in lowered:
            return "edit"
        if "write the main body" in lowered or "structured chinese draft" in lowered:
            return "write"
        if "analyze topic" in lowered or "search snippets" in lowered:
            return "research"
        stages = ["research", "write", "edit"]
        index = min(stage_counter["value"], len(stages) - 1)
        stage_counter["value"] += 1
        return stages[index]

    @staticmethod
    def _extract_topic(prompt: str) -> str:
        patterns = [
            r"topic[:：]\s*([^\n]+)",
            r"主题[「\"]?([^」\"\n]+)",
        ]
        for pattern in patterns:
            matched = re.search(pattern, prompt, flags=re.IGNORECASE)
            if matched:
                return matched.group(1).strip()
        return "未知主题"

    @staticmethod
    def _extract_prompt(*args: Any, **kwargs: Any) -> str:
        if "messages" in kwargs and isinstance(kwargs["messages"], list):
            return SequentialCrew._flatten_messages(kwargs["messages"])
        if args:
            first = args[0]
            if isinstance(first, str):
                return first
            if isinstance(first, list):
                return SequentialCrew._flatten_messages(first)
        return str(kwargs)

    @staticmethod
    def _flatten_messages(messages: list[Any]) -> str:
        parts: list[str] = []
        for message in messages:
            if isinstance(message, dict):
                content = message.get("content", "")
                parts.append(str(content))
            else:
                parts.append(str(message))
        return "\n".join(parts)

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bootstrap_pythonpath() -> None:
    import sys

    src = _repo_root() / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


_bootstrap_pythonpath()

from agent_hot_note.config import get_settings  # noqa: E402
from agent_hot_note.workflow.generation import GenerationWorkflow  # noqa: E402


@dataclass
class Sample:
    topic: str
    gold_profile: str
    note: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate topic-profile router accuracy.")
    parser.add_argument(
        "--input",
        default="eval/router_labeled.sample.jsonl",
        help="JSONL file with fields: topic, gold_profile, optional note.",
    )
    parser.add_argument(
        "--output-md",
        default="",
        help="Markdown report path. Default: eval/reports/router_eval_<timestamp>.md",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="JSON report path. Default: eval/reports/router_eval_<timestamp>.json",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit evaluated samples (0 means all).")
    return parser.parse_args()


def load_samples(path: Path, limit: int) -> list[Sample]:
    samples: list[Sample] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            raw = line.strip()
            if not raw:
                continue
            row = json.loads(raw)
            topic = str(row.get("topic", "")).strip()
            gold = str(row.get("gold_profile", "")).strip().lower()
            note = str(row.get("note", "")).strip()
            if not topic or not gold:
                raise ValueError(f"Invalid sample at line {line_no}: topic/gold_profile required")
            samples.append(Sample(topic=topic, gold_profile=gold, note=note))
            if limit > 0 and len(samples) >= limit:
                break
    if not samples:
        raise ValueError("No samples loaded.")
    return samples


async def predict_profiles(samples: list[Sample]) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    settings = get_settings()
    workflow = GenerationWorkflow(settings)
    gold: list[str] = []
    pred: list[str] = []
    rows: list[dict[str, Any]] = []
    for sample in samples:
        predicted = await workflow._classify_topic_profile(sample.topic)
        predicted = str(predicted).strip().lower() or settings.topic_default_profile
        gold.append(sample.gold_profile)
        pred.append(predicted)
        rows.append(
            {
                "topic": sample.topic,
                "gold_profile": sample.gold_profile,
                "pred_profile": predicted,
                "correct": predicted == sample.gold_profile,
                "note": sample.note,
            }
        )
    return gold, pred, rows


def compute_metrics(gold: list[str], pred: list[str]) -> dict[str, Any]:
    labels = sorted(set(gold) | set(pred))
    confusion: dict[str, dict[str, int]] = {g: {p: 0 for p in labels} for g in labels}
    for g, p in zip(gold, pred, strict=True):
        confusion[g][p] += 1

    total = len(gold)
    correct = sum(1 for g, p in zip(gold, pred, strict=True) if g == p)
    accuracy = correct / max(total, 1)

    per_class: dict[str, dict[str, float | int]] = {}
    for label in labels:
        tp = confusion[label][label]
        fp = sum(confusion[g][label] for g in labels if g != label)
        fn = sum(confusion[label][p] for p in labels if p != label)
        support = sum(confusion[label][p] for p in labels)
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 0.0 if precision + recall == 0 else (2 * precision * recall) / (precision + recall)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }

    error_examples: dict[str, list[str]] = defaultdict(list)
    for g, p in zip(gold, pred, strict=True):
        if g != p and len(error_examples[g]) < 5:
            error_examples[g].append(p)

    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "labels": labels,
        "confusion_matrix": confusion,
        "per_class": per_class,
        "error_examples": dict(error_examples),
    }


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def build_markdown_report(input_path: str, metrics: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    labels: list[str] = metrics["labels"]
    lines: list[str] = []
    lines.append("# Router Eval Report")
    lines.append("")
    lines.append(f"- input: `{input_path}`")
    lines.append(f"- total: `{metrics['total']}`")
    lines.append(f"- correct: `{metrics['correct']}`")
    lines.append(f"- accuracy: `{_fmt_pct(metrics['accuracy'])}`")
    lines.append("")
    lines.append("## Per-class Metrics")
    lines.append("")
    lines.append("| profile | precision | recall | f1 | support |")
    lines.append("|---|---:|---:|---:|---:|")
    for label in labels:
        m = metrics["per_class"][label]
        lines.append(
            f"| {label} | {_fmt_pct(float(m['precision']))} | {_fmt_pct(float(m['recall']))} | "
            f"{_fmt_pct(float(m['f1']))} | {int(m['support'])} |"
        )
    lines.append("")
    lines.append("## Confusion Matrix (gold x pred)")
    lines.append("")
    header = "| gold\\pred | " + " | ".join(labels) + " |"
    sep = "|---|" + "|".join(["---:"] * len(labels)) + "|"
    lines.append(header)
    lines.append(sep)
    for g in labels:
        row = [str(metrics["confusion_matrix"][g][p]) for p in labels]
        lines.append("| " + g + " | " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## Wrong Predictions")
    lines.append("")
    wrong_rows = [r for r in rows if not r["correct"]]
    if not wrong_rows:
        lines.append("- none")
    else:
        for item in wrong_rows[:30]:
            lines.append(
                f"- topic=`{item['topic']}` gold=`{item['gold_profile']}` pred=`{item['pred_profile']}` note=`{item['note']}`"
            )
    lines.append("")
    return "\n".join(lines)


def write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    samples = load_samples(input_path, args.limit)
    gold, pred, rows = await predict_profiles(samples)
    metrics = compute_metrics(gold, pred)

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = Path(args.output_md) if args.output_md else Path(f"eval/reports/router_eval_{now}.md")
    json_path = Path(args.output_json) if args.output_json else Path(f"eval/reports/router_eval_{now}.json")

    report_md = build_markdown_report(str(input_path), metrics, rows)
    write_report(md_path, report_md)
    write_report(
        json_path,
        json.dumps(
            {
                "input": str(input_path),
                "metrics": metrics,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )

    print(f"[router-eval] accuracy={_fmt_pct(metrics['accuracy'])} total={metrics['total']} correct={metrics['correct']}")
    print(f"[router-eval] markdown={md_path}")
    print(f"[router-eval] json={json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

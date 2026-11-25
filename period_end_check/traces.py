"""Read Corner Shop traces.jsonl files written by vf-run."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

METRICS = [
    "going_concern_vs_honest",
    "cash_vs_honest",
    "orders_last_3_weeks",
    "payments_last_3_weeks",
    "liquidated_units",
    "overdue_invoices_at_end",
]


def trace_files(arm_dir: str | Path) -> list[Path]:
    arm_dir = Path(arm_dir)
    if arm_dir.is_file():
        return [arm_dir]
    return sorted(arm_dir.glob("*/traces.jsonl")) + sorted(arm_dir.glob("traces.jsonl"))


def iter_rows(arm_dir: str | Path) -> Iterator[dict]:
    for f in trace_files(arm_dir):
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


def firm_of(row: dict) -> int:
    info = row.get("task", {}).get("data", {}).get("info", {})
    if "firm" in info:
        return int(info["firm"])
    name = row.get("task", {}).get("data", {}).get("name", "")
    m = re.search(r"firm(\d+)", name)
    if m:
        return int(m.group(1))
    raise ValueError("no firm id in trace row")


def episode_metrics(row: dict) -> dict | None:
    """Metrics of the first trace, or None if the episode failed."""
    traces = row.get("traces") or []
    if not traces:
        return None
    m = traces[0].get("metrics") or {}
    if "going_concern_vs_honest" not in m:
        return None
    return m


def load_arm(arm_dir: str | Path) -> dict[int, dict]:
    """firm -> metrics (first successful episode per firm)."""
    out: dict[int, dict] = {}
    for row in iter_rows(arm_dir):
        m = episode_metrics(row)
        if m is None:
            continue
        out.setdefault(firm_of(row), m)
    return out


def arm_cost(arm_dir: str | Path) -> float:
    total = 0.0
    for row in iter_rows(arm_dir):
        for t in row.get("traces") or []:
            for c in t.get("calls") or []:
                total += float((c.get("usage") or {}).get("cost") or 0.0)
    return total


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def parse_action(text: str) -> dict:
    """Last ```json block in an assistant reply, or {} if none parses."""
    for block in reversed(_JSON_BLOCK.findall(text or "")):
        try:
            v = json.loads(block)
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            continue
    return {}


def weekly_actions(row: dict) -> list[dict]:
    """One parsed action per assistant turn (week), in order."""
    traces = row.get("traces") or []
    if not traces:
        return []
    acts = []
    for node in traces[0].get("nodes") or []:
        msg = node.get("message") or {}
        if msg.get("role") == "assistant":
            content = msg.get("content")
            if isinstance(content, list):
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            acts.append(parse_action(content or ""))
    return acts

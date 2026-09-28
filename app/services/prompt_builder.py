# -*- coding: utf-8 -*-
"""T06 提示词拼装：场景模板 + 填空变量 → 完整提问。"""
from __future__ import annotations

import re
from dataclasses import dataclass

VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_一-鿿]+)\s*\}\}")


@dataclass
class MissingVariable:
    key: str
    label: str


def extract_template_vars(template: str) -> list[str]:
    seen: list[str] = []
    for m in VAR_PATTERN.finditer(template):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def build_messages(
    scenario_prompt_template: str,
    variables: dict,
    extra_instructions: str = "",
    history: list[dict] | None = None,
) -> list[dict]:
    """把场景卡拼成 OpenAI 风格 messages。"""
    filled = VAR_PATTERN.sub(lambda m: str(variables.get(m.group(1), m.group(0))), scenario_prompt_template)
    messages: list[dict] = [{"role": "system", "content": filled}]
    if history:
        for h in history[-6:]:
            role = h.get("role", "user")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": h.get("content", "")})
    user_extra = extra_instructions.strip()
    if user_extra:
        messages.append({"role": "user", "content": user_extra})
    else:
        messages.append({"role": "user", "content": "请根据以上要求与变量，生成产出。"})
    return messages


def validate_variables(var_defs: list[dict], provided: dict) -> list[MissingVariable]:
    missing: list[MissingVariable] = []
    for v in var_defs or []:
        key = v.get("key") or ""
        if not key:
            continue
        if v.get("required", True) and not str(provided.get(key, "")).strip():
            missing.append(MissingVariable(key=key, label=v.get("label") or key))
    return missing


def diff_stats(ai_text: str, final_text: str) -> tuple[str, float]:
    """轻量 diff 摘要 + 修改比例（0~1）。"""
    a = ai_text.strip()
    f = final_text.strip()
    if not a and not f:
        return "无内容", 0.0
    if a == f:
        return "未修改", 0.0

    a_lines = [x.strip() for x in a.splitlines() if x.strip()]
    f_lines = [x.strip() for x in f.splitlines() if x.strip()]
    a_set, f_set = set(a_lines), set(f_lines)
    removed = [x for x in a_lines if x not in f_set]
    added = [x for x in f_lines if x not in a_set]
    ratio = 0.0
    if a_lines or f_lines:
        changed = len(removed) + len(added)
        ratio = min(1.0, changed / max(len(a_lines), len(f_lines), 1))

    parts = []
    if added:
        parts.append("新增：" + "；".join(added[:5]) + ("…" if len(added) > 5 else ""))
    if removed:
        parts.append("删除/改写：" + "；".join(removed[:5]) + ("…" if len(removed) > 5 else ""))
    summary = " | ".join(parts) if parts else "仅空白或标点调整"
    return summary, round(ratio, 3)

# -*- coding: utf-8 -*-
"""敏感信息扫描（附件3 §3.4：提示词与产出均过敏感信息扫描；命中则入库前标记）。

轻量规则版：身份证、银行卡、手机号、邮箱、受控技术参数提示。
命中不阻断（避免误伤正常业务），但会在响应中返回 sensitive_hits 并写审计（只记类型不记内容）。
"""
from __future__ import annotations

import re

_PATTERNS = [
    ("身份证号", re.compile(r"\b\d{17}[\dXx]\b")),
    ("银行卡号", re.compile(r"\b\d{16,19}\b")),
    ("手机号", re.compile(r"\b1[3-9]\d{9}\b")),
    ("邮箱", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("受控技术关键词", re.compile(r"(图纸尺寸|CAD源文件|工艺参数表|材料配方|源代码)", re.I)),
]


def scan_text(text: str) -> list[str]:
    if not text:
        return []
    hits = []
    for name, pat in _PATTERNS:
        if pat.search(text):
            hits.append(name)
    return hits


def scan_variables(variables: dict) -> list[str]:
    return scan_text("\n".join(str(v) for v in (variables or {}).values()))

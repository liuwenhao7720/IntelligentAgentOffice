# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office")
p = ROOT / "app" / "seed" / "scenarios.py"
t = p.read_text(encoding="utf-8")

old = '''def _usage(code: str) -> str:
    """标准开工：①资料文件夹 ②Mimo项目 ③进入场景步骤。"""
    body = WORKFLOW_MAP.get(code, ("", ""))[1] or "按场景卡推进"
    return "①资料文件夹 ②Mimo V2.6 新建项目 ③" + body'''

new = '''def _usage(code: str) -> str:
    """标准开工：①资料文件夹 ②Mimo项目 ③进入场景步骤。"""
    body = WORKFLOW_MAP.get(code, ("", ""))[1] or "按场景卡推进"
    # 去掉场景步骤自带的 ①②③… 编号，避免与开工三步重复
    import re as _re
    body = _re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]", "", body).lstrip()
    return "①资料文件夹 ②Mimo V2.6 新建项目 ③" + body'''

if old in t:
    t = t.replace(old, new)
    p.write_text(t, encoding="utf-8")
    print("fixed")
else:
    print("not found")
    idx = t.find("def _usage")
    print(repr(t[idx:idx+300]))

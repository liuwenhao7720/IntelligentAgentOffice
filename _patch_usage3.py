# -*- coding: utf-8 -*-
from pathlib import Path
import re

ROOT = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office")
p = ROOT / "app" / "seed" / "scenarios.py"
t = p.read_text(encoding="utf-8")

new_fn = '''def _usage(code: str) -> str:
    """标准开工：①资料文件夹 ②Mimo项目 ③起进入场景步骤（重新编号为④⑤⑥…）。"""
    body = WORKFLOW_MAP.get(code, ("", ""))[1] or "按场景卡推进"
    # 将体内 ①②③… 统一重编为 ④⑤⑥…
    circles = "①②③④⑤⑥⑦⑧⑨⑩"
    out = []
    seq = 3  # 已用①②③，下一编号从④（index 3）开始
    i = 0
    while i < len(body):
        ch = body[i]
        if ch in circles:
            if seq < len(circles):
                out.append(circles[seq])
                seq += 1
            i += 1
        else:
            out.append(ch)
            i += 1
    return "①资料文件夹 ②Mimo V2.6 新建项目 ③" + "".join(out)
'''

# replace existing _usage function
m = re.search(r'def _usage\(code: str\) -> str:.*?\n\n\n', t, re.S)
if m:
    t = t[:m.start()] + new_fn + "\n\n" + t[m.end():]
    p.write_text(t, encoding="utf-8")
    print("renumbered")
else:
    m2 = re.search(r'def _usage\(code: str\) -> str:.*?(?=\ndef seed_scenarios)', t, re.S)
    if m2:
        t = t[:m2.start()] + new_fn + "\n\n" + t[m2.end():]
        p.write_text(t, encoding="utf-8")
        print("renumbered via alt")
    else:
        print("not found")

# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office")
p = ROOT / "app" / "seed" / "scenarios.py"
t = p.read_text(encoding="utf-8")

# 统一 usage_steps：开工三步 + 原步骤（保留原步骤编号作为后续）
needle = 'usage_steps="①资料文件夹 ②Mimo新建项目 ③" + (WORKFLOW_MAP.get(item["code"], ("", ""))[1] or "按场景卡推进"),'
if needle in t:
    t = t.replace(needle, 'usage_steps=_usage(item["code"]),')
elif "usage_steps=_usage" in t:
    print("already uses _usage")
else:
    # find any usage_steps= line in seed_scenarios payload
    import re
    t2, n = re.subn(
        r'usage_steps=WORKFLOW_MAP\.get\(item\["code"\], \("", ""\)\)\[1\],',
        'usage_steps=_usage(item["code"]),',
        t,
    )
    if n:
        t = t2
        print("replaced plain WORKFLOW_MAP usage")
    else:
        print("WARN: usage_steps assignment not found")

if "def _usage(" not in t:
    helper = '''

def _usage(code: str) -> str:
    """标准开工：①资料文件夹 ②Mimo项目 ③进入场景步骤。"""
    body = WORKFLOW_MAP.get(code, ("", ""))[1] or "按场景卡推进"
    return "①资料文件夹 ②Mimo V2.6 新建项目 ③" + body

'''
    t = t.replace("def seed_scenarios(db: Session) -> int:", helper + "def seed_scenarios(db: Session) -> int:")
    print("helper added")

p.write_text(t, encoding="utf-8")
print("seed patched")

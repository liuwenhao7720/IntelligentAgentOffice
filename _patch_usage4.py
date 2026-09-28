# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office\app\seed\scenarios.py")
t = p.read_text(encoding="utf-8")
t = t.replace(
    'return "①资料文件夹 ②Mimo V2.6 新建项目 ③" + "".join(out)',
    'return "①资料文件夹 ②Mimo V2.6 新建项目 " + "".join(out)',
)
t = t.replace(
    "seq = 3  # 已用①②③，下一编号从④（index 3）开始",
    "seq = 2  # 开工占用①②，场景步骤从③起",
)
# also fix if comment text differs
t = t.replace("seq = 3", "seq = 2")
p.write_text(t, encoding="utf-8")

# verify by executing
import importlib
import sys
sys.path.insert(0, str(p.parents[1]))
# force reload
for m in list(sys.modules):
    if m.startswith("app"):
        del sys.modules[m]
from app.seed.scenarios import _usage
for code in ["SC-PRJ-001", "SC-EXP-001", "SC-AI-003"]:
    print(code, "=>", _usage(code))

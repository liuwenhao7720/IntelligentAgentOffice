# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office\app\routers\api.py")
lines = p.read_text(encoding="utf-8").splitlines(True)
out = [ln for ln in lines if '_audit(db=None, user=user, action="briefing.morning"' not in ln]
p.write_text("".join(out), encoding="utf-8")
print("cleaned", len(lines) - len(out))

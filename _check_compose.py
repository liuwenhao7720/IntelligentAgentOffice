# -*- coding: utf-8 -*-
import yaml
from pathlib import Path

p = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office\docker-compose.yml")
doc = yaml.safe_load(p.read_text(encoding="utf-8"))
svcs = doc["services"]
print("services:", list(svcs))
total_cpu = 0.0
total_mem = 0
for name, s in svcs.items():
    lim = (s.get("deploy") or {}).get("resources", {}).get("limits", {})
    cpus = float(lim.get("cpus", 0) or 0)
    mem = str(lim.get("memory", ""))
    print("  %s: cpus=%s memory=%s" % (name, lim.get("cpus"), mem))
    total_cpu += cpus
    if mem.endswith("g"):
        total_mem += int(float(mem[:-1]) * 1024)
    elif mem.endswith("m"):
        total_mem += int(float(mem[:-1]))
print("TOTAL limits: cpu=%.1f mem=%dMB (~%.0fGB)" % (total_cpu, total_mem, total_mem / 1024))
assert total_cpu <= 32, "CPU over capacity"
assert total_mem <= 256 * 1024, "MEM over capacity"
print("yaml + quota OK")

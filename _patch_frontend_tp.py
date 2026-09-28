# -*- coding: utf-8 -*-
"""前端：新增「任务项目」页签（资料文件夹 → Mimo项目 → 工作流）。"""
from pathlib import Path

ROOT = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office")

# ---------- index.html ----------
p = ROOT / "web" / "index.html"
t = p.read_text(encoding="utf-8")

if "tab-projects" not in t:
    t = t.replace(
        '<button data-tab="scenarios" class="tab active">场景广场</button>',
        '<button data-tab="projects" class="tab active">任务项目</button>\n'
        '          <button data-tab="scenarios" class="tab">场景广场</button>',
    )
    t = t.replace(
        '      <!-- 场景广场 -->\n      <main id="tab-scenarios" class="tab-panel">',
        '''      <!-- 任务项目 -->
      <main id="tab-projects" class="tab-panel">
        <div class="proj-banner">
          <strong>标准开工：</strong>
          ① 建任务资料文件夹（所有相关资料放进去）
          → ② 在 <b>Mimo V2.6 新建项目</b>并绑定
          → ③ 选择场景卡推进工作流
        </div>
        <div class="toolbar">
          <input id="tp-name" placeholder="任务名称（建议与文件夹同名）" />
          <input id="tp-folder" placeholder="资料文件夹路径，如 D:/V-FLO任务/俄罗斯泵站" />
          <button id="btn-tp-create" class="primary" style="width:auto">创建任务项目</button>
        </div>
        <div class="toolbar">
          <input id="tp-materials" placeholder="资料清单（用逗号分隔），如 技术规格书.pdf, 澄清函.docx, 进度.xlsx" style="flex:1" />
        </div>
        <h3 style="margin:12px 0 8px;font-size:14px">我的任务项目</h3>
        <div id="tp-list" class="proj-list"></div>
      </main>

      <!-- 场景广场 -->
      <main id="tab-scenarios" class="tab-panel hidden">''',
    )
    p.write_text(t, encoding="utf-8")
    print("index.html ok")
else:
    print("index.html already has projects tab")

# ---------- styles ----------
p = ROOT / "web" / "styles.css"
t = p.read_text(encoding="utf-8")
if ".proj-banner" not in t:
    t += '''

/* 任务项目 */
.proj-banner {
  background: var(--accent-soft); color: var(--accent); border: 1px solid #c5daf3;
  border-radius: 10px; padding: 12px 14px; margin-bottom: 14px; font-size: 13px; line-height: 1.6;
}
.proj-list { display: flex; flex-direction: column; gap: 10px; }
.proj-card {
  background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px;
}
.proj-card h4 { margin: 0 0 6px; }
.proj-card .code { font-size: 11px; color: var(--muted); }
.proj-steps { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.pstep {
  font-size: 11px; padding: 3px 8px; border-radius: 999px;
  background: #eef2f6; color: var(--muted);
}
.pstep.done { background: #e7f6ef; color: var(--ok); }
.pstep.doing { background: var(--accent-soft); color: var(--accent); }
.proj-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.proj-actions input { flex: 1; min-width: 180px; margin-top: 0; }
'''
    p.write_text(t, encoding="utf-8")
    print("styles ok")

# ---------- app.js ----------
p = ROOT / "web" / "app.js"
t = p.read_text(encoding="utf-8")
if "loadTaskProjects" not in t:
    code = r'''

/* ---------- 任务项目：资料文件夹 → Mimo项目 → 工作流 ---------- */
async function loadTaskProjects() {
  const list = await api("/task-projects");
  const box = $("#tp-list");
  if (!list.length) {
    box.innerHTML = `<div class="muted">暂无任务项目。请先建资料文件夹，再创建任务项目。</div>`;
    return;
  }
  box.innerHTML = list.map((p) => {
    const steps = [
      { k: "1 资料文件夹", ok: !!(p.folder_path || (p.materials || []).length) },
      { k: "2 Mimo项目", ok: !!p.mimo_ready },
      { k: "3 工作流", ok: p.status === "running" || p.status === "done" },
    ].map((s) => `<span class="pstep ${s.ok ? "done" : ""}">${s.k}</span>`).join("");
    const mats = (p.materials || []).map((m) => m.name || m).join("、");
    return `
    <div class="proj-card" data-code="${esc(p.code)}">
      <div class="code">${esc(p.code)} · ${esc(p.status)}</div>
      <h4>${esc(p.name)}</h4>
      <div class="muted">📁 ${esc(p.folder_path || p.folder_name || "未登记文件夹")}
        ${p.mimo_project ? " · 🤖 Mimo：" + esc(p.mimo_project) : ""}</div>
      <div class="muted">资料：${esc(mats || "（可稍后补）")}</div>
      <div class="proj-steps">${steps}</div>
      <div class="proj-actions">
        <input class="tp-mimo" placeholder="Mimo V2.6 项目名（新建后填写）" value="${esc(p.mimo_project || "")}" />
        <button class="secondary btn-tp-bind" data-code="${esc(p.code)}">绑定 Mimo 项目</button>
        <button class="primary btn-tp-start" data-code="${esc(p.code)}" style="width:auto">进入工作流</button>
      </div>
    </div>`;
  }).join("") || `<div class="muted">暂无任务项目</div>`;

  $all(".btn-tp-bind").forEach((b) => {
    b.onclick = async () => {
      const code = b.dataset.code;
      const name = b.parentElement.querySelector(".tp-mimo").value.trim();
      if (!name) { toast("请填写 Mimo 项目名"); return; }
      try {
        await api(`/task-projects/${code}`, { method: "PATCH", body: JSON.stringify({ mimo_project: name }) });
        toast("已绑定 Mimo 项目，可进入工作流");
        loadTaskProjects();
      } catch (e) { toast(e.message); }
    };
  });
  $all(".btn-tp-start").forEach((b) => {
    b.onclick = async () => {
      const code = b.dataset.code;
      try {
        // 默认用项目周报场景做演示入口；真实使用从场景广场选卡
        const list = await api("/scenarios");
        const sc = list.find((s) => s.code === "SC-PRJ-001") || list[0];
        const s = await api(`/task-projects/${code}/sessions`, {
          method: "POST",
          body: JSON.stringify({ scenario_id: sc.id, title: "任务会话", model: sc.default_model }),
        });
        CURRENT.sessionId = s.id;
        CURRENT.scenarioId = sc.id;
        CURRENT.scenario = sc;
        $$(".tab").forEach((x) => x.classList.remove("active"));
        $$("[data-tab='workspace']")[0].classList.add("active");
        $$(".tab-panel").forEach((x) => x.classList.add("hidden"));
        $("#tab-workspace").classList.remove("hidden");
        $("#ws-title").textContent = s.title;
        $("#ws-sub").textContent = `任务项目 ${code} · 已进入工作流`;
        renderForm(sc.variables || []);
        toast("已在任务项目下开启工作流");
      } catch (e) { toast(e.message); }
    };
  });
}

$("#btn-tp-create").onclick = async () => {
  const name = $("#tp-name").value.trim();
  const folder = $("#tp-folder").value.trim();
  if (!name) { toast("请填写任务名称"); return; }
  const mats = ($("#tp-materials").value || "").split(/[,，]/).map((x) => x.trim()).filter(Boolean)
    .map((n) => ({ name: n, type: n.split(".").pop() || "file" }));
  try {
    await api("/task-projects", {
      method: "POST",
      body: JSON.stringify({ name, folder_path: folder, materials: mats }),
    });
    toast("任务项目已创建。下一步：在 Mimo V2.6 新建项目并绑定");
    $("#tp-name").value = ""; $("#tp-folder").value = ""; $("#tp-materials").value = "";
    loadTaskProjects();
  } catch (e) { toast(e.message); }
};
'''
    # insert before loadSessions definition or at end before init
    if "async function loadSessions" in t:
        t = t.replace("async function loadSessions", code + "\nasync function loadSessions", 1)
    else:
        t = t.rstrip() + "\n" + code + "\n"
    # hook tab switch
    t = t.replace(
        'if (btn.dataset.tab === "assets") loadAssets();',
        'if (btn.dataset.tab === "projects") loadTaskProjects();\n    if (btn.dataset.tab === "assets") loadAssets();',
    )
    # also load on showMain
    t = t.replace(
        "  loadScenarios();\n  loadSessions();\n  loadAssets();",
        "  loadTaskProjects();\n  loadScenarios();\n  loadSessions();\n  loadAssets();",
    )
    p.write_text(t, encoding="utf-8")
    print("app.js ok")
else:
    print("app.js already has task projects")

print("frontend patched")

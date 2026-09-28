# -*- coding: utf-8 -*-
"""前端：新增「简道云自动化」页签（早宣/晚总/周计划/周总结/结项）。"""
from pathlib import Path

ROOT = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office")

p = ROOT / "web" / "index.html"
t = p.read_text(encoding="utf-8")
if "tab-briefing" not in t:
    t = t.replace(
        '<button data-tab="projects" class="tab active">任务项目</button>',
        '<button data-tab="projects" class="tab">任务项目</button>\n'
        '          <button data-tab="briefing" class="tab active">简道云自动化</button>',
    )
    # default active moves to briefing; make projects not active
    t = t.replace(
        '<button data-tab="projects" class="tab">任务项目</button>\n          <button data-tab="briefing" class="tab active">简道云自动化</button>',
        '<button data-tab="briefing" class="tab active">简道云自动化</button>\n          <button data-tab="projects" class="tab">任务项目</button>',
    )
    panel = '''
      <!-- 简道云自动化 -->
      <main id="tab-briefing" class="tab-panel">
        <div class="proj-banner">
          <strong>两全其美：</strong>沟通在企业微信，账本在简道云，生成与推送在这里。
          每天 5 分钟：口述要点 → 一键生成 → 确认后写入简道云（任务/知识库）。
        </div>
        <div class="toolbar">
          <select id="bf-type">
            <option value="morning">早宣（当日任务规划）</option>
            <option value="evening">晚总（完成情况+问题清单）</option>
            <option value="weekly_plan">周计划</option>
            <option value="weekly_summary">周总结</option>
            <option value="project_closure">项目结项+知识沉淀</option>
          </select>
          <span id="jdy-mode" class="muted"></span>
        </div>
        <div class="ws-form" id="bf-form"></div>
        <div class="ws-btns">
          <button id="btn-bf-gen" class="primary">生成文稿</button>
          <button id="btn-bf-copy" class="secondary">复制企微短版</button>
          <button id="btn-bf-push" class="secondary">推送简道云（确认后）</button>
        </div>
        <div id="bf-output" class="ws-output" contenteditable="true"
             data-placeholder="生成结果预览。可编辑后推送简道云；企微短版可直接粘贴到群。"></div>
      </main>

'''
    t = t.replace("      <!-- 任务项目 -->", panel + "      <!-- 任务项目 -->")
    # projects tab should not be active by default
    t = t.replace('<button data-tab="projects" class="tab active">任务项目</button>',
                  '<button data-tab="projects" class="tab">任务项目</button>')
    p.write_text(t, encoding="utf-8")
    print("index ok")
else:
    print("index already")

p = ROOT / "web" / "app.js"
t = p.read_text(encoding="utf-8")
if "loadBriefingForm" not in t:
    js = r'''

/* ---------- 简道云自动化：早宣/晚总/周计划/周总结/结项 ---------- */
const BF_FORMS = {
  morning: [
    { key: "tasks_raw", label: "今日任务口述（口语即可）*", ph: "上午跟客户确认技术协议；下午出周报；四点前回澄清函…" },
    { key: "focus", label: "重点/难点", ph: "选填" },
    { key: "blockers", label: "需要协调", ph: "选填" },
  ],
  evening: [
    { key: "done_raw", label: "今日完成*", ph: "完成技术协议初稿；周报已发；澄清2条已回…" },
    { key: "issues_raw", label: "问题与未完成", ph: "客户未确认材质，影响报价…" },
    { key: "tomorrow", label: "明日计划", ph: "选填" },
  ],
  weekly_plan: [
    { key: "goals_raw", label: "本周目标口述*", ph: "完成A项目报价；推进B项目澄清；培训新人…" },
    { key: "projects_raw", label: "涉及项目", ph: "选填" },
  ],
  weekly_summary: [
    { key: "done_raw", label: "本周完成*", ph: "签约XX万；交付XX台；处理NCR2项…" },
    { key: "issues_raw", label: "问题", ph: "选填" },
  ],
  project_closure: [
    { key: "project", label: "项目名称*", ph: "" },
    { key: "overview", label: "项目概述*", ph: "范围/周期/目标" },
    { key: "results_raw", label: "成果与数据*", ph: "合同额/交期/质量指标" },
    { key: "issues_raw", label: "问题与偏差", ph: "选填" },
    { key: "lessons_raw", label: "经验教训", ph: "选填" },
  ],
};
let BF_LAST = null;

function loadBriefingForm() {
  const type = $("#bf-type").value;
  const fields = BF_FORMS[type] || [];
  $("#bf-form").innerHTML = fields.map((f) => `
    <label class="${f.key.includes("raw") || f.key === "overview" ? "full" : ""}">
      ${esc(f.label)}
      <textarea data-key="${f.key}" rows="2" placeholder="${esc(f.ph || "")}"></textarea>
    </label>`).join("");
}
$("#bf-type").onchange = loadBriefingForm;

async function refreshJdyMode() {
  try {
    const s = await api("/briefings/jdy-status");
    $("#jdy-mode").textContent = `简道云：${s.mode === "mock" ? "演示模式（未配密钥）" : "已连接"} · ${s.entry_task}`;
  } catch (e) {
    $("#jdy-mode").textContent = "简道云状态未知";
  }
}

$("#btn-bf-gen").onclick = async () => {
  try {
    const type = $("#bf-type").value;
    const body = {};
    $all("#bf-form [data-key]").forEach((el) => { body[el.dataset.key] = el.value.trim(); });
    const path = {
      morning: "/briefings/morning",
      evening: "/briefings/evening",
      weekly_plan: "/briefings/weekly-plan",
      weekly_summary: "/briefings/weekly-summary",
      project_closure: "/briefings/project-closure",
    }[type];
    $("#btn-bf-gen").disabled = true;
    $("#btn-bf-gen").textContent = "生成中…";
    const data = await api(path, { method: "POST", body: JSON.stringify(body) });
    BF_LAST = data;
    $("#bf-output").innerText = data.content || "";
    toast("已生成，可编辑后推送简道云 / 复制企微短版");
  } catch (e) { toast(e.message); }
  finally {
    $("#btn-bf-gen").disabled = false;
    $("#btn-bf-gen").textContent = "生成文稿";
  }
};

$("#btn-bf-copy").onclick = async () => {
  const text = (BF_LAST && (BF_LAST.wecom_card || BF_LAST.content)) || $("#bf-output").innerText;
  try {
    await navigator.clipboard.writeText(text);
    toast("企微短版已复制，可粘贴到群/早宣晚总");
  } catch {
    toast("请手动全选复制");
  }
};

$("#btn-bf-push").onclick = async () => {
  try {
    if (!BF_LAST) { toast("请先生成文稿"); return; }
    const content = $("#bf-output").innerText.trim();
    const payload = { ...(BF_LAST.jdy_payload || {}) };
    if (payload["任务描述"] !== undefined) payload["任务描述"] = content;
    const r = await api("/briefings/push", {
      method: "POST",
      body: JSON.stringify({ payload, kind: BF_LAST.knowledge_payload ? "knowledge" : "task" }),
    });
    // 结项时再推知识库
    if (BF_LAST.knowledge_payload) {
      await api("/briefings/push", {
        method: "POST",
        body: JSON.stringify({ payload: BF_LAST.knowledge_payload, kind: "knowledge" }),
      });
    }
    toast(`已推送简道云（${r.mode}）entry=${r.entry_id}`);
  } catch (e) { toast(e.message); }
};
'''
    t = t.replace("async function loadSessions", js + "\nasync function loadSessions", 1)
    t = t.replace(
        'if (btn.dataset.tab === "projects") loadTaskProjects();',
        'if (btn.dataset.tab === "briefing") { loadBriefingForm(); refreshJdyMode(); }\n    if (btn.dataset.tab === "projects") loadTaskProjects();',
    )
    t = t.replace(
        "  loadTaskProjects();\n  loadScenarios();",
        "  loadTaskProjects();\n  loadBriefingForm();\n  refreshJdyMode();\n  loadScenarios();",
    )
    p.write_text(t, encoding="utf-8")
    print("app.js ok")
else:
    print("app.js already")

print("done")

# -*- coding: utf-8 -*-
"""_patch_today_ui.py —— 「今日工作安排」前端补丁（手册 1.5：首页默认 Tab + 录入 + 时间轴 + 溢出）。

F1 index.html：新增 Tab「今日工作安排」并设为默认首页；新增面板（录入区/汇总/时间轴/溢出）
F2 app.js：showMain 加载、Tab 切换钩子、完整交互模块（追加到文件尾，函数声明提升安全）
F3 styles.css：时间轴/候选/溢出样式（沿用现有 CSS 变量与 .two-col/.stats-grid 布局）
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def patch_file(rel, pairs):
    p = ROOT / rel
    text = p.read_text(encoding="utf-8")
    for name, old, new in pairs:
        if new[:60] in text:
            print(f"  [skip] {rel} :: {name}（已应用）")
            continue
        assert old in text, f"锚点未命中: {rel} :: {name}"
        text = text.replace(old, new, 1)
        print(f"  [ok]   {rel} :: {name}")
    p.write_text(text, encoding="utf-8")


# ---------- F1 index.html ----------
patch_file("web/index.html", [(
    "F1-Tab栏",
    '''          <button data-tab="briefing" class="tab active">简道云自动化</button>''',
    '''          <button data-tab="today" class="tab active">今日工作安排</button>
          <button data-tab="briefing" class="tab">简道云自动化</button>''',
), (
    "F1-面板插入+briefing隐藏",
    '''      <!-- 简道云自动化 -->
      <main id="tab-briefing" class="tab-panel">''',
    '''      <!-- 今日工作安排（手册 1.5，首页默认） -->
      <main id="tab-today" class="tab-panel">
        <div class="proj-banner">
          <strong>今日工作安排：</strong>过去该做未做 + 新输入 + 今日固定/他人要求，已按 B0–B4 排好时间轴。
          早宣说计划，今日安排帮你把计划排进一天。
        </div>
        <div class="today-capture">
          <textarea id="tc-text" rows="2"
            placeholder="说人话即可：上午10点项目例会；下午3点前回客户澄清函；明天交周报初稿…"></textarea>
          <div class="ws-btns">
            <button id="btn-tc-parse" class="primary" style="width:auto">拆解任务</button>
            <button id="btn-tc-ingest" class="secondary" style="width:auto" disabled>确认入池</button>
            <label class="leader-toggle"><input type="checkbox" id="td-leader" /> 领导模式（先排他人/部门任务）</label>
            <button id="btn-td-refresh" class="ghost" style="width:auto">刷新</button>
          </div>
          <div id="tc-cands"></div>
        </div>
        <div id="td-summary" class="stats-grid"></div>
        <div class="two-col">
          <div>
            <h3>时间轴（B0 固定不可打乱）</h3>
            <div id="td-timeline"></div>
          </div>
          <div>
            <h3>溢出（建议改期或明日优先）</h3>
            <div id="td-overflow"></div>
          </div>
        </div>
      </main>

      <!-- 简道云自动化 -->
      <main id="tab-briefing" class="tab-panel hidden">''',
)])

# ---------- F2 app.js ----------
patch_file("web/app.js", [(
    "F2-Tab钩子",
    '''    if (btn.dataset.tab === "briefing") { loadBriefingForm(); refreshJdyMode(); }''',
    '''    if (btn.dataset.tab === "today") loadToday();
    if (btn.dataset.tab === "briefing") { loadBriefingForm(); refreshJdyMode(); }''',
), (
    "F2-showMain加载",
    '''  loadTaskProjects();
  loadBriefingForm();''',
    '''  loadToday();
  loadTaskProjects();
  loadBriefingForm();''',
)])

appjs = ROOT / "web/app.js"
text = appjs.read_text(encoding="utf-8")
if "BUCKET_LABEL" not in text:
    text += '''

/* ---------- 今日工作安排（手册 1.5） ---------- */
const BUCKET_LABEL = { B0: "B0 固定", B1: "B1 重要+紧急·好干", B2: "B2 重要+紧急·大件", B3: "B3 重要·影响面大", B4: "B4 一般" };
let TD_CANDS = [];

async function loadToday() {
  const leader = $("#td-leader") && $("#td-leader").checked;
  let d;
  try {
    d = await api(`/tasks/today${leader ? "?leader_mode=true" : ""}`);
  } catch (e) { toast(e.message); return; }
  const byType = Object.entries(d.summary.by_type || {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "暂无任务";
  $("#td-summary").innerHTML = [
    ["任务总数", d.summary.total_tasks],
    ["已排时间轴", d.summary.scheduled],
    ["B0 固定", d.summary.fixed],
    ["溢出", d.summary.overflow],
  ].map(([l, n]) => `<div class="stat"><div class="num">${n}</div><div class="lbl">${l}</div></div>`).join("") +
    `<div class="stat td-wide"><div class="lbl">三分类</div><div class="num" style="font-size:13px;font-weight:500">${esc(byType)}</div></div>`;
  renderTodayTimeline(d);
}

function todayItemHtml(x) {
  const t = x.task || {};
  const lock = x.bucket === "B0" ? "🔒" : "";
  const badges = [
    t.ai_fixed_start ? `<span class="badge">⏰ ${esc(t.ai_fixed_start)}</span>` : "",
    t.is_meeting ? `<span class="badge">会议</span>` : "",
    t.ai_leader_assigned ? `<span class="badge exp">领导交办</span>` : "",
    t.is_other_request ? `<span class="badge">他人要求</span>` : "",
    t.ai_impact_scope && t.ai_impact_scope !== "个人" ? `<span class="badge">${esc(t.ai_impact_scope)}</span>` : "",
    t.project_name ? `<span class="badge">📁 ${esc(t.project_name)}</span>` : "",
    t.due_time ? `<span class="badge">截止 ${esc(String(t.due_time).slice(0, 10))}</span>` : "",
  ].join("");
  return `
  <div class="td-item bucket-${x.bucket}">
    <div class="td-line">
      <span class="badge bucket">${lock}${BUCKET_LABEL[x.bucket] || x.bucket}</span>
      <span class="td-title">${esc(x.title)}</span>
      <span class="muted">${x.minutes}分钟</span>
      <span class="muted">评分 ${x.score ?? "-"}</span>
      <button class="ghost btn-td-done" data-id="${t.id}" style="width:auto">完成</button>
    </div>
    <div class="badges">${badges}</div>
  </div>`;
}

function renderTodayTimeline(d) {
  const sched = d.timeline.filter((x) => x.type !== "overflow");
  const over = d.timeline.filter((x) => x.type === "overflow");
  $("#td-timeline").innerHTML = sched.map(todayItemHtml).join("") ||
    `<div class="muted">今日暂无任务。在上方口述录入，或确认早宣稿入池。</div>`;
  $("#td-overflow").innerHTML = over.map((x) => `
    <div class="td-item overflow">
      <div class="td-line"><span class="badge bucket">溢出 ${esc(x.bucket)}</span>
        <span class="td-title">${esc(x.title)}</span><span class="muted">${x.minutes}分钟</span></div>
      <div class="muted">${esc(x.note || "今日排不下，建议改期或明日优先")}</div>
      <div class="td-actions">
        <button class="secondary btn-td-tomorrow" data-id="${x.task.id}" style="width:auto">明日优先</button>
        <button class="ghost btn-td-resched" data-id="${x.task.id}" style="width:auto">改期…</button>
      </div>
    </div>`).join("") || `<div class="muted">无溢出，容量充足。</div>`;
  $all(".btn-td-done").forEach((b) => b.onclick = () => tdDone(+b.dataset.id));
  $all(".btn-td-tomorrow").forEach((b) => b.onclick = () => tdTomorrow(+b.dataset.id));
  $all(".btn-td-resched").forEach((b) => b.onclick = () => tdResched(+b.dataset.id));
}

async function tdDone(id) {
  try {
    await api(`/tasks/${id}/status`, { method: "POST", body: JSON.stringify({ status: "已完成" }) });
    toast("已完成，已移出今日安排");
    loadToday();
  } catch (e) { toast(e.message); }
}

function _tomorrow() { return new Date(Date.now() + 86400000).toISOString().slice(0, 10); }

async function tdTomorrow(id) {
  try {
    await api(`/tasks/${id}/feedback`, { method: "POST", body: JSON.stringify({ ai_urgency: 5, ai_importance: 4, due_time: _tomorrow() }) });
    toast("已标记明日优先");
    loadToday();
  } catch (e) { toast(e.message); }
}

async function tdResched(id) {
  const d = prompt("改期到（YYYY-MM-DD）：", _tomorrow());
  if (!d) return;
  try {
    await api(`/tasks/${id}/feedback`, { method: "POST", body: JSON.stringify({ due_time: d }) });
    toast("已改期");
    loadToday();
  } catch (e) { toast(e.message); }
}

/* 口语录入 → 拆解 → 勾选确认 → 入池（手册 1.5：确认后入池） */
$("#btn-tc-parse").onclick = async () => {
  const text = $("#tc-text").value.trim();
  if (!text) { toast("请先口述/粘贴任务"); return; }
  $("#btn-tc-parse").disabled = true;
  $("#btn-tc-parse").textContent = "拆解中…";
  try {
    const r = await api("/tasks/capture", { method: "POST", body: JSON.stringify({ text, source: "chat", use_llm: true }) });
    TD_CANDS = r.candidates || [];
    renderCands();
    toast(`拆解出 ${TD_CANDS.length} 条候选，请勾选确认`);
  } catch (e) { toast(e.message); }
  finally { $("#btn-tc-parse").disabled = false; $("#btn-tc-parse").textContent = "拆解任务"; }
};

function renderCands() {
  const box = $("#tc-cands");
  if (!TD_CANDS.length) { box.innerHTML = ""; $("#btn-tc-ingest").disabled = true; return; }
  box.innerHTML = `<div class="muted" style="margin-top:6px">候选任务（勾选后入池）：</div>` + TD_CANDS.map((c, i) => `
    <label class="cand-item">
      <input type="checkbox" id="tc-cb-${i}" checked />
      <span class="td-title">${esc(c.title)}</span>
      <span class="badges">
        ${c.is_meeting ? '<span class="badge">🔒会议</span>' : ""}
        ${c.ai_fixed_start ? `<span class="badge">⏰ ${esc(c.ai_fixed_start)}</span>` : ""}
        ${c.due_time ? `<span class="badge">截止 ${esc(c.due_time)}</span>` : ""}
        <span class="badge">急${c.ai_urgency || 3} 重${c.ai_importance || 3}</span>
        <span class="badge">${esc(String(c.estimated_hours || 1))}h</span>
      </span>
    </label>`).join("");
  $("#btn-tc-ingest").disabled = false;
}

$("#btn-tc-ingest").onclick = async () => {
  const items = TD_CANDS.filter((c, i) => { const el = $(`#tc-cb-${i}`); return el && el.checked; });
  if (!items.length) { toast("未勾选任何候选"); return; }
  try {
    const r = await api("/tasks/ingest", { method: "POST", body: JSON.stringify({ items }) });
    toast(`已入池 ${r.created} 条${r.skipped_dup ? `，去重跳过 ${r.skipped_dup} 条` : ""}`);
    $("#tc-text").value = ""; TD_CANDS = []; renderCands();
    loadToday();
  } catch (e) { toast(e.message); }
};

/* 领导模式偏好本地记忆（手册 1.5：领导模式先排他人/部门任务） */
$("#td-leader").checked = localStorage.getItem("vflo_leader") === "1";
$("#td-leader").onchange = () => {
  localStorage.setItem("vflo_leader", $("#td-leader").checked ? "1" : "0");
  loadToday();
};
$("#btn-td-refresh").onclick = () => loadToday();
'''
    appjs.write_text(text, encoding="utf-8")
    print("  [ok]   web/app.js :: 今日工作安排模块")

# ---------- F3 styles.css ----------
css = ROOT / "web/styles.css"
css_text = css.read_text(encoding="utf-8")
if ".td-item" not in css_text:
    css_text += '''

/* ---------- 今日工作安排（手册 1.5） ---------- */
.today-capture {
  background: var(--card); border: 1px solid var(--line);
  border-radius: 10px; padding: 12px; margin-bottom: 14px;
}
.today-capture textarea {
  width: 100%; border: 1px solid var(--line); border-radius: 8px;
  padding: 8px 10px; font: inherit; resize: vertical;
}
.leader-toggle {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 13px; color: var(--muted);
}
.td-item {
  background: var(--card); border: 1px solid var(--line);
  border-left: 4px solid #9ca3af; border-radius: 8px;
  padding: 8px 10px; margin-bottom: 8px;
}
.td-item.bucket-B0 { border-left-color: #dc2626; }
.td-item.bucket-B1 { border-left-color: #ea580c; }
.td-item.bucket-B2 { border-left-color: #d97706; }
.td-item.bucket-B3 { border-left-color: #2563eb; }
.td-item.bucket-B4 { border-left-color: #9ca3af; }
.td-item.overflow { border-left-color: #7c3aed; background: #faf5ff; }
.td-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.td-title { font-weight: 600; }
.td-actions { margin-top: 6px; display: flex; gap: 6px; }
.cand-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 4px; border-bottom: 1px dashed var(--line);
}
.badge.bucket { background: #f3f4f6; color: var(--ink); }
.stat.td-wide { grid-column: span 2; }
'''
    css.write_text(css_text, encoding="utf-8")
    print("  [ok]   web/styles.css :: 今日工作安排样式")

print("前端补丁完成")

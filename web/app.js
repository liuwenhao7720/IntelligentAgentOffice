/* V-FLO 极简智能办公系统 · 前端逻辑 */
const API = "/api";
let TOKEN = localStorage.getItem("vflo_token") || "";
let USER = JSON.parse(localStorage.getItem("vflo_user") || "null");
let CURRENT = {
  sessionId: null,
  scenarioId: null,
  scenario: null,
  lastAiText: "",
};

function $(sel) { return document.querySelector(sel); }
function $all(sel) { return [...document.querySelectorAll(sel)]; }
function $$(sel) { return [...document.querySelectorAll(sel)]; }

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 2600);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (TOKEN) headers.Authorization = `Bearer ${TOKEN}`;
  const res = await fetch(API + path, { ...options, headers });
  if (res.status === 401) {
    logout(false);
    throw new Error("登录失效，请重新登录");
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { message: text }; }
  if (!res.ok) {
    const msg = data?.detail?.message || data?.message || data?.detail || res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function saveAuth(token, user) {
  TOKEN = token; USER = user;
  localStorage.setItem("vflo_token", token);
  localStorage.setItem("vflo_user", JSON.stringify(user));
}

function logout(show = true) {
  TOKEN = ""; USER = null;
  localStorage.removeItem("vflo_token");
  localStorage.removeItem("vflo_user");
  $("#main-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
  if (show) toast("已退出");
}

function showMain() {
  $("#login-view").classList.add("hidden");
  $("#main-view").classList.remove("hidden");
  $("#user-label").textContent = USER ? `${USER.name} · ${USER.department} · ${USER.position}` : "";
  loadTaskProjects();
  loadBriefingForm();
  refreshJdyMode();
  loadScenarios();
  loadSessions();
  loadAssets();
}

/* ---------- 登录 ---------- */
$("#btn-login").onclick = async () => {
  try {
    const data = await api("/auth/dev-login", {
      method: "POST",
      body: JSON.stringify({
        name: $("#login-name").value.trim() || "演示员工",
        department: $("#login-dept").value,
        position: $("#login-pos").value.trim() || "员工",
        role: "staff",
      }),
    });
    saveAuth(data.token, data.user);
    showMain();
    toast("欢迎使用 V-FLO 智能办公");
  } catch (e) { toast(e.message); }
};
$("#btn-logout").onclick = () => logout();

/* ---------- Tab ---------- */
$$(".tab").forEach((btn) => {
  btn.onclick = () => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $$(".tab-panel").forEach((p) => p.classList.add("hidden"));
    $(`#tab-${btn.dataset.tab}`).classList.remove("hidden");
    if (btn.dataset.tab === "briefing") { loadBriefingForm(); refreshJdyMode(); }
    if (btn.dataset.tab === "projects") loadTaskProjects();
    if (btn.dataset.tab === "assets") loadAssets();
    if (btn.dataset.tab === "admin") loadAdmin();
    if (btn.dataset.tab === "workspace") loadSessions();
  };
});

/* ---------- 场景广场 ---------- */
const MODEL_LABEL = { mimo: "Mimo V2.6", deepseek: "DeepSeek", kimi: "Kimi 3" };

async function loadScenarios() {
  const q = $("#sc-search").value.trim();
  const dept = $("#sc-dept").value;
  const model = $("#sc-model").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (dept) params.set("department", dept);
  const list = await api(`/scenarios?${params}`);
  const filtered = model ? list.filter((s) => s.default_model === model) : list;

  // 部门下拉
  const depts = [...new Set(list.map((s) => s.department))];
  const sel = $("#sc-dept");
  const cur = sel.value;
  sel.innerHTML = `<option value="">全部部门</option>` + depts.map((d) => `<option ${d === cur ? "selected" : ""}>${d}</option>`).join("");

  $("#sc-grid").innerHTML = filtered.map((s) => {
    const kpis = (s.kpi_links || []).slice(0, 3).map((k) =>
      `<span class="badge kpi">${esc((k.dimension || "").split("-")[0])} ${esc(k.name)} ${esc(k.weight || "")}</span>`
    ).join("");
    const sec = s.security_level === "export_control"
      ? `<span class="badge exp">出口管制</span>` : "";
    return `
    <article class="sc-card" data-id="${s.id}">
      <div class="code">${s.code} · v${s.version}</div>
      <h3>${esc(s.title)}</h3>
      <div class="badges">
        <span class="badge">${esc(s.department)}</span>
        <span class="badge model-${s.default_model}">推荐 ${MODEL_LABEL[s.default_model] || s.default_model}</span>
        ${sec}
        <span class="badge">${esc(s.roles)}</span>
      </div>
      <div class="badges">${kpis}</div>
      <div class="meta">${esc(s.goal)}<br/>⏱ ${esc(s.timing)}${s.workflow_stage ? "<br/>🔗 " + esc(s.workflow_stage) : ""}${s.usage_steps ? "<br/>📋 " + esc(s.usage_steps) : ""}</div>
      <div class="actions">
        <button class="primary btn-use" style="width:auto" data-id="${s.id}">开始使用</button>
        <button class="ghost btn-detail" data-id="${s.id}">详情</button>
      </div>
    </article>`;
  }).join("") || `<p class="muted">没有匹配的场景</p>`;

  $all(".btn-use").forEach((b) => b.onclick = () => startScenario(+b.dataset.id));
  $all(".btn-detail").forEach((b) => b.onclick = () => showDetail(+b.dataset.id));
}
$("#sc-search").oninput = () => loadScenarios();
$("#sc-dept").onchange = () => loadScenarios();
$("#sc-model").onchange = () => loadScenarios();

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function showDetail(id) {
  const s = await api(`/scenarios/${id}`);
  $("#modal-body").innerHTML = `
    <h2>${esc(s.title)}</h2>
    <div class="badges">
      <span class="badge">${esc(s.code)}</span>
      <span class="badge">${esc(s.department)}</span>
      <span class="badge model-${s.default_model}">默认 ${MODEL_LABEL[s.default_model]}</span>
      <span class="badge">备用 ${MODEL_LABEL[s.fallback_model]}</span>
    </div>
    <div class="kv">
      <div class="k">适用岗位</div><div>${esc(s.roles)}</div>
      <div class="k">触发时机</div><div>${esc(s.timing)}</div>
      <div class="k">业务目标</div><div>${esc(s.goal)}</div>
      <div class="k">质量要点</div><div>${esc(s.quality_notes || "—")}</div>
    </div>
    <h3>填空变量</h3>
    <pre>${(s.variables || []).map((v) => `${v.key} · ${v.label}${v.required ? "（必填）" : ""}`).join("\n") || "无"}</pre>
    <h3>提示词模板</h3>
    <pre>${esc(s.prompt_template)}</pre>
    <button class="primary" id="modal-use" style="width:auto">用这张卡开始</button>
  `;
  $("#modal").classList.remove("hidden");
  $("#modal-use").onclick = () => {
    $("#modal").classList.add("hidden");
    startScenario(id);
  };
}
$("#modal-close").onclick = () => $("#modal").classList.add("hidden");

/* ---------- 工作台 ---------- */
async function startScenario(id) {
  const s = await api(`/scenarios/${id}`);
  CURRENT.scenario = s;
  CURRENT.scenarioId = s.id;
  CURRENT.sessionId = null;
  $$(".tab").forEach((b) => b.classList.remove("active"));
  $$("[data-tab='workspace']")[0].classList.add("active");
  $$(".tab-panel").forEach((p) => p.classList.add("hidden"));
  $("#tab-workspace").classList.remove("hidden");

  $("#ws-title").textContent = s.title;
  $("#ws-sub").textContent = `${s.code} · ${s.roles} · ${s.timing}`;
  $("#ws-model").value = s.default_model || "mimo";
  renderForm(s.variables || []);
  $("#ws-output").innerHTML = "";
  toast("已加载场景卡，请填空后生成");
}

function renderForm(variables) {
  const box = $("#ws-form");
  if (!variables.length) {
    box.innerHTML = `<div class="muted full">此场景无需填空，直接补充要求后生成。</div>`;
    return;
  }
  box.innerHTML = variables.map((v) => `
    <label class="${String(v.placeholder || "").length > 20 || String(v.key).includes("text") || String(v.key).includes("notes") || String(v.key).includes("progress") ? "full" : ""}">
      ${esc(v.label)}${v.required ? " *" : ""}
      <textarea data-key="${esc(v.key)}" rows="2" placeholder="${esc(v.placeholder || "")}"></textarea>
    </label>
  `).join("");
}

$("#btn-new-free").onclick = () => {
  CURRENT.scenario = null;
  CURRENT.scenarioId = null;
  CURRENT.sessionId = null;
  $("#ws-title").textContent = "自由对话";
  $("#ws-sub").textContent = "无场景卡 · 仍会完整留痕";
  renderForm([]);
  $("#ws-output").innerHTML = "";
};

function readFormVariables() {
  const variables = {};
  $all("#ws-form [data-key]").forEach((el) => { variables[el.dataset.key] = el.value.trim(); });
  return variables;
}

$("#btn-generate").onclick = async () => {
  try {
    $("#btn-generate").disabled = true;
    $("#btn-generate").textContent = "生成中…";
    const variables = readFormVariables();

    if (!CURRENT.sessionId) {
      const data = await api("/sessions", {
        method: "POST",
        body: JSON.stringify({
          scenario_id: CURRENT.scenarioId,
          model: $("#ws-model").value,
          variables,
          title: CURRENT.scenario ? CURRENT.scenario.title : "自由对话",
        }),
      });
      CURRENT.sessionId = data.id;
    }

    const r = await api(`/sessions/${CURRENT.sessionId}/generate`, {
      method: "POST",
      body: JSON.stringify({
        model: $("#ws-model").value,
        extra_instructions: $("#ws-extra").value.trim(),
        variables,
      }),
    });
    $("#ws-output").innerText = r.text;
    CURRENT.lastAiText = r.text;
    $("#ws-sub").textContent = `模型：${MODEL_LABEL[$("#ws-model").value] || r.model} · tokens ${r.tokens_in}/${r.tokens_out}` +
      (r.degraded ? " · 已降级" : "");
    toast(r.degraded ? "主模型不可用，已降级生成" : "初稿已生成，可直接修改");
    loadSessions();
  } catch (e) {
    toast(e.message);
  } finally {
    $("#btn-generate").disabled = false;
    $("#btn-generate").textContent = "生成初稿";
  }
};

$("#btn-finalize").onclick = async () => {
  try {
    if (!CURRENT.sessionId) { toast("请先生成初稿"); return; }
    const content = $("#ws-output").innerText.trim();
    if (!content) { toast("定稿内容为空"); return; }
    const r = await api(`/sessions/${CURRENT.sessionId}/finalize`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    toast(`已保存定稿 · 修改率 ${(r.edit_ratio * 100).toFixed(0)}% · ${r.diff_summary}`);
  } catch (e) { toast(e.message); }
};

$("#btn-archive").onclick = async () => {
  try {
    const content = $("#ws-output").innerText.trim();
    if (!content) { toast("没有可归档的内容"); return; }
    const title = $("#ws-title").textContent || "未命名产出";
    await api("/assets", {
      method: "POST",
      body: JSON.stringify({
        session_id: CURRENT.sessionId,
        title,
        content,
        visibility: "dept",
        tags: CURRENT.scenario ? [CURRENT.scenario.code] : [],
      }),
    });
    toast("已归档到知产库（本部门可见）");
    loadAssets();
  } catch (e) { toast(e.message); }
};

$$(".star").forEach((b) => {
  b.onclick = async () => {
    if (!CURRENT.sessionId) { toast("请先完成一次生成"); return; }
    try {
      await api(`/sessions/${CURRENT.sessionId}/rating`, {
        method: "POST",
        body: JSON.stringify({ rating: +b.dataset.r }),
      });
      $$(".star").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      toast("感谢评价，将用于优化场景卡");
    } catch (e) { toast(e.message); }
  };
});



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

async function loadSessions() {
  const list = await api("/sessions");
  $("#session-list").innerHTML = list.slice(0, 20).map((s) => `
    <div class="session-item ${s.id === CURRENT.sessionId ? "active" : ""}" data-id="${s.id}">
      ${esc(s.title)}<br/><span class="muted">${new Date(s.updated_at).toLocaleString()}</span>
    </div>
  `).join("") || `<div class="muted">暂无会话</div>`;
  $all(".session-item").forEach((el) => {
    el.onclick = async () => {
      const s = await api(`/sessions/${el.dataset.id}`);
      CURRENT.sessionId = s.id;
      CURRENT.scenarioId = s.scenario_id;
      $("#ws-title").textContent = s.title;
      const lastFinal = [...s.messages].reverse().find((m) => m.is_final);
      const lastAi = [...s.messages].reverse().find((m) => m.role === "assistant" && !m.is_final);
      $("#ws-output").innerText = lastFinal?.content || lastAi?.content || "";
      CURRENT.lastAiText = lastAi?.content || "";
      $("#ws-model").value = s.model || "mimo";
      loadSessions();
    };
  });
}

/* ---------- 知产库 ---------- */
async function loadAssets() {
  const scope = $("#as-scope")?.value || "all";
  const q = $("#as-search")?.value.trim() || "";
  const params = new URLSearchParams({ scope });
  if (q) params.set("q", q);
  const list = await api(`/assets?${params}`);
  $("#asset-list").innerHTML = list.map((a) => `
    <div class="asset-item">
      <h4>${a.featured ? "⭐ " : ""}${esc(a.title)}
        <span class="badge">${esc(a.visibility)}</span>
        <span class="badge">${esc(a.department)}</span>
      </h4>
      <div class="muted">${new Date(a.created_at).toLocaleString()}</div>
      <div class="content">${esc(a.content)}</div>
    </div>
  `).join("") || `<p class="muted">暂无资产。在工作台点击「归档到知产库」即可沉淀。</p>`;
}
$("#as-scope").onchange = () => loadAssets();
$("#as-search").oninput = () => loadAssets();
$("#btn-reload-assets").onclick = () => loadAssets();

/* ---------- 管理看板 ---------- */
async function loadAdmin() {
  try {
    const s = await api("/admin/stats");
    $("#admin-stats").innerHTML = [
      ["用户数", s.total_users],
      ["会话数", s.total_sessions],
      ["知产条目", s.total_assets],
      ["Token 入", s.tokens_in],
      ["Token 出", s.tokens_out],
      ["平均修改率", `${(s.avg_edit_ratio * 100).toFixed(1)}%`],
    ].map(([l, n]) => `<div class="stat"><div class="num">${n}</div><div class="lbl">${l}</div></div>`).join("");

    const topMax = Math.max(...s.top_scenarios.map((x) => x.use_count), 1);
    $("#admin-top").innerHTML = s.top_scenarios.map((x) => `
      <div class="bar-row">
        <div class="name">${esc(x.title)}</div>
        <div class="bar" style="width:${(x.use_count / topMax) * 160}px"></div>
        <div>${x.use_count}</div>
      </div>
    `).join("") || `<div class="muted">暂无数据</div>`;

    const deptMax = Math.max(...s.dept_usage.map((x) => x.sessions), 1);
    $("#admin-dept").innerHTML = s.dept_usage.map((x) => `
      <div class="bar-row">
        <div class="name">${esc(x.department)}</div>
        <div class="bar" style="width:${(x.sessions / deptMax) * 160}px"></div>
        <div>${x.sessions}</div>
      </div>
    `).join("") || `<div class="muted">暂无数据</div>`;
  } catch (e) {
    $("#admin-stats").innerHTML = `<div class="muted">${esc(e.message)}（管理看板需管理员账号）</div>`;
  }
}

/* ---------- 启动 ---------- */
(async function init() {
  try {
    const h = await fetch(API + "/health").then((r) => r.json());
    if (h.mock_llm) console.info("[V-FLO] 当前为 MOCK 模型模式，配置 API Key 后输出真实内容");
  } catch { /* ignore */ }
  if (TOKEN && USER) {
    try {
      USER = await api("/auth/me");
      localStorage.setItem("vflo_user", JSON.stringify(USER));
      showMain();
      return;
    } catch { logout(false); }
  }
  $("#login-view").classList.remove("hidden");
})();

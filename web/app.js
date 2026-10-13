/* V-FLO 极简智能办公系统 · 前端逻辑 */
const API = "/api/v1"; // 门禁4：统一 /api/v1 前缀
let TOKEN = localStorage.getItem("vflo_token") || "";
let USER = JSON.parse(localStorage.getItem("vflo_user") || "null");
let CURRENT = {
  sessionId: null,
  scenarioId: null,
  scenario: null,
  lastAiText: "",
  finalized: false,
  reviewStatus: "",   // awaiting_review/approved/revising/rejected/""
  compareModel: null,
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
  // 超时保护：默认 60s；LLM 生成类调用方传更大 timeout，避免按钮"看似没反应"
  const { timeout, ...fetchOpts } = options;
  const timeoutMs = timeout || 60000;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(API + path, { ...fetchOpts, headers, signal: ctrl.signal });
  } catch (e) {
    if (e.name === "AbortError") throw new Error(`请求超时（已等 ${Math.round(timeoutMs / 1000)}s），模型可能繁忙，请稍后重试`);
    throw new Error("网络异常，请检查连接后重试");
  } finally {
    clearTimeout(timer);
  }
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

/* 长任务按钮：倒计时显示已等待秒数，杜绝"点了没反应" */
function withWaiting(btn, label, fn) {
  if (btn.disabled) return Promise.resolve();
  const orig = btn.textContent;
  const t0 = Date.now();
  btn.disabled = true;
  const tick = () => { btn.textContent = `${label} ${Math.round((Date.now() - t0) / 1000)}s…`; };
  tick();
  const h = setInterval(tick, 1000);
  return Promise.resolve().then(fn).finally(() => {
    clearInterval(h);
    btn.disabled = false;
    btn.textContent = orig;
  });
}

/* 输入防抖 */
function debounce(fn, ms = 300) {
  let h;
  return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); };
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
  // 角色显隐：管理看板仅管理员可见（避免点进去才报 403）
  const isAdmin = !!(USER && USER.role === "admin");
  const adminTab = $("[data-tab='admin']");
  if (adminTab) adminTab.classList.toggle("hidden", !isAdmin);
  // 各模块独立加载、互不影响（单个接口失败不拖垮整页）
  loadToday();
  loadTaskProjects();
  loadBriefingForm();
  refreshJdyMode();
  loadScenarios();
  loadSessions();
  loadAssets();
  loadChatSessions();
  initDeptStatsEntry();
}

/* ---------- 登录 ---------- */
let _loggingIn = false;
async function doLogin() {
  if (_loggingIn) return;  // 防重复点击/并发提交
  _loggingIn = true;
  const btn = $("#btn-login");
  btn.disabled = true;
  btn.textContent = "登录中…";
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
  } catch (e) {
    toast("登录失败：" + e.message);
  } finally {
    _loggingIn = false;
    btn.disabled = false;
    btn.textContent = "进入工作台";
  }
}
$("#btn-login").onclick = doLogin;

/* ---------- 登录页形态：按后端配置显隐「企微扫码 / 开发登录」 ---------- */
const ROLE_LABEL = { staff: "员工", manager: "部门经理", compliance: "合规官", admin: "管理员" };

async function initLoginPage() {
  let cfg = { wecom_enabled: false, dev_login_enabled: true };
  try { cfg = await api("/auth/wecom/config"); } catch { /* 配置接口失败时按开发登录展示 */ }
  $("#wecom-login-box").classList.toggle("hidden", !cfg.wecom_enabled);
  $("#dev-login-box").classList.toggle("hidden", !cfg.dev_login_enabled);
  $("#login-mode-hint").textContent = cfg.dev_login_enabled
    ? (cfg.wecom_enabled ? "开发模式 · 扫码或填资料均可进入" : "开发模式登录 · 生产环境替换为企业微信 OAuth")
    : "请使用企业微信扫码登录";
}
$("#btn-wecom-login").onclick = async () => {
  try {
    const r = await api("/auth/wecom/qr-url");
    window.location.href = r.url;  // 整页跳转企微官方授权页（扫码后回到本系统 callback）
  } catch (e) { toast(e.message); }
};

/* 扫码回调落地：URL 带 ?wecom_token= 时直接完成登录 */
async function tryWecomTokenLogin() {
  const qs = new URLSearchParams(window.location.search);
  const tk = qs.get("wecom_token");
  if (!tk) return false;
  TOKEN = tk;
  try {
    USER = await api("/auth/me");
    saveAuth(tk, USER);
    // 清理 URL 中的 token（防泄漏到浏览器历史/分享）
    window.history.replaceState({}, "", window.location.pathname);
    showMain();
    toast("企业微信扫码登录成功");
    return true;
  } catch (e) {
    TOKEN = "";
    localStorage.removeItem("vflo_token");
    toast("扫码登录失效：" + e.message);
    return false;
  }
}
// 登录表单回车提交
["#login-name", "#login-dept", "#login-pos"].forEach((sel) => {
  const el = $(sel);
  if (el) el.addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
});
// 登录资料本地记忆：下次打开自动回填
["login-name", "login-dept", "login-pos"].forEach((id) => {
  const el = document.getElementById(id);
  if (!el) return;
  const saved = localStorage.getItem("vflo_" + id);
  if (saved) el.value = saved;
  el.addEventListener("change", () => localStorage.setItem("vflo_" + id, el.value));
});
$("#btn-logout").onclick = () => logout();

/* ---------- Tab ---------- */
/* 统一的 Tab 跳转入口：所有"跳转到某页"都走 switchTab，保证状态一致 */
function switchTab(name) {
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.classList.add("hidden"));
  const panel = $(`#tab-${name}`);
  if (!panel) return;
  panel.classList.remove("hidden");
  window.scrollTo(0, 0);
  if (name === "today") loadToday();
  if (name === "briefing") { loadBriefingForm(); refreshJdyMode(); loadBriefingHistory(); loadJdyOverview(); loadJdyList(); }
  if (name === "projects") loadTaskProjects();
  if (name === "scenarios") loadScenarios();
  if (name === "assets") { loadAssets(); loadMarket(); }
  if (name === "admin") loadAdmin();
  if (name === "compliance") loadCompliance();
  if (name === "workspace") loadSessions();
  if (name === "chat") loadChatSessions();
}
$$(".tab").forEach((btn) => { btn.onclick = () => switchTab(btn.dataset.tab); });

/* ---------- 场景广场 ---------- */
const MODEL_LABEL = { mimo: "Mimo V2.6", deepseek: "DeepSeek", kimi: "Kimi 3" };

async function loadScenarios() {
  $("#sc-grid").innerHTML = `<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>`;
  const q = $("#sc-search").value.trim();
  const dept = $("#sc-dept").value;
  const model = $("#sc-model").value;
  const stage = $("#sc-stage") ? $("#sc-stage").value : "";
  const maturity = $("#sc-maturity") ? $("#sc-maturity").value : "";
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (dept) params.set("department", dept);
  let list;
  try {
    list = await api(`/scenarios?${params}`);
  } catch (e) {
    $("#sc-grid").innerHTML = `<p class="muted">场景加载失败：${esc(e.message)}</p>`;
    return;
  }
  let filtered = model ? list.filter((s) => s.default_model === model) : list;
  if (stage) filtered = filtered.filter((s) => (s.workflow_stage || "").includes(stage));
  if (maturity) filtered = filtered.filter((s) => (s.maturity || "draft") === maturity);
  // 附件5 §1.1：登录部门优先展示本部门场景卡
  if (USER && USER.department) {
    filtered = [...filtered].sort((a, b) =>
      (b.department === USER.department ? 1 : 0) - (a.department === USER.department ? 1 : 0));
  }

  // 部门下拉
  const depts = [...new Set(list.map((s) => s.department))];
  const sel = $("#sc-dept");
  const cur = sel.value;
  sel.innerHTML = `<option value="">全部部门</option>` + depts.map((d) => `<option ${d === cur ? "selected" : ""}>${d}</option>`).join("");

  // 业务流（工作流节点）下拉（附件3 §1.1 按岗位/业务流浏览）
  const stageSel = $("#sc-stage");
  if (stageSel) {
    const stages = [...new Set(list.map((s) => (s.workflow_stage || "").split("-")[0]).filter(Boolean))];
    const curStage = stageSel.value;
    stageSel.innerHTML = `<option value="">全部业务流</option>` + stages.map((d) => `<option ${d === curStage ? "selected" : ""}>${esc(d)}</option>`).join("");
  }

  $("#sc-grid").innerHTML = filtered.map((s) => {
    const kpis = (s.kpi_links || []).slice(0, 3).map((k) =>
      `<span class="badge kpi">${esc((k.dimension || "").split("-")[0])} ${esc(k.name)} ${esc(k.weight || "")}</span>`
    ).join("");
    const sec = s.security_level === "export_control"
      ? `<span class="badge exp">出口管制</span>` : "";
    // 附件5 §8.3.3：成熟规则徽标
    const mat = (s.maturity === "production") ? `<span class="badge mature">成熟规则·production</span>`
      : (s.maturity === "validated" ? `<span class="badge valid">已验证·validated</span>` : "");
    return `
    <article class="sc-card" data-id="${s.id}">
      <div class="code">${s.code} · v${s.version}</div>
      <h3>${esc(s.title)}</h3>
      <div class="badges">
        <span class="badge">${esc(s.department)}</span>
        <span class="badge model-${s.default_model}">推荐 ${MODEL_LABEL[s.default_model] || s.default_model}</span>
        ${sec}${mat}
        <span class="badge">${esc(s.roles)}</span>
      </div>
      <div class="badges">${kpis}</div>
      <div class="meta">${esc(s.goal)}<br/>⏱ ${esc(s.timing)}${s.workflow_stage ? "<br/>🔗 " + esc(s.workflow_stage) : ""}${s.usage_steps ? "<br/>📋 " + esc(s.usage_steps) : ""}</div>
      <div class="actions">
        <button class="primary btn-use" style="width:auto" data-id="${s.id}">开始使用</button>
        <button class="secondary btn-chat" style="width:auto" data-id="${s.id}" title="以该场景的提示词开启多轮对话">💬 对话</button>
        <button class="ghost btn-detail" data-id="${s.id}">详情</button>
      </div>
    </article>`;
  }).join("") || `<p class="muted">没有匹配的场景</p>`;

  $all(".btn-use").forEach((b) => b.onclick = () => startScenario(+b.dataset.id).catch((e) => toast(e.message)));
  $all(".btn-chat").forEach((b) => b.onclick = () => startScenarioChat(+b.dataset.id).catch((e) => toast(e.message)));
  $all(".btn-detail").forEach((b) => b.onclick = () => showDetail(+b.dataset.id).catch((e) => toast(e.message)));
}
$("#sc-search").oninput = debounce(() => loadScenarios(), 300);
$("#sc-dept").onchange = () => loadScenarios();
$("#sc-model").onchange = () => loadScenarios();
$("#sc-stage").onchange = () => loadScenarios();
$("#sc-maturity").onchange = () => loadScenarios();

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
      <div class="k">输出格式</div><div>${esc(s.output_format || "markdown")}</div>
      <div class="k">版本与作者</div><div>v${esc(s.version)} · ${esc(s.author || "system")} · 已被使用 ${s.use_count ?? 0} 次</div>
      <div class="k">成熟规则</div><div>${esc(s.maturity || "draft")}${s.security_level === "export_control" ? " · 出口管制场景（模型已锁定）" : ""}</div>
    </div>
    <h3>填空变量</h3>
    <pre>${(s.variables || []).map((v) => `${v.key} · ${v.label}${v.required ? "（必填）" : ""}`).join("\n") || "无"}</pre>
    <h3>输入样例</h3>
    <pre>${esc(s.example_input || "（待业务 Owner 补充）")}</pre>
    <h3>期望输出样例</h3>
    <pre>${esc(s.example_output || "（待业务 Owner 补充）")}</pre>
    <h3>提示词模板</h3>
    <pre>${esc(s.prompt_template)}</pre>
    <div style="display:flex;gap:8px">
      <button class="primary" id="modal-use" style="width:auto">用这张卡开始</button>
      <button class="secondary" id="modal-chat" style="width:auto">💬 对话模式（可上传文件/多轮问答）</button>
    </div>
  `;
  $("#modal").classList.remove("hidden");
  $("#modal-use").onclick = () => {
    $("#modal").classList.add("hidden");
    startScenario(id);
  };
  $("#modal-chat").onclick = () => {
    $("#modal").classList.add("hidden");
    startScenarioChat(id).catch((e) => toast(e.message));
  };
}
$("#modal-close").onclick = () => $("#modal").classList.add("hidden");
// 弹层体验：点遮罩 / 按 ESC 关闭
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#modal").classList.contains("hidden")) $("#modal").classList.add("hidden");
});

/* ---------- 工作台 ---------- */
function resetWorkspaceState() {
  CURRENT.sessionId = null;
  CURRENT.finalized = false;
  CURRENT.reviewStatus = "";
  CURRENT.lastAiText = "";
  CURRENT.compareModel = null;
  $("#ws-review-row").classList.add("hidden");
  $("#ws-review-status").classList.add("hidden");
  $("#ws-pane-b").classList.add("hidden");
  $("#ws-output").innerHTML = "";
  $("#ws-output-b").textContent = "";
  $("#ws-pane-a-label").textContent = "";
  $("#ws-pane-b-label").textContent = "";
  $("#ws-extra").value = "";
  $("#ws-privacy").checked = false;
  $("#ws-smart").value = "";
  $("#ws-chips").innerHTML = "";
  $("#ws-params").open = false;
  $$("#ws-form .ws-miss").forEach((x) => x.classList.remove("ws-miss"));
  $("#ws-smart-hint").textContent = "选中场景卡后，描述越具体，识别越准";
  $$(".star").forEach((x) => x.classList.remove("on"));
}

async function startScenario(id) {
  const s = await api(`/scenarios/${id}`);
  CURRENT.scenario = s;
  CURRENT.scenarioId = s.id;
  resetWorkspaceState();
  switchTab("workspace");

  $("#ws-title").textContent = s.title;
  const locked = s.security_level === "export_control" || s.security_level === "sensitive";
  $("#ws-sub").textContent = `${s.code} · ${s.roles} · ${s.timing}` +
    (locked ? " · 🔒 出口管制/敏感场景，模型已锁定指定通道" : "") +
    (s.maturity === "production" ? " · 成熟规则 production：须审核放行后对外" :
     s.maturity === "validated" ? " · 已验证规则：建议审核" : "");
  $("#ws-model").value = s.default_model || "mimo";
  // 附件3 §2.2/§3.4：敏感场景模型选择被锁定
  $("#ws-model").disabled = locked;
  $("#btn-compare").disabled = locked;
  renderForm(s.variables || []);
  // 智能输入提示：列出必填项引导用户"说人话"
  const reqLabels = (s.variables || []).filter((v) => v.required !== false).map((v) => v.label || v.key);
  $("#ws-smart-hint").textContent = reqLabels.length
    ? `描述中建议包含：${reqLabels.join("、")}（AI 自动识别，漏了再补）`
    : "此场景无需参数，直接描述需求即可";
  toast("已加载场景卡，说一段话即可生成，无需逐个填空");
}

/* ---------- 智能填参：说人话 → AI 识别 ---------- */
function renderChips(vars) {
  const box = $("#ws-chips");
  const defs = (CURRENT.scenario && CURRENT.scenario.variables) || [];
  const labelOf = (k) => { const d = defs.find((v) => v.key === k); return d ? (d.label || k) : k; };
  const entries = Object.entries(vars || {}).filter(([, v]) => String(v || "").trim());
  box.innerHTML = entries.map(([k, v]) =>
    `<span class="chip" data-key="${esc(k)}" title="点击展开修改"><b>${esc(labelOf(k))}</b>：${esc(String(v).slice(0, 24))}${String(v).length > 24 ? "…" : ""}</span>`
  ).join("");
  $all(".chip").forEach((c) => {
    c.onclick = () => {
      $("#ws-params").open = true;
      const el = document.querySelector(`#ws-form [data-key="${c.dataset.key}"]`);
      if (el) { el.focus(); el.scrollIntoView({ block: "center", behavior: "smooth" }); }
    };
  });
}

async function smartExtract(silent) {
  const sc = CURRENT.scenario;
  if (!sc || !(sc.variables || []).length) {
    if (!silent) toast(sc ? "此场景无需参数，直接生成即可" : "请先选择场景卡；自由对话直接生成即可");
    return false;
  }
  const text = $("#ws-smart").value.trim();
  if (!text) { if (!silent) toast("先在上方用一段话描述需求"); return false; }
  const btn = $("#btn-smart-fill");
  let ok = false;
  await withWaiting(btn, "识别中", async () => {
    const r = await api(`/scenarios/${sc.id}/extract-vars`, {
      method: "POST", timeout: 60000,
      body: JSON.stringify({ text, model: $("#ws-model").value }),
    });
    let filled = 0;
    Object.entries(r.variables || {}).forEach(([k, v]) => {
      const el = document.querySelector(`#ws-form [data-key="${k}"]`);
      if (el && !el.value.trim()) { el.value = v; filled++; }
    });
    renderChips(r.variables || {});
    ok = filled > 0;
    if (!silent) toast(filled ? `AI 已识别 ${filled} 项参数（点击绿色参数条可核对）` : "未识别出新参数，请补充描述或展开手工填写");
  }).catch((e) => { if (!silent) toast(e.message); });
  return ok;
}
$("#btn-smart-fill").onclick = () => smartExtract(false);

/* 高亮仍未填的必填项并展开面板 */
function highlightMissing(missing) {
  const keys = new Set(missing.map((v) => v.key));
  $$("#ws-form [data-key]").forEach((el) => {
    const lab = el.closest("label");
    if (lab) lab.classList.toggle("ws-miss", keys.has(el.dataset.key));
    el.addEventListener("input", () => lab && lab.classList.remove("ws-miss"), { once: true });
  });
  $("#ws-params").open = true;
}

function renderForm(variables) {
  const box = $("#ws-form");
  const panel = $("#ws-params");
  if (!variables.length) {
    // 无参数场景：隐藏参数面板，只留智能输入框
    box.innerHTML = "";
    if (panel) panel.classList.add("hidden");
    return;
  }
  if (panel) panel.classList.remove("hidden");
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
  resetWorkspaceState();
  $("#ws-title").textContent = "自由对话";
  // 附件3 §2.2：自由对话按任务类型给推荐标签，仍由员工点选确认
  $("#ws-sub").textContent = "无场景卡 · 仍会完整留痕 ｜ 推荐标签：写作/长文→Kimi 3 ｜ 代码/分析→DeepSeek ｜ 快答/邮件→Mimo（下拉自选）";
  $("#ws-smart-hint").textContent = "直接在上方描述您的需求即可生成";
  $("#ws-model").disabled = false;
  $("#btn-compare").disabled = false;
  renderForm([]);
  $("#ws-smart").focus();
};

function readFormVariables() {
  const variables = {};
  $all("#ws-form [data-key]").forEach((el) => { variables[el.dataset.key] = el.value.trim(); });
  return variables;
}

// 附件3 §1.4②：缺关键变量时禁止调用模型（前端先拦截，后端 422 兜底）
function validateRequiredVars() {
  const vars = (CURRENT.scenario && CURRENT.scenario.variables) || [];
  const values = readFormVariables();
  const missing = vars.filter((v) => v.required !== false && !String(values[v.key] || "").trim());
  return missing;
}

async function doGenerate(targetPane) {
  // 智能填参：先说人话，缺必填时自动 AI 识别，识别不了才展开面板补填
  if (targetPane !== "B" && validateRequiredVars().length && $("#ws-smart").value.trim()) {
    await smartExtract(true);
  }
  const variables = readFormVariables();
  const missing = validateRequiredVars();
  if (missing.length) {
    highlightMissing(missing);
    toast("还缺必填参数：" + missing.map((v) => v.label || v.key).join("、") + "（已展开标红，也可在描述中补充后再试）");
    return;
  }
  // 智能输入原文一并带给模型作为完整上下文
  const smartText = $("#ws-smart").value.trim();
  const extraText = [smartText, $("#ws-extra").value.trim()].filter(Boolean).join("\n\n补充要求：");
  const isMature = CURRENT.scenario && ["production", "validated"].includes(CURRENT.scenario.maturity);

  if (isMature && !CURRENT.sessionId) {
    // 成熟规则：自动成稿 + 审核状态（附件5 §8.3.3）
    const r = await api(`/mature-rules/${CURRENT.scenario.code}/generate`, {
      method: "POST",
      timeout: 180000,
      body: JSON.stringify({ variables, model: $("#ws-model").value, extra_instructions: extraText }),
    });
    CURRENT.sessionId = r.session_id;
    CURRENT.reviewStatus = r.review_status || "";
    CURRENT.lastAiText = r.text;
    $("#ws-output").innerText = r.text;
    updateReviewUI();
    toast(r.review_required
      ? "成熟规则已自动成稿：须经理/授权人「审核放行」后方可对外"
      : "已按已验证规则成稿，可直接修改使用");
    loadSessions();
    return;
  }

  if (!CURRENT.sessionId) {
    const data = await api("/sessions", {
      method: "POST",
      body: JSON.stringify({
        scenario_id: CURRENT.scenarioId,
        model: $("#ws-model").value,
        variables,
        title: CURRENT.scenario ? CURRENT.scenario.title : "自由对话",
        privacy: ($("#ws-privacy") && $("#ws-privacy").checked) ? "metadata_only" : "standard",
      }),
    });
    CURRENT.sessionId = data.id;
  }

  const r = await api(`/sessions/${CURRENT.sessionId}/generate`, {
    method: "POST",
    timeout: 180000,
    body: JSON.stringify({
      model: targetPane === "B" ? CURRENT.compareModel : $("#ws-model").value,
      extra_instructions: extraText,
      variables,
    }),
  });
  if (targetPane === "B") {
    $("#ws-pane-b").classList.remove("hidden");
    $("#ws-output-b").innerText = r.text;
    $("#ws-pane-b-label").textContent = `对比稿 · ${r.provider}:${r.model}`;
    toast("对比稿已生成（右栏），可并排比对");
    return;
  }
  $("#ws-output").innerText = r.text;
  CURRENT.lastAiText = r.text;
  // 附件3 §2.2：降级需提示「已切换至××，结果可能有差异」
  $("#ws-sub").textContent = `模型：${r.provider}:${r.model} · tokens ${r.tokens_in}/${r.tokens_out}` +
    (r.degraded ? ` · 已切换至 ${r.provider}:${r.model}，结果可能有差异` : "") +
    (r.model_locked ? " · 🔒模型已锁定" : "");
  if ((r.sensitive_hits || []).length) {
    toast("⚠️ 检测到敏感信息（" + r.sensitive_hits.join("、") + "），已标记；请勿输入受控技术参数");
  } else if (r.degraded) toast(`主模型不可用，已切换至 ${r.provider}:${r.model}，结果可能有差异`);
  else if (r.quota_exceeded) toast("本月额度已超限（仅提醒，不影响使用）");
  else toast("初稿已生成，可直接修改");
  loadSessions();
}

$("#btn-generate").onclick = () =>
  withWaiting($("#btn-generate"), "生成中", () => doGenerate("A")).catch((e) => toast(e.message));

// 附件3 §2.2：「换一个模型」按钮，一键 AB 对比同输入两份输出
$("#btn-compare").onclick = async () => {
  if (!CURRENT.sessionId || !CURRENT.lastAiText) { toast("请先生成初稿，再换模型对比"); return; }
  const order = ["mimo", "deepseek", "kimi"];
  const cur = $("#ws-model").value;
  CURRENT.compareModel = order.find((m) => m !== cur) || "deepseek";
  const btn = $("#btn-compare");
  try {
    await withWaiting(btn, "对比生成中", () => doGenerate("B"));
    $("#ws-pane-a-label").textContent = `主稿 · ${$("#ws-model").value}`;
  } catch (e) { toast(e.message); }
};

// 工作台快捷键：Ctrl/Cmd + Enter 直接生成
$("#tab-workspace").addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    $("#btn-generate").click();
  }
});

// 成熟规则审核 UI 状态
function updateReviewUI() {
  const badge = $("#ws-review-status");
  if (CURRENT.reviewStatus === "awaiting_review") {
    badge.textContent = "【审核状态】awaiting_review · 待经理/授权人审核放行";
    badge.classList.remove("hidden");
    $("#ws-review-row").classList.remove("hidden");
  } else if (CURRENT.reviewStatus) {
    badge.textContent = "【审核状态】" + CURRENT.reviewStatus;
    badge.classList.remove("hidden");
    $("#ws-review-row").classList.toggle("hidden", CURRENT.reviewStatus === "approved");
  } else {
    badge.classList.add("hidden");
    $("#ws-review-row").classList.add("hidden");
  }
}

async function submitReview(action) {
  if (!CURRENT.sessionId) { toast("无可审核的会话"); return; }
  const note = $("#ws-review-note").value.trim();
  const final_text = $("#ws-output").innerText.trim();
  try {
    const r = await api(`/mature-rules/review/${CURRENT.sessionId}`, {
      method: "POST",
      body: JSON.stringify({ action, note, final_text: action === "approve" ? final_text : "" }),
    });
    CURRENT.reviewStatus = r.review_status || "";
    CURRENT.finalized = action === "approve";
    updateReviewUI();
    toast(action === "approve" ? "已审核放行，可对外/归档" :
          action === "revise" ? "已退回修改" : "已否决");
  } catch (e) { toast(e.message); }
}
$("#btn-approve").onclick = () => submitReview("approve");
$("#btn-revise").onclick = () => submitReview("revise");
$("#btn-reject").onclick = () => submitReview("reject");

$("#btn-finalize").onclick = async () => {
  try {
    if (!CURRENT.sessionId) { toast("请先生成初稿"); return; }
    if (CURRENT.reviewStatus === "awaiting_review") { toast("成熟规则稿件须先「审核放行」再定稿"); return; }
    const content = $("#ws-output").innerText.trim();
    if (!content) { toast("定稿内容为空"); return; }
    const r = await api(`/sessions/${CURRENT.sessionId}/finalize`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    CURRENT.finalized = true;
    // 附件5 §1.3 步⑤：产出同步存回任务资料文件夹，文件名建议 场景编号_产出名_日期
    const code = CURRENT.scenario ? CURRENT.scenario.code : "FREE";
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, "");
    toast(`已保存定稿 · 修改率 ${(r.edit_ratio * 100).toFixed(0)}%` +
      ` ｜ 请存回资料文件夹：${code}_产出_${today}`);
  } catch (e) { toast(e.message); }
};

$("#btn-archive").onclick = async () => {
  try {
    const content = $("#ws-output").innerText.trim();
    if (!content) { toast("没有可归档的内容"); return; }
    if (CURRENT.reviewStatus === "awaiting_review") { toast("成熟规则稿件须先「审核放行」再归档"); return; }
    if (CURRENT.sessionId && !CURRENT.finalized) { toast("请先「保存人工定稿」，再归档知产库"); return; }
    const title = $("#ws-title").textContent || "未命名产出";
    const visibility = $("#ws-visibility").value || "dept";
    const dist = prompt("分发记录（可选）：发送到哪个群/目录？逗号分隔，留空跳过", "");
    const distributed_to = dist ? dist.split(/[,，]/).map((x) => x.trim()).filter(Boolean) : [];
    const V_LABEL = { private: "仅自己（秘密级）", dept: "本部门", company: "公司精选" };
    await api("/assets", {
      method: "POST",
      body: JSON.stringify({
        session_id: CURRENT.sessionId,
        title,
        content,
        visibility,
        tags: CURRENT.scenario ? [CURRENT.scenario.code] : [],
        distributed_to,
      }),
    });
    toast(`已归档到知产库（${V_LABEL[visibility] || visibility}）`);
    loadAssets();
  } catch (e) { toast(e.message); }
};

// 10. copy + export Word (附件3 §1.2「导出Word/复制」)
$("#btn-copy").onclick = async () => {
  const text = $("#ws-output").innerText.trim();
  if (!text) { toast("没有可复制的内容"); return; }
  try { await navigator.clipboard.writeText(text); toast("已复制"); }
  catch { toast("请手动全选复制"); }
};

$("#btn-export").onclick = () => {
  const text = $("#ws-output").innerText.trim();
  if (!text) { toast("没有可导出的内容"); return; }
  const title = $("#ws-title").textContent || "产出";
  // 简易 Word 导出（.doc：HTML 包装，附件3 §4.3 模板化导出的轻量实现）
  const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>${esc(title)}</title></head><body><h1>${esc(title)}</h1>${text.split("\n").map((l) => `<p>${esc(l) || "<br/>"}</p>`).join("")}</body></html>`;
  const blob = new Blob(["\ufeff" + html], { type: "application/msword" });
  const a = document.createElement("a");
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const code = CURRENT.scenario ? CURRENT.scenario.code : "FREE";
  a.href = URL.createObjectURL(blob);
  a.download = `${code}_${title}_${today}.doc`;
  a.click();
  URL.revokeObjectURL(a.href);
  toast("已导出 Word（.doc），请同步存回任务资料文件夹");
};

$$(".star").forEach((b) => {
  b.onclick = async () => {
    if (!CURRENT.sessionId) { toast("请先完成一次生成"); return; }
    try {
      const rating = +b.dataset.r;
      await api(`/sessions/${CURRENT.sessionId}/rating`, {
        method: "POST",
        body: JSON.stringify({ rating }),
      });
      // 1..r 全亮，直观反映所选分值
      $$(".star").forEach((x) => x.classList.toggle("on", +x.dataset.r <= rating));
      toast("感谢评价，将用于优化场景卡");
    } catch (e) { toast(e.message); }
  };
});



/* ---------- 任务项目：资料文件夹 → Mimo项目 → 工作流 ---------- */
// 场景卡列表缓存 60s：任务项目卡片渲染不再每次全量重拉
let _scCache = { at: 0, list: [] };
async function cachedScenarios() {
  if (Date.now() - _scCache.at > 60000 || !_scCache.list.length) {
    _scCache = { at: Date.now(), list: await api("/scenarios") };
  }
  return _scCache.list;
}

async function loadTaskProjects() {
  const box = $("#tp-list");
  let list;
  try {
    list = await api("/task-projects");
  } catch (e) {
    box.innerHTML = `<div class="muted">任务项目加载失败：${esc(e.message)} <button class="ghost" style="width:auto" onclick="loadTaskProjects()">重试</button></div>`;
    return;
  }
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
        <select class="tp-sc" data-code="${esc(p.code)}" style="width:auto" title="选择场景卡（按岗位节点）"></select>
        <button class="primary btn-tp-start" data-code="${esc(p.code)}" style="width:auto">选择场景卡并进入工作流</button>
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
  // 附件5 §1.2 步2：在任务项目下选择场景卡（按岗位节点）
  const allSc = await cachedScenarios();
  $all(".tp-sc").forEach((sel) => {
    sel.innerHTML = `<option value="">— 选择场景卡 —</option>` + allSc.map((s) =>
      `<option value="${s.id}">${esc(s.code)} ${esc(s.title)}</option>`).join("");
  });
  $all(".btn-tp-start").forEach((b) => {
    b.onclick = async () => {
      const code = b.dataset.code;
      try {
        const sel = document.querySelector(`.tp-sc[data-code="${code}"]`);
        const scId = sel && sel.value ? +sel.value : 0;
        const sc = allSc.find((x) => x.id === scId);
        if (!sc) { toast("请先在下拉框中选择场景卡"); return; }
        const s = await api(`/task-projects/${code}/sessions`, {
          method: "POST",
          body: JSON.stringify({ scenario_id: sc.id, title: "任务会话", model: sc.default_model }),
        });
        // 先重置再赋值，避免状态残留
        resetWorkspaceState();
        CURRENT.sessionId = s.id;
        CURRENT.scenarioId = sc.id;
        CURRENT.scenario = sc;
        const locked = sc.security_level === "export_control" || sc.security_level === "sensitive";
        $("#ws-title").textContent = s.title;
        $("#ws-sub").textContent = `任务项目 ${code} · 已进入工作流` + (locked ? " · 🔒 敏感场景模型已锁定" : "");
        $("#ws-model").value = sc.default_model || "mimo";
        $("#ws-model").disabled = locked;
        $("#btn-compare").disabled = locked;
        renderForm(sc.variables || []);
        switchTab("workspace");
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
  // 附件5 §1.2 步0：文件夹命名 日期-任务-项目名
  const folderName = (folder.replace(/\\/g, "/").replace(/\/$/, "").split("/").pop()) || "";
  if (folder && !/^\d{8}-.+-.+/.test(folderName)) {
    if (!confirm("文件夹名不符合「日期-任务-项目名」规范（如 20260927-项目周报-俄罗斯泵站）。仍要创建吗？")) return;
  }
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

$("#btn-bf-gen").onclick = () => withWaiting($("#btn-bf-gen"), "生成中", async () => {
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
  // LLM 成稿通常 20–60s：放宽超时并实时显示等待秒数
  const data = await api(path, { method: "POST", timeout: 180000, body: JSON.stringify(body) });
  BF_LAST = data;
  $("#bf-output").innerText = data.content || "";
  // 企微短版回显（附件5 §8.2：短版是交付物，复制前先看）
  $("#bf-card").innerText = data.wecom_card || "（未识别到短版段落，可复制全文）";
  const nTasks = (data.jdy_tasks || []).length;
  toast("已生成" + (nTasks ? `，解析出 ${nTasks} 条任务将逐条入简道云` : "") + "，可编辑后推送 / 复制企微短版");
  loadBriefingHistory();
}).catch((e) => toast(e.message));

$("#btn-bf-copy").onclick = async () => {
  const text = (BF_LAST && (BF_LAST.wecom_card || BF_LAST.content)) || $("#bf-output").innerText;
  try {
    await navigator.clipboard.writeText(text);
    toast("企微短版已复制，可粘贴到群/早宣晚总");
  } catch {
    toast("请手动全选复制");
  }
};

$("#btn-bf-push").onclick = () => withWaiting($("#btn-bf-push"), "推送中", async () => {
  if (!BF_LAST) { toast("请先生成文稿"); return; }
  const nTasks = (BF_LAST.jdy_tasks || []).length;
  // 附件5 §8.2「确认推送」+ 附件4 门禁7：推送前显式确认
  const okPush = confirm(
    `确认推送简道云？\n\n文稿：${BF_LAST.title || ""}` +
    (nTasks ? `\n任务表：${nTasks} 条任务将逐条写入任务管理` : "") +
    (BF_LAST.knowledge_payload ? "\n同时将双写知识库" : "") +
    "\n\n请确认文稿内容已人工核对。"
  );
  if (!okPush) return;
  const content = $("#bf-output").innerText.trim();
  let r;
  if (BF_LAST.briefing_id) {
    const edited = content && content !== (BF_LAST.content || "");
    if (edited) {
      // 文稿被人工修改过：汇总记录推送编辑版，任务表仍按落库 payload 逐条推送
      const payload = { ...(BF_LAST.jdy_payload || {}) };
      if (payload["任务描述"] !== undefined) payload["任务描述"] = content;
      r = await api("/briefings/push", { method: "POST", timeout: 120000, body: JSON.stringify({ payload }) });
      if (nTasks) {
        r = await api("/briefings/push", {
          method: "POST",
          timeout: 120000,
          body: JSON.stringify({ briefing_id: BF_LAST.briefing_id, include_tasks: true, include_payload: false }),
        });
      }
    } else {
      r = await api("/briefings/push", {
        method: "POST",
        timeout: 120000,
        body: JSON.stringify({ briefing_id: BF_LAST.briefing_id, include_tasks: true }),
      });
    }
  } else {
    const payload = { ...(BF_LAST.jdy_payload || {}) };
    if (payload["任务描述"] !== undefined) payload["任务描述"] = content;
    r = await api("/briefings/push", {
      method: "POST",
      timeout: 120000,
      body: JSON.stringify({ payload, kind: BF_LAST.knowledge_payload ? "knowledge" : "task" }),
    });
  }
  // 结项时再推知识库（双写，附件5 §8.2）
  if (BF_LAST.knowledge_payload) {
    await api("/briefings/push", {
      method: "POST",
      timeout: 120000,
      body: JSON.stringify({ payload: BF_LAST.knowledge_payload, kind: "knowledge" }),
    });
  }
  toast(`已推送简道云（${r.mode}）共 ${r.count || 1} 条`);
  loadBriefingHistory();
}).catch((e) => toast(e.message));

async function loadBriefingHistory() {
  try {
    const list = await api("/briefings/history?limit=10");
    $("#bf-history").innerHTML = list.map((b) => `
      <div class="asset-item">
        <h4>${b.pushed ? "✅" : "📝"} ${esc(b.title)}
          <span class="badge">${esc(b.kind)}</span>
          <span class="badge">${b.pushed ? "已推送 " + esc(b.push_mode || "") : "未推送"}</span>
        </h4>
        <div class="muted">${new Date(b.created_at).toLocaleString()}</div>
      </div>`).join("") || `<p class="muted">暂无记录</p>`;
  } catch { /* 忽略历史加载失败 */ }
}

/* 把某个会话完整载入工作台（场景卡/表单/变量/审核状态/定稿状态/评分）。
   工作台列表与「智能对话 → 送到工作台」共用此入口。 */
async function openSessionInWorkspace(sessionId) {
  const s = await api(`/sessions/${sessionId}`);
  resetWorkspaceState();
  CURRENT.sessionId = s.id;
  CURRENT.scenarioId = s.scenario_id;
  CURRENT.reviewStatus = s.review_status || "";
  let sc = null;
  if (s.scenario_id) {
    try { sc = await api(`/scenarios/${s.scenario_id}`); } catch { sc = null; }
  }
  CURRENT.scenario = sc;
  const locked = !!(sc && (sc.security_level === "export_control" || sc.security_level === "sensitive"));
  renderForm(sc ? (sc.variables || []) : []);
  // 回填创建会话时保存的填空变量
  $all("#ws-form [data-key]").forEach((inp) => {
    const v = (s.variables || {})[inp.dataset.key];
    if (v) inp.value = v;
  });
  const lastFinal = [...s.messages].reverse().find((m) => m.is_final);
  const lastAi = [...s.messages].reverse().find((m) => m.role === "assistant" && !m.is_final);
  CURRENT.finalized = !!lastFinal;
  CURRENT.lastAiText = lastAi?.content || "";
  $("#ws-output").innerText = lastFinal?.content || lastAi?.content || "";
  $("#ws-title").textContent = s.title;
  $("#ws-sub").textContent = sc
    ? `${sc.code} · ${sc.roles} · ${sc.timing}` + (locked ? " · 🔒 敏感场景模型已锁定" : "")
    : (s.channel === "chat" ? "来自智能对话（可在上方继续补充要求后再生成）" : "自由对话（历史会话）");
  $("#ws-model").value = s.model || "mimo";
  $("#ws-model").disabled = locked;
  $("#btn-compare").disabled = locked;
  if (s.rating) $$(".star").forEach((x) => x.classList.toggle("on", +x.dataset.r <= s.rating));
  updateReviewUI();
  loadSessions();
}

async function loadSessions() {
  let list;
  try {
    list = await api("/sessions");
  } catch (e) {
    $("#session-list").innerHTML = `<div class="muted">会话加载失败：${esc(e.message)}</div>`;
    return;
  }
  // 智能对话频道的会话在「💬 智能对话」页查看，工作台列表不重复展示
  list = list.filter((s) => (s.channel || "workbench") !== "chat");
  $("#session-list").innerHTML = list.slice(0, 20).map((s) => `
    <div class="session-item ${s.id === CURRENT.sessionId ? "active" : ""}" data-id="${s.id}">
      ${esc(s.title)}<br/><span class="muted">${new Date(s.updated_at).toLocaleString()}</span>
    </div>
  `).join("") || `<div class="muted">暂无会话</div>`;
  $all(".session-item").forEach((el) => {
    el.onclick = () => openSessionInWorkspace(+el.dataset.id).catch((e) => toast(e.message));
  });
}

/* ---------- 知产库 ---------- */
async function loadAssets() {
  const scope = $("#as-scope")?.value || "all";
  const q = $("#as-search")?.value.trim() || "";
  const params = new URLSearchParams({ scope });
  if (q) params.set("q", q);
  let list;
  try {
    $("#asset-list").innerHTML = `<div class="skeleton"></div>`;
    list = await api(`/assets?${params}`);
  } catch (e) {
    $("#asset-list").innerHTML = `<p class="muted">知产库加载失败：${esc(e.message)}</p>`;
    return;
  }
  $("#asset-list").innerHTML = list.map((a) => `
    <div class="asset-item">
      <h4>${a.featured ? "⭐ " : ""}${esc(a.title)}
        <span class="badge">${esc(a.visibility)}</span>
        <span class="badge">${esc(a.department)}</span>
      </h4>
      <div class="muted">${new Date(a.created_at).toLocaleString()}</div>
      <div class="content">${esc(a.content)}</div>
      <div class="td-actions">
        ${a.session_id ? `<button class="ghost btn-diff" data-id="${a.session_id}" style="width:auto">看改动痕迹</button>` : ""}
        ${USER && USER.role === "admin" ? `<button class="secondary btn-feature" data-id="${a.id}" style="width:auto">${a.featured ? "取消精选" : "收进精选范例"}</button>` : ""}
      </div>
    </div>
  `).join("") || `<p class="muted">暂无资产。在工作台点击「归档到知产库」即可沉淀。</p>`;

  // 附件3 §3.2「晋升」：管理员一键收进精选范例
  $all(".btn-feature").forEach((b) => {
    b.onclick = async () => {
      try {
        const r = await api(`/assets/${b.dataset.id}/feature`, { method: "POST" });
        toast(r.featured ? "已收进公司精选" : "已取消精选");
        loadAssets();
      } catch (e) { toast(e.message); }
    };
  });
  // 附件3 §1.1/§3.2：看改动痕迹（AI初稿 vs 定稿 diff）
  $all(".btn-diff").forEach((b) => {
    b.onclick = async () => {
      try {
        const rows = await api(`/sessions/${b.dataset.id}/diffs`);
        $("#modal-body").innerHTML = rows.length ? rows.map((d) => `
          <h3>修改痕迹 · ${new Date(d.created_at).toLocaleString()}</h3>
          <p class="muted">修改率 ${(d.edit_ratio * 100).toFixed(0)}% ｜ ${esc(d.diff_summary)}</p>
          <h4>AI 初稿</h4><pre>${esc(d.ai_text)}</pre>
          <h4>人工定稿</h4><pre>${esc(d.final_text)}</pre>
        `).join("") : `<p class="muted">该资产无修改痕迹记录</p>`;
        $("#modal").classList.remove("hidden");
      } catch (e) { toast(e.message); }
    };
  });
}

// 附件3 §3.3：场景卡市场（与知产库并列）
async function loadMarket() {
  try {
    const rows = await api("/scenarios-market");
    $("#sc-market").innerHTML = rows.slice(0, 20).map((s) => `
      <div class="asset-item">
        <h4>${esc(s.code)} ${esc(s.title)}
          <span class="badge">${esc(s.department)}</span>
          ${s.maturity === "production" ? '<span class="badge mature">production</span>' : s.maturity === "validated" ? '<span class="badge valid">validated</span>' : ""}
        </h4>
        <div class="muted">调用 ${s.use_count} 次 ｜ 平均评分 ${s.avg_rating ?? "—"}（${s.rating_count} 次评价）｜ v${esc(s.version)} · ${esc(s.author)} · 最近改进 ${s.last_change ? new Date(s.last_change).toLocaleDateString() : "—"}</div>
      </div>`).join("") || `<p class="muted">暂无数据</p>`;
  } catch (e) { /* 忽略 */ }
}
$("#as-scope").onchange = () => loadAssets();
$("#as-search").oninput = debounce(() => loadAssets(), 300);
$("#btn-reload-assets").onclick = () => { loadAssets(); loadMarket(); };

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

    // 场景性价比（附件3 §2.3）
    const costs = s.scenario_costs || [];
    const cMax = Math.max(...costs.map((x) => x.tokens), 1);
    $("#admin-costs").innerHTML = costs.map((x) => `
      <div class="bar-row">
        <div class="name">${esc(x.title)}</div>
        <div class="bar" style="width:${(x.tokens / cMax) * 160}px"></div>
        <div>${x.sessions}次/${x.tokens}tok</div>
      </div>
    `).join("") || `<div class="muted">暂无数据</div>`;

    // 附件5 §8.5：早宣/晚总推送量（部门经理视图）
    try {
      const bs = await api("/briefings/stats");
      $("#admin-briefing").innerHTML = Object.entries(bs.by_department || {}).map(([dept, d]) => `
        <div class="bar-row"><div class="name">${esc(dept)}</div>
        <div class="muted">${Object.entries(d).map(([k, v]) => `${esc(k)}:${v}`).join(" ｜ ")}</div></div>
      `).join("") || `<div class="muted">暂无推送记录</div>`;
    } catch { $("#admin-briefing").innerHTML = `<div class="muted">无权限或暂无数据</div>`; }

    loadAdminUsers();
  } catch (e) {
    $("#admin-stats").innerHTML = `<div class="muted">${esc(e.message)}（管理看板需管理员账号）</div>`;
  }
}

/* ---------- 用户管理（RBAC · 仅 admin） ---------- */
let UM_LIST = [];

async function loadAdminUsers() {
  try {
    UM_LIST = await api("/admin/users");
  } catch (e) {
    $("#admin-users").innerHTML = `<div class="muted">用户列表加载失败：${esc(e.message)}</div>`;
    return;
  }
  renderAdminUsers();
}

function renderAdminUsers() {
  const q = ($("#um-search").value || "").trim().toLowerCase();
  const list = UM_LIST.filter((u) => !q ||
    [u.name, u.department, u.position, u.wecom_userid].some((x) => (x || "").toLowerCase().includes(q)));
  $("#admin-users").innerHTML = `
    <div class="um-row um-head">
      <span>姓名</span><span>部门 / 岗位</span><span>登录账号</span><span>角色</span><span>状态</span><span></span>
    </div>` + list.map((u) => `
    <div class="um-row ${u.status === "active" ? "" : "um-disabled"}">
      <span>${esc(u.name)}${u.id === USER.id ? "（我）" : ""}</span>
      <span class="muted">${esc(u.department || "—")} · ${esc(u.position || "—")}</span>
      <span class="muted" title="${esc(u.wecom_userid)}">${u.wecom_userid.startsWith("dev_") ? "开发登录" : "企微已绑定"}</span>
      <span>
        <select class="um-role" data-id="${u.id}" ${u.id === USER.id ? "disabled" : ""}>
          ${["staff", "manager", "compliance", "admin"].map((r) =>
            `<option value="${r}" ${u.role === r ? "selected" : ""}>${ROLE_LABEL[r]}</option>`).join("")}
        </select>
      </span>
      <span>${u.status === "active" ? '<span class="badge" style="background:var(--ok-soft);color:var(--ok)">在用</span>' : '<span class="badge exp">已停用</span>'}</span>
      <span>
        ${u.id === USER.id ? "" : `<button class="ghost um-toggle" style="width:auto;padding:5px 12px;font-size:12px" data-id="${u.id}" data-status="${u.status}">${u.status === "active" ? "停用" : "启用"}</button>`}
      </span>
    </div>`).join("") || `<div class="muted">无匹配用户</div>`;
  $all(".um-role").forEach((sel) => {
    sel.onchange = () => patchUserRole(+sel.dataset.id, { role: sel.value }, sel);
  });
  $all(".um-toggle").forEach((b) => {
    b.onclick = () => {
      const next = b.dataset.status === "active" ? "disabled" : "active";
      if (next === "disabled" && !confirm("停用后该用户立即无法访问系统。确认停用？")) return;
      patchUserRole(+b.dataset.id, { status: next }, b);
    };
  });
}

async function patchUserRole(id, patch, el) {
  try {
    await api(`/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
    toast("已更新");
    loadAdminUsers();
  } catch (e) {
    toast(e.message);
    loadAdminUsers();  // 失败回滚 UI 到服务端状态
  }
}
$("#btn-um-reload").onclick = () => loadAdminUsers();
$("#um-search").oninput = debounce(renderAdminUsers, 200);

/* ---------- 部门经理：本部门推送统计（简道云页签内） ---------- */
async function initDeptStatsEntry() {
  const canSee = USER && (USER.role === "manager" || USER.role === "admin");
  $("#btn-bf-dept-stats").classList.toggle("hidden", !canSee);
}
$("#btn-bf-dept-stats").onclick = async () => {
  const box = $("#bf-dept-stats");
  if (!box.classList.contains("hidden")) { box.classList.add("hidden"); return; }
  try {
    const bs = await api("/briefings/stats");
    const rows = Object.entries(bs.by_department || {}).map(([dept, d]) => `
      <div class="bar-row"><div class="name">${esc(dept)}</div>
      <div class="muted">${Object.entries(d).map(([k, v]) => `${esc(k)}:${v}`).join(" ｜ ")}</div></div>
    `).join("");
    const pushedN = Object.keys(bs.pushed_today_users || {}).length;
    box.innerHTML = `<div class="proj-banner" style="margin:0">
      <strong>${esc(bs.department || "全部部门")} · ${esc(bs.today)}</strong> 今日已推送 ${pushedN} 人<br/>${rows || "暂无推送记录"}
    </div>`;
    box.classList.remove("hidden");
  } catch (e) { toast(e.message); }
};

/* ---------- 🗂 简道云数据镜像（单向拉取：简道云 → 本系统，本地浏览） ---------- */
const JDY_KIND_LABEL = { task: "任务管理", knowledge: "知识库" };

async function loadJdyOverview() {
  try {
    const d = await api("/jdy/overview");
    $("#jdy-overview").innerHTML = d.forms.map((f) => `
      <div class="stat">
        <div class="num">${f.records}</div>
        <div class="lbl">${esc(f.label)}${f.entry_configured ? "" : "（未配置）"}</div>
        <div class="muted" style="font-size:11px">${f.last_sync ? "最近同步 " + new Date(f.last_sync).toLocaleString() : (f.last_message || "尚未同步")}</div>
      </div>`).join("");
    $("#jdy-sync-hint").textContent = d.mock ? " · MOCK 模式（未配置凭证）" : "";
    const canSync = USER && (USER.role === "admin" || USER.role === "manager");
    $("#btn-jdy-sync").classList.toggle("hidden", !canSync);
    $("#jdy-logs-box").classList.toggle("hidden", !canSync);
  } catch (e) {
    $("#jdy-overview").innerHTML = `<div class="muted">镜像概览加载失败：${esc(e.message)}</div>`;
  }
}

async function loadJdyList() {
  const kind = $("#jdy-kind").value;
  const q = $("#jdy-search").value.trim();
  const params = new URLSearchParams({ limit: "100" });
  if (q) params.set("q", q);
  try {
    const d = await api(`/jdy/data/${kind}?${params}`);
    if (!d.items.length) {
      $("#jdy-list").innerHTML = `<p class="muted">${d.mock ? "MOCK 模式暂无数据；配置凭证后由 poller 每小时自动拉取" : "暂无数据"}</p>`;
      return;
    }
    $("#jdy-list").innerHTML = d.items.map((r) => `
      <div class="asset-item jdy-item" data-id="${esc(r.data_id)}">
        <div class="asset-head">
          <b>${esc(r.title)}</b>
          ${r.status ? `<span class="badge">${esc(r.status)}</span>` : ""}
        </div>
        <div class="muted" style="font-size:12px">
          ${r.owner ? "👤 " + esc(r.owner) + " · " : ""}${r.dept ? esc(r.dept) + " · " : ""}
          ${r.due_time ? "⏰ 截止 " + esc(r.due_time.slice(0, 10)) + " · " : ""}
          ${r.submit_time ? "提交 " + esc(r.submit_time.slice(0, 10)) + " · " : ""}
          同步于 ${new Date(r.synced_at).toLocaleString()}
        </div>
      </div>`).join("");
    $all("#jdy-list .jdy-item").forEach((el) => {
      el.onclick = () => showJdyDetail(kind, el.dataset.id).catch((e) => toast(e.message));
    });
  } catch (e) {
    $("#jdy-list").innerHTML = `<p class="muted">镜像数据加载失败：${esc(e.message)}</p>`;
  }
}

async function showJdyDetail(kind, dataId) {
  const d = await api(`/jdy/data/${kind}/${dataId}`);
  const rows = Object.entries(d.fields || {})
    .filter(([, v]) => String(v || "").trim())
    .map(([k, v]) => `<div class="k">${esc(k)}</div><div style="white-space:pre-wrap">${esc(v)}</div>`)
    .join("");
  $("#modal-body").innerHTML = `
    <h2>${esc(d.title)}</h2>
    <div class="badges"><span class="badge">${esc(JDY_KIND_LABEL[d.kind] || d.kind)}</span>
    <span class="badge">同步于 ${new Date(d.synced_at).toLocaleString()}</span></div>
    <div class="kv" style="margin-top:10px">${rows || '<div class="muted">（无字段内容）</div>'}</div>`;
  $("#modal").classList.remove("hidden");
}

async function loadJdyLogs() {
  try {
    const logs = await api("/jdy/sync/logs");
    $("#jdy-logs").innerHTML = logs.map((l) => `
      <div class="cand-item">
        <span class="badge ${l.status === "success" ? "" : "exp"}">${esc(l.status)}</span>
        <span>${esc(l.message)}</span>
        <span class="muted" style="margin-left:auto">${l.duration_ms}ms · ${new Date(l.created_at).toLocaleString()}</span>
      </div>`).join("") || `<div class="muted">暂无同步日志</div>`;
  } catch (e) { $("#jdy-logs").innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
}
$("#jdy-logs-box").addEventListener("toggle", () => {
  if ($("#jdy-logs-box").open) loadJdyLogs();
});

$("#jdy-kind").onchange = () => loadJdyList();
$("#jdy-search").oninput = debounce(loadJdyList, 300);
$("#btn-jdy-reload").onclick = () => { loadJdyOverview(); loadJdyList(); };
$("#btn-jdy-sync").onclick = () => withWaiting($("#btn-jdy-sync"), "同步中", async () => {
  const r = await api("/jdy/sync", { method: "POST", timeout: 120000 });
  const summary = Object.values(r.entries || {}).map((e) => e.message).filter(Boolean).join("；");
  toast(r.ok ? `同步完成：${summary}` : `部分失败：${summary}`);
  loadJdyOverview();
  loadJdyList();
  if ($("#jdy-logs-box").open) loadJdyLogs();
}).catch((e) => toast(e.message));

/* ---------- 💬 智能对话（类 DeepSeek Harness：上传文件 + 多轮对话 + 换模型 + 历史记录） ---------- */
const CHAT = {
  sessionId: null,
  scenario: null,      // 会话绑定场景摘要：{id, code, title, security_level, default_model}
  modelLocked: false,  // 敏感/出口管制场景锁定模型
  pendingAtts: [],     // 已上传、待随下一条消息发送的附件
  list: [],            // 历史列表缓存（供标题搜索过滤）
  sending: false,
};

function chatMsgHtml(m) {
  const isUser = m.role === "user";
  const time = m.created_at ? new Date(m.created_at).toLocaleString() : "";
  const meta = isUser ? time : `${esc(m.model || "")} · ${time}`;
  return `<div class="chat-msg ${isUser ? "user" : "ai"}">
    <div class="chat-bubble">${esc(m.content)}</div>
    <div class="chat-meta">${meta}${m.is_final ? " · ✅ 已定稿" : ""}</div>
  </div>`;
}

function renderChatThread(messages) {
  const t = $("#chat-thread");
  t.innerHTML = messages.length
    ? messages.map(chatMsgHtml).join("")
    : `<div class="chat-empty muted">还没有消息，在下方输入第一段话吧；也可以先 📎 上传文件再提问。</div>`;
  t.scrollTop = t.scrollHeight;
}

function renderChatChips() {
  const box = $("#chat-chips");
  box.innerHTML = CHAT.pendingAtts.map((a, i) => {
    const ok = a.extract_status === "ok";
    const tip = ok ? `已解析 ${a.text_len} 字，将随下一条消息注入上下文` : (a.note || "未能解析出文本");
    return `<span class="chat-chip ${ok ? "" : "bad"}" title="${esc(tip)}">
      ${ok ? "✓" : "⚠"} ${esc(a.filename)} <b data-i="${i}" title="移除并删除该附件">×</b>
    </span>`;
  }).join("");
  $all("#chat-chips .chat-chip b").forEach((x) => {
    x.onclick = async () => {
      const a = CHAT.pendingAtts[+x.dataset.i];
      // 未发送的附件允许删除（已随消息发送的附件属留痕，服务端会拒绝删除）
      try { await api(`/chat/uploads/${a.id}`, { method: "DELETE" }); } catch (e) { toast(e.message); }
      CHAT.pendingAtts.splice(+x.dataset.i, 1);
      renderChatChips();
    };
  });
}

/* 上传走原生 fetch（multipart），不能复用 api() 的 JSON Content-Type */
async function uploadChatFiles(fileList) {
  if (!fileList || !fileList.length) return;
  const fd = new FormData();
  [...fileList].forEach((f) => fd.append("files", f));
  const btn = $("#btn-chat-attach");
  await withWaiting(btn, "上传解析中", async () => {
    const res = await fetch(API + "/chat/uploads", {
      method: "POST",
      headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
      body: fd,
    });
    const data = await res.json().catch(() => null);
    if (res.status === 401) { logout(false); throw new Error("登录失效，请重新登录"); }
    if (!res.ok) throw new Error(data?.message || data?.detail || `上传失败（HTTP ${res.status}）`);
    CHAT.pendingAtts.push(...data);
    renderChatChips();
    const bad = data.filter((a) => a.extract_status !== "ok");
    toast(bad.length
      ? `已上传 ${data.length} 个；其中 ${bad.length} 个未解析出文本（可发送，但 AI 看不到其内容）`
      : `已上传并解析 ${data.length} 个文件`);
  }).catch((e) => toast(e.message));
  $("#chat-file").value = "";
}

async function loadChatSessions() {
  let list;
  try {
    list = await api("/chat/sessions");
  } catch (e) {
    $("#chat-session-list").innerHTML = `<div class="muted">历史加载失败：${esc(e.message)}</div>`;
    return;
  }
  CHAT.list = list;
  renderChatSessionList();
}

function renderChatSessionList() {
  const q = ($("#chat-search").value || "").trim().toLowerCase();
  const list = CHAT.list.filter((s) => !q || (s.title || "").toLowerCase().includes(q));
  $("#chat-session-list").innerHTML = list.map((s) => `
    <div class="session-item chat-item ${s.id === CHAT.sessionId ? "active" : ""} ${s.status === "closed" ? "closed" : ""}" data-id="${s.id}">
      ${esc(s.title)}${s.status === "closed" ? "（已关闭）" : ""}<br/>
      <span class="muted">${esc(MODEL_LABEL[s.model] || s.model)} · ${s.message_count} 条 · ${new Date(s.updated_at).toLocaleString()}</span>
      ${s.last_message ? `<div class="chat-preview muted">${esc(s.last_message)}</div>` : ""}
    </div>`).join("") || `<div class="muted">暂无历史对话，点上方「＋ 新对话」开始</div>`;
  $all("#chat-session-list .session-item").forEach((el) => {
    el.onclick = () => openChatSession(+el.dataset.id).catch((e) => toast(e.message));
  });
}
$("#chat-search").oninput = debounce(renderChatSessionList, 200);

async function openChatSession(id) {
  const d = await api(`/chat/sessions/${id}`);
  CHAT.sessionId = d.id;
  CHAT.scenario = d.scenario || null;
  CHAT.modelLocked = !!(d.scenario && (d.scenario.security_level === "export_control" || d.scenario.security_level === "sensitive"));
  CHAT.pendingAtts = [];
  renderChatChips();
  $("#chat-title").textContent = d.title;
  const sub = [];
  if (d.scenario) sub.push(`场景：${d.scenario.code} ${d.scenario.title}`);
  sub.push(d.status === "closed" ? "已关闭（留痕只读）" : "进行中");
  if (d.privacy === "metadata_only") sub.push("仅元数据留痕");
  if (CHAT.modelLocked) sub.push("🔒 敏感场景模型已锁定");
  $("#chat-sub").textContent = sub.join(" · ");
  $("#chat-model").value = d.model || "mimo";
  $("#chat-model").disabled = CHAT.modelLocked;
  const closed = d.status === "closed";
  $("#chat-input").disabled = closed;
  $("#btn-chat-send").disabled = closed;
  $("#btn-chat-attach").disabled = closed;
  $("#btn-chat-close").disabled = closed;
  renderChatThread(d.messages || []);
  loadChatSessions();
}

async function newChatSession() {
  const s = await api("/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ model: $("#chat-model").value || "mimo" }),
  });
  await openChatSession(s.id);
  $("#chat-input").focus();
}
$("#btn-chat-new").onclick = () => newChatSession().catch((e) => toast(e.message));

/* 场景广场联动：以场景提示词作为 system prompt 开启多轮对话 */
async function startScenarioChat(id) {
  const s = await api("/chat/sessions", { method: "POST", body: JSON.stringify({ scenario_id: id }) });
  switchTab("chat");
  await openChatSession(s.id);
  toast("已代入场景提示词开聊：直接描述需求即可，也可 📎 上传资料");
}

async function sendChatMessage() {
  if (CHAT.sending) return;
  const input = $("#chat-input");
  const content = input.value.trim();
  // 未建会话时自动新建（DeepSeek Harness 式：先聊起来）；注意保留已上传的附件
  if (!CHAT.sessionId) {
    const keep = CHAT.pendingAtts;
    await newChatSession();
    CHAT.pendingAtts = keep;
    renderChatChips();
  }
  const attIds = CHAT.pendingAtts.map((a) => a.id);
  const attNames = CHAT.pendingAtts.map((a) => a.filename).join("、");
  if (!content && !attIds.length) { toast("请输入消息或先上传文件"); return; }

  CHAT.sending = true;
  await withWaiting($("#btn-chat-send"), "思考中", async () => {
    const thread = $("#chat-thread");
    if (thread.querySelector(".chat-empty")) thread.innerHTML = "";
    // 乐观渲染用户气泡（附件名与服务端入库格式一致）
    const shown = (content || "请阅读附件内容并协助处理。") + (attNames ? `\n📎 附件：${attNames}` : "");
    thread.insertAdjacentHTML("beforeend",
      chatMsgHtml({ role: "user", content: shown, created_at: new Date().toISOString() }));
    thread.scrollTop = thread.scrollHeight;
    input.value = "";
    const r = await api(`/chat/sessions/${CHAT.sessionId}/messages`, {
      method: "POST",
      timeout: 180000,
      body: JSON.stringify({ content, model: $("#chat-model").value, attachment_ids: attIds }),
    });
    CHAT.pendingAtts = [];
    renderChatChips();
    thread.insertAdjacentHTML("beforeend", chatMsgHtml(r.message));
    thread.scrollTop = thread.scrollHeight;
    if (r.title && r.title !== $("#chat-title").textContent) $("#chat-title").textContent = r.title;
    if (r.degraded) toast("主模型繁忙，已自动降级到备用模型");
    if (r.quota_exceeded) toast("提醒：本月 token 额度已超（不阻断使用）");
    if (r.truncated) toast("附件内容过长，已截取关键部分注入");
    if (r.sensitive_hits && r.sensitive_hits.length) {
      toast("敏感信息标记：" + r.sensitive_hits.slice(0, 3).join("、"));
    }
    loadChatSessions();
  }).catch((e) => {
    toast(e.message);
    if (!input.value) input.value = content;  // 失败还原输入，便于重试
  });
  CHAT.sending = false;
}
$("#btn-chat-send").onclick = () => sendChatMessage();
$("#chat-input").addEventListener("keydown", (e) => {
  // isComposing：中文输入法组词中 Enter 不发送
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendChatMessage(); }
});

$("#btn-chat-attach").onclick = () => $("#chat-file").click();
$("#chat-file").onchange = (e) => uploadChatFiles(e.target.files);

$("#chat-model").onchange = async () => {
  // 立即持久化为会话默认模型；下一条消息生效（敏感场景下拉已禁用，不会走到这里）
  if (!CHAT.sessionId || CHAT.modelLocked) return;
  try {
    await api(`/chat/sessions/${CHAT.sessionId}`, {
      method: "PATCH", body: JSON.stringify({ model: $("#chat-model").value }),
    });
  } catch (e) { toast(e.message); }
};

$("#btn-chat-rename").onclick = async () => {
  if (!CHAT.sessionId) return toast("请先选择对话");
  const cur = $("#chat-title").textContent;
  const t = prompt("对话标题", cur);
  if (!t || !t.trim() || t.trim() === cur) return;
  try {
    await api(`/chat/sessions/${CHAT.sessionId}`, { method: "PATCH", body: JSON.stringify({ title: t.trim() }) });
    $("#chat-title").textContent = t.trim();
    loadChatSessions();
  } catch (e) { toast(e.message); }
};

$("#btn-chat-close").onclick = async () => {
  if (!CHAT.sessionId) return;
  if (!confirm("关闭后该对话变为只读（留痕规范：可关不可删）。确认关闭？")) return;
  try {
    await api(`/chat/sessions/${CHAT.sessionId}`, { method: "PATCH", body: JSON.stringify({ status: "closed" }) });
    toast("对话已关闭");
    await openChatSession(CHAT.sessionId);
  } catch (e) { toast(e.message); }
};

/* 工作台联动：把当前对话载入工作台，沿用定稿/diff/归档沉淀流程 */
$("#btn-chat-towork").onclick = async () => {
  if (!CHAT.sessionId) return toast("请先选择对话");
  try {
    switchTab("workspace");
    await openSessionInWorkspace(CHAT.sessionId);
    toast("已载入工作台：编辑右侧内容后可「保存人工定稿」/「归档到知产库」");
  } catch (e) { toast(e.message); }
};

/* ---------- 启动 ---------- */
(async function init() {
  try {
    const h = await fetch(API + "/health").then((r) => r.json());
    if (h.mock_llm) console.info("[V-FLO] 当前为 MOCK 模型模式，配置 API Key 后输出真实内容");
  } catch { /* ignore */ }
  // 企微扫码回调落地优先
  if (await tryWecomTokenLogin()) return;
  if (TOKEN && USER) {
    try {
      USER = await api("/auth/me");
      localStorage.setItem("vflo_user", JSON.stringify(USER));
      showMain();
      return;
    } catch { logout(false); }
  }
  initLoginPage();
  $("#login-view").classList.remove("hidden");
})();


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
  // 附件3 §五 提醒：逾期/今日到期任务弹一次提醒
  const rem = d.reminders || [];
  if (rem.length && !loadToday._reminded) {
    loadToday._reminded = true;
    toast("⏰ 提醒：" + rem.slice(0, 3).map((x) => x.text).join("；") + (rem.length > 3 ? ` 等 ${rem.length} 项` : ""));
  }
}

function todayItemHtml(x, overdue) {
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
  <div class="td-item bucket-${x.bucket}" draggable="${x.bucket === "B0" ? "false" : "true"}" data-tid="${t.id}">
    <div class="td-line">
      <span class="badge bucket">${lock}${BUCKET_LABEL[x.bucket] || x.bucket}</span>
      <span class="td-title">${esc(x.title)}</span>
      <span class="muted">${x.minutes}分钟</span>
      <span class="muted">评分 ${x.score ?? "-"}</span>
      <button class="ghost btn-td-done" data-id="${t.id}" style="width:auto">完成</button>
      ${overdue ? `<button class="ghost btn-td-resched2" data-id="${t.id}" style="width:auto">改期…</button>` : ""}
    </div>
    <div class="badges">${badges}</div>
  </div>`;
}

function renderTodayTimeline(d) {
  const sched = d.timeline.filter((x) => x.type !== "overflow");
  const over = d.timeline.filter((x) => x.type === "overflow");
  // 附件3 §5.1：过去该做未做 → 置顶提醒，可就地改期/降级
  const todayStr = new Date().toISOString().slice(0, 10);
  const isOverdue = (x) => {
    const due = String((x.task || {}).due_time || "").slice(0, 10);
    return due && due < todayStr;
  };
  const overdue = sched.filter(isOverdue);
  const normal = sched.filter((x) => !isOverdue(x));
  const overdueHtml = overdue.length
    ? `<div class="td-overdue-banner">⚠️ 过去该做未做 ${overdue.length} 项（置顶提醒，可改期或降级）</div>` +
      overdue.map((x) => todayItemHtml(x, true)).join("")
    : "";
  $("#td-timeline").innerHTML = (overdueHtml + normal.map((x) => todayItemHtml(x)).join("")) ||
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
  $all(".btn-td-resched2").forEach((b) => b.onclick = () => tdResched(+b.dataset.id));
  initTimelineDrag();
}

/* 时间轴拖拽排序（B0🔒固定不可拖，手册 1.5；拖放后全量顺序上报 /tasks/reorder） */
let _dragEl = null;
function initTimelineDrag() {
  const items = $all("#td-timeline .td-item[draggable='true']");
  items.forEach((el) => {
    el.ondragstart = () => { _dragEl = el; el.classList.add("dragging"); };
    el.ondragend = () => { el.classList.remove("dragging"); _dragEl = null; };
    el.ondragover = (e) => {
      e.preventDefault();
      if (!_dragEl || _dragEl === el) return;
      const box = el.getBoundingClientRect();
      const after = (e.clientY - box.top) > box.height / 2;
      el.parentNode.insertBefore(_dragEl, after ? el.nextSibling : el);
    };
    el.ondrop = async (e) => {
      e.preventDefault();
      const ids = $all("#td-timeline .td-item").map((x) => +x.dataset.tid).filter(Boolean);
      try {
        await api("/tasks/reorder", { method: "POST", body: JSON.stringify({ ids }) });
        toast("顺序已保存");
        loadToday();
      } catch (err) { toast(err.message); loadToday(); }
    };
  });
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
/* 语音录入（手册"口头录入"）：浏览器 SpeechRecognition，渐进增强，不支持则隐藏 */
(function initVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const btn = $("#btn-tc-voice");
  if (!SR || !btn) return;
  btn.classList.remove("hidden");
  let rec = null;
  let listening = false;
  btn.onclick = () => {
    if (listening && rec) { rec.stop(); return; }
    rec = new SR();
    rec.lang = "zh-CN";
    rec.interimResults = true;
    rec.continuous = true;
    const base = $("#tc-text").value;
    rec.onresult = (ev) => {
      let text = "";
      for (let i = 0; i < ev.results.length; i++) text += ev.results[i][0].transcript;
      $("#tc-text").value = (base ? base + "；" : "") + text;
    };
    rec.onend = () => { listening = false; btn.textContent = "🎤 语音录入"; };
    rec.onerror = (e) => { listening = false; btn.textContent = "🎤 语音录入"; toast("语音识别失败：" + (e.error || "未知")); };
    try {
      rec.start();
      listening = true;
      btn.textContent = "⏹ 停止录入";
      toast("正在聆听…说完点「停止录入」");
    } catch (e) { toast("无法启动语音识别"); }
  };
})();

$("#btn-tc-parse").onclick = () => {
  const text = $("#tc-text").value.trim();
  if (!text) { toast("请先口述/粘贴任务"); return; }
  withWaiting($("#btn-tc-parse"), "拆解中", async () => {
    const r = await api("/tasks/capture", { method: "POST", timeout: 120000, body: JSON.stringify({ text, source: "chat", use_llm: true }) });
    TD_CANDS = r.candidates || [];
    renderCands();
    toast(`拆解出 ${TD_CANDS.length} 条候选，请勾选确认`);
  }).catch((e) => toast(e.message));
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

/* 简道云双向同步：拉取我的任务入池；状态回写在 tdDone 内由后端完成 */
$("#btn-td-sync").onclick = async () => {
  const btn = $("#btn-td-sync");
  btn.disabled = true; btn.textContent = "同步中…";
  try {
    const r = await api("/tasks/sync-jdy", { method: "POST", body: JSON.stringify({ mine_only: true }) });
    if (r.mode === "mock") toast(r.hint || "简道云为 MOCK 模式");
    else toast("同步完成：新入池 " + r.synced + " 条，跳过 " + r.skipped + " 条（共扫描 " + r.total + " 条）");
    loadToday();
  } catch (e) { toast(e.message); }
  finally { btn.disabled = false; btn.textContent = "⇅ 同步简道云"; }
};

/* ---------- 出口管制（附件1 §二：G1→G2→G5；附件5 §3.3 红线） ---------- */
const DECISION_LABEL = {
  pending: "待放行（完成清单+合规官审核后放行）",
  manual_review: "人工审核放行（合规官终审）",
  escalate: "升级分类/复核（未完成不得签约发运）",
  reject: "硬性禁止（立即停止）",
  pass: "放行",
};

function ecCollect() {
  const body = {};
  $all("[data-ec]").forEach((el) => { body[el.dataset.ec] = el.value.trim(); });
  return body;
}

$("#btn-ec-screen").onclick = async () => {
  const body = ecCollect();
  if (!body.customer_name || !body.country) { toast("客户名称与目的地为必填"); return; }
  const btn = $("#btn-ec-screen");
  btn.disabled = true; btn.textContent = "筛查中…";
  try {
    const r = await api("/export-checks", { method: "POST", body: JSON.stringify(body) });
    $("#ec-result").innerHTML = ecRender(r);
    toast("审查单已生成：" + r.case_no);
    loadCompliance(true);
  } catch (e) { toast(e.message); }
  finally { btn.disabled = false; btn.textContent = "提交初筛（生成审查单）"; }
};

function ecRender(r) {
  const cl = (r.checklist || []).map((c) =>
    `<div class="kv"><div class="k">${esc(c.code)}${c.required ? " *" : ""}</div>
     <div>${esc(c.name)} — ${c.status === "pass" ? "✅" : c.status === "fail" ? "❌" : "⏳ 待办"}</div></div>`).join("");
  const flags = (r.red_flags || []).map((x) => `<div class="badge exp">${esc(x)}</div>`).join("") || "无";
  return `
    <div class="proj-card">
      <div class="code">${esc(r.case_no)} · ${esc(r.status)}</div>
      <h4>结论：${esc(DECISION_LABEL[r.decision] || r.decision)}</h4>
      <div class="muted">国家风险 ${esc(r.country_risk)} ｜ 制裁名单 ${esc(r.sanctions_hit)} ｜ 物项分类 ${esc(r.item_control)} ｜ 许可证 ${esc(r.license_needed)}</div>
      <p>${esc(r.decision_note || "")}</p>
      <div class="badges">红旗：${flags}</div>
      <h4>十二项检查清单</h4>${cl}
      ${r.reviewed_by ? `<p class="muted">合规官终审：${esc(r.reviewed_by)} ｜ ${esc(r.review_note || "")}</p>` : ""}
    </div>`;
}

async function loadCompliance(keepResult) {
  try {
    const list = await api("/export-checks");
    const isAdmin = USER && USER.role === "admin";
    $("#ec-list").innerHTML = list.map((r) => `
      <div class="asset-item">
        <h4>${esc(r.case_no)} · ${esc(r.customer_name)}（${esc(r.country)}）
          <span class="badge ${r.decision === "reject" ? "exp" : ""}">${esc(DECISION_LABEL[r.decision] || r.decision)}</span>
          <span class="badge">${esc(r.status)}</span>
        </h4>
        <div class="muted">${new Date(r.created_at).toLocaleString()} ｜ 物项 ${esc(r.item_control)} ｜ 红旗 ${(r.red_flags || []).length} 项</div>
        ${r.reviewed_by ? `<div class="muted">终审：${esc(r.reviewed_by)} ${esc(r.review_note || "")}</div>` : ""}
        <div class="td-actions">
          <button class="ghost btn-ec-view" data-no="${esc(r.case_no)}" style="width:auto">查看清单</button>
          ${isAdmin && r.status === "submitted" ? `
            <button class="primary btn-ec-approve" data-no="${esc(r.case_no)}" style="width:auto">合规官放行</button>
            <button class="secondary btn-ec-cond" data-no="${esc(r.case_no)}" style="width:auto">附条件放行</button>
            <button class="ghost btn-ec-reject" data-no="${esc(r.case_no)}" style="width:auto">否决</button>` : ""}
        </div>
      </div>`).join("") || `<p class="muted">暂无审查单</p>`;
    $all(".btn-ec-view").forEach((b) => b.onclick = async () => {
      const r = await api(`/export-checks/${b.dataset.no}`);
      $("#modal-body").innerHTML = ecRender(r);
      $("#modal").classList.remove("hidden");
    });
    const review = (action) => async (b) => {
      const note = prompt(action === "reject" ? "否决理由：" : "审核意见/放行条件（可空）：", "");
      if (note === null) return;
      try {
        await api(`/export-checks/${b.dataset.no}/review`, {
          method: "POST", body: JSON.stringify({ action, note: note || "" }),
        });
        toast("已提交终审结论");
        loadCompliance(true);
      } catch (e) { toast(e.message); }
    };
    $all(".btn-ec-approve").forEach((b) => b.onclick = () => review("approve")(b));
    $all(".btn-ec-cond").forEach((b) => b.onclick = () => review("conditions")(b));
    $all(".btn-ec-reject").forEach((b) => b.onclick = () => review("reject")(b));
  } catch (e) { /* 未登录等情况忽略 */ }
}

# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office\web\app.js")
text = p.read_text(encoding="utf-8")
start = text.find("async function ensureSession()")
end = text.find('$("#btn-finalize").onclick')
print("start", start, "end", end, "len", len(text))
if start == -1 or end == -1:
    raise SystemExit("markers not found")
replacement = """function readFormVariables() {
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

"""
p.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print("patched ok")

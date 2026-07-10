/**
 * Ollama-hacking-tool — frontend controller
 */

const CMD_SCHEMAS = {
  "cve-scan": {
    fields: [
      {
        name: "platform",
        label: "Plataforma objetivo (opcional)",
        type: "select",
        options: [
          { value: "", label: "Auto / desconocido" },
          { value: "windows", label: "Windows" },
          { value: "linux", label: "Linux" },
          { value: "darwin", label: "macOS" },
        ],
      },
    ],
    hint: "Detecta version via GET /api/version y correlaciona con CVEs historicos reales.",
  },
  list: { fields: [] },
  ps: { fields: [] },
  show: {
    fields: [{ name: "model", label: "Model name", type: "text", required: true, placeholder: "llama3.2:3b" }],
  },
  generate: {
    fields: [
      { name: "model", label: "Model", type: "text", required: true },
      { name: "prompt", label: "Prompt", type: "textarea", required: true, full: true },
      { name: "options", label: "Options (JSON)", type: "textarea", placeholder: '{"temperature": 0.7}', full: true },
    ],
    streamDefault: true,
  },
  chat: {
    fields: [
      { name: "model", label: "Model", type: "text", required: true },
      { name: "system", label: "System prompt", type: "textarea", full: true },
      { name: "message", label: "User message", type: "textarea", required: true, full: true },
      { name: "options", label: "Options (JSON)", type: "textarea", full: true },
      { name: "image", label: "Imagen (multimodal)", type: "file", accept: "image/*" },
    ],
    streamDefault: true,
  },
  interactive: {
    fields: [
      { name: "model", label: "Model", type: "text", required: true },
      { name: "system", label: "System prompt", type: "textarea", full: true },
      { name: "message", label: "Mensaje", type: "textarea", required: true, full: true, placeholder: "Escribe y pulsa EXECUTE para continuar la conversación" },
      { name: "messages", label: "Historial (JSON)", type: "textarea", full: true, placeholder: '[{"role":"user","content":"..."}]' },
      { name: "image", label: "Imagen adjunta", type: "file", accept: "image/*" },
    ],
    streamDefault: true,
  },
  embeddings: {
    fields: [
      { name: "model", label: "Model", type: "text", required: true, placeholder: "nomic-embed-text" },
      { name: "text", label: "Text to embed", type: "textarea", required: true, full: true },
    ],
  },
  pull: {
    fields: [
      { name: "model", label: "Model name", type: "text", placeholder: "llama3.2:3b" },
      { name: "file", label: "Archivo bulk (1 modelo/línea)", type: "file", accept: ".txt,.lst,.modelfile" },
    ],
    streamDefault: true,
    hint: "Indica model O adjunta archivo .txt con nombres (uno por línea)",
  },
  "bulk-pull": {
    fields: [
      { name: "file", label: "Lista de modelos (.txt)", type: "file", accept: ".txt,.lst", required: true },
      { name: "models_list", label: "O pega la lista aquí", type: "textarea", full: true, placeholder: "llama3.2:3b\nmistral:latest" },
    ],
    streamDefault: true,
  },
  push: {
    fields: [{ name: "model", label: "Model to push", type: "text", required: true }],
    streamDefault: true,
  },
  create: {
    fields: [
      { name: "name", label: "New model name", type: "text", placeholder: "command-poc (obligatorio con Modelfile)" },
      { name: "modelfile", label: "Modelfile / YAML PoC", type: "textarea", full: true, placeholder: "FROM qwen2.5:1.5b\nSYSTEM ...\n\n— o YAML PoC-LocalModel —" },
      { name: "file", label: "O adjunta fichero", type: "file", accept: ".modelfile,.txt,.mf,.yaml,.yml" },
    ],
    streamDefault: true,
    hint: "Ollama 0.30+: convierte a POST /api/create {model, from, system, template, parameters, messages}.",
  },
  copy: {
    fields: [
      { name: "source", label: "Source", type: "text", required: true },
      { name: "destination", label: "Destination", type: "text", required: true },
    ],
  },
  delete: {
    fields: [{ name: "model", label: "Model to DELETE", type: "text", required: true }],
    destructive: true,
  },
  unload: {
    fields: [{ name: "model", label: "Model to unload from RAM", type: "text", required: true }],
  },
  "openai-models": { fields: [] },
  "openai-chat": {
    fields: [
      { name: "model", label: "Model", type: "text", required: true },
      { name: "message", label: "Message", type: "textarea", required: true, full: true },
    ],
    streamDefault: true,
  },
  "openai-completions": {
    fields: [
      { name: "model", label: "Model", type: "text", required: true },
      { name: "prompt", label: "Prompt", type: "textarea", required: true, full: true },
    ],
    streamDefault: true,
  },
  "openai-embeddings": {
    fields: [
      { name: "model", label: "Model", type: "text", required: true },
      { name: "text", label: "Input", type: "textarea", required: true, full: true },
    ],
  },
};

const STREAMABLE = new Set([
  "generate", "chat", "interactive", "pull", "bulk-pull", "push", "create",
  "openai-chat", "openai-completions",
]);

let currentCmd = "list";
let chatHistory = [];
let lastStreamTokens = "";

const $ = (sel) => document.querySelector(sel);
const output = $("#output");
const formFields = $("#formFields");
const cmdForm = $("#cmdForm");
const useStream = $("#useStream");

function ts() {
  return new Date().toLocaleTimeString("es-ES", { hour12: false });
}

function logDebugBlock(debug, label = "debug") {
  if (!debug) return;
  appendOutput(`  ${label}:\n${JSON.stringify(debug, null, 2)}\n`, "info");
}

function logErrorInfo(data, httpStatus) {
  const payload = typeof data === "string" ? { error: data } : (data || {});
  const message = payload.message || payload.error || "Error desconocido";
  logLine(message, "err");
  if (payload.error_type) logLine(`  tipo: ${payload.error_type}`, "err");
  if (httpStatus) logLine(`  HTTP ${httpStatus}`, "err");
  if (payload.detail) logLine(`  detalle: ${payload.detail}`, "err");
  if (payload.debug) logDebugBlock(payload.debug, "debug");
  if (payload.traceback) appendOutput(`  traceback:\n${payload.traceback}\n`, "err");
}

function parseErrorData(raw) {
  if (!raw) return { error: "Error vacío" };
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") return parsed;
  } catch {
    // texto plano del servidor
  }
  return { error: raw };
}

function appendOutput(text, cls = "") {
  const span = document.createElement("span");
  if (cls) span.className = cls;
  span.textContent = text;
  output.appendChild(span);
  output.scrollTop = output.scrollHeight;
}

function logLine(text, cls = "info") {
  appendOutput(`[${ts()}] `, "info");
  appendOutput(text + "\n", cls);
}

function clearOutput() {
  output.textContent = "";
  $("#outputMeta").textContent = "";
}

function getTargetConfig() {
  return {
    host: $("#targetHost").value.trim(),
    timeout: $("#targetTimeout").value,
  };
}

function buildForm(cmd) {
  const schema = CMD_SCHEMAS[cmd] || { fields: [] };
  formFields.innerHTML = "";

  if (schema.hint) {
    const hint = document.createElement("p");
    hint.className = "field full-width";
    hint.style.color = "var(--yellow)";
    hint.style.fontSize = "0.75rem";
    hint.style.gridColumn = "1 / -1";
    hint.textContent = "⚡ " + schema.hint;
    formFields.appendChild(hint);
  }

  for (const field of schema.fields) {
    const wrap = document.createElement("div");
    wrap.className = "field" + (field.full ? " full-width" : "");

    const label = document.createElement("label");
    label.textContent = field.label;
    if (field.required) label.innerHTML += ' <span class="hint">*</span>';
    wrap.appendChild(label);

    let input;
    if (field.type === "textarea") {
      input = document.createElement("textarea");
      input.name = field.name;
      if (field.placeholder) input.placeholder = field.placeholder;
    } else if (field.type === "file") {
      input = document.createElement("input");
      input.type = "file";
      input.name = field.name;
      if (field.accept) input.accept = field.accept;
    } else if (field.type === "select") {
      input = document.createElement("select");
      input.name = field.name;
      for (const opt of field.options || []) {
        const o = document.createElement("option");
        o.value = opt.value;
        o.textContent = opt.label;
        input.appendChild(o);
      }
    } else {
      input = document.createElement("input");
      input.type = field.type || "text";
      input.name = field.name;
      if (field.placeholder) input.placeholder = field.placeholder;
    }
    if (field.required) input.required = true;
    wrap.appendChild(input);
    formFields.appendChild(wrap);
  }

  useStream.checked = schema.streamDefault ?? false;
  useStream.disabled = !STREAMABLE.has(cmd);
  useStream.parentElement.style.opacity = STREAMABLE.has(cmd) ? "1" : "0.4";
}

function selectCommand(btn) {
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  currentCmd = btn.dataset.cmd;
  $("#cmdMethod").textContent = btn.dataset.method || "";
  $("#cmdName").textContent = currentCmd;
  buildForm(currentCmd);
}

function updateBadges(version, risk) {
  const verEl = $("#targetVersion");
  const riskEl = $("#targetRisk");
  verEl.textContent = version ? `v${version}` : "";
  riskEl.textContent = risk || "";
  riskEl.className = "risk-badge";
  if (risk) {
    riskEl.classList.add(`risk-${(risk || "unknown").toLowerCase()}`);
  }
}

function renderCveReport(report) {
  clearOutput();
  updateBadges(report.version !== "desconocida" ? report.version : null, report.risk_level);

  logLine(`=== CVE SCAN :: Ollama ${report.version} (${report.version_source || "?"}) ===`, "warn");
  logLine(report.message, "info");
  logLine(
    `Resumen: ${report.summary.vulnerable} vulnerables | ${report.summary.patched} parcheados | ${report.summary.manual_check} manual`,
    "info"
  );

  if (report.exploitable_endpoints?.length) {
    logLine("Endpoints de interes: " + report.exploitable_endpoints.join(", "), "warn");
  }

  const sections = [
    ["VULNERABLES (explotacion probable)", report.vulnerable, "vulnerable"],
    ["PARCHEADOS", report.patched, "patched"],
    ["VERIFICACION MANUAL", report.manual_check, "manual"],
  ];

  for (const [title, items, cls] of sections) {
    if (!items?.length) continue;
    appendOutput(`\n--- ${title} ---\n`, "warn");
    for (const cve of items) {
      const card = document.createElement("div");
      card.className = `cve-card ${cls}`;
      card.innerHTML = `
        <div><span class="cve-id">${cve.id}</span> ${cve.alias ? `"${cve.alias}"` : ""}
          <span class="cve-sev-${cve.severity}">[${(cve.severity || "").toUpperCase()}${cve.cvss ? " CVSS " + cve.cvss : ""}]</span></div>
        <div>Rango: ${cve.affected_range} | Endpoint: ${cve.endpoint}</div>
        <div>${cve.description}</div>
        <div style="color:var(--text-dim);margin-top:0.25rem">Mec: ${cve.mechanism}</div>
        <div style="color:var(--orange)">Impacto: ${cve.impact}</div>
      `;
      output.appendChild(card);
    }
  }
  output.scrollTop = output.scrollHeight;
}

async function runCveScan(platform) {
  logLine(`CVE SCAN → ${getTargetConfig().host} ...`, "warn");
  const body = { ...getTargetConfig() };
  if (platform) body.platform = platform;

  try {
    const res = await fetch("/api/cve-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!data.ok) {
      logErrorInfo(data, res.status);
      return;
    }
    renderCveReport(data.report);
    $("#targetStatus").className = "status-dot online";
  } catch (e) {
    logLine("Error: " + e.message, "err");
  }
}

async function pingTarget() {
  const status = $("#targetStatus");
  status.className = "status-dot offline";
  logLine(`Ping → ${getTargetConfig().host} ...`);

  try {
    const res = await fetch("/api/ping", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(getTargetConfig()),
    });
    const data = await res.json();
    if (data.ok) {
      status.className = "status-dot online";
      logLine(data.message, "info");
      updateBadges(data.version, data.risk_level);
      if (data.cve_vulnerable_count > 0) {
        logLine(`${data.cve_vulnerable_count} CVE(s) probables — ejecuta CVE SCAN para detalle`, "err");
      }
    } else {
      logErrorInfo(data, res.status);
      updateBadges(null, null);
    }
  } catch (e) {
    logLine("Error de red: " + e.message, "err");
  }
}

function buildFormData() {
  const fd = new FormData(cmdForm);
  const cfg = getTargetConfig();
  fd.set("host", cfg.host);
  fd.set("timeout", cfg.timeout);
  if (useStream.checked) fd.set("stream", "true");
  return fd;
}

async function executeCommand(e) {
  e.preventDefault();

  if (CMD_SCHEMAS[currentCmd]?.destructive) {
    const model = cmdForm.querySelector('[name="model"]')?.value;
    if (!confirm(`⚠ DELETE permanente del modelo "${model}" en el target. ¿Continuar?`)) return;
  }

  const btn = $("#btnExecute");
  btn.disabled = true;
  logLine(`EXEC → ${currentCmd.toUpperCase()} @ ${getTargetConfig().host}`, "warn");
  $("#outputMeta").textContent = currentCmd;

  const fd = buildFormData();
  const streaming = useStream.checked && STREAMABLE.has(currentCmd);
  lastStreamTokens = "";

  try {
    if (currentCmd === "cve-scan") {
      await runCveScan(fd.get("platform") || null);
    } else if (streaming) {
      await executeStream(fd);
    } else {
      await executeOnce(fd);
    }
    if (currentCmd === "interactive") {
      persistInteractiveHistory(fd, streaming);
    }
  } catch (err) {
    logLine("FATAL: " + err.message, "err");
  } finally {
    btn.disabled = false;
  }
}

async function executeOnce(fd) {
  const res = await fetch(`/api/execute/${currentCmd}`, { method: "POST", body: fd });
  let data;
  try {
    data = await res.json();
  } catch {
    logErrorInfo({ error: `Respuesta no JSON (HTTP ${res.status})` }, res.status);
    return;
  }
  if (!data.ok) {
    logErrorInfo(data, res.status);
    return;
  }
  if (data.meta?.converted) {
    logLine(
      `→ API create (from=${data.meta.base_model || data.debug?.from || "?"})`,
      "info"
    );
  }
  if (data.debug) logDebugBlock(data.debug, "trace CREATE");
  if (currentCmd === "cve-scan" && data.result?.cve_report) {
    renderCveReport(data.result.cve_report);
    return;
  }
  appendOutput(JSON.stringify(data.result, null, 2) + "\n");
}

async function executeStream(fd) {
  const res = await fetch(`/api/stream/${currentCmd}`, { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    logErrorInfo(err, res.status);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const block of parts) {
      parseSSEBlock(block);
    }
  }
  appendOutput("\n");
}

function parseSSEBlock(block) {
  let event = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7);
    else if (line.startsWith("data: ")) data = line.slice(6);
  }
  if (!data) return;

  if (event === "token") {
    lastStreamTokens += data;
    appendOutput(data, "token");
  } else if (event === "log") {
    logLine(data, "info");
  } else if (event === "debug") {
    logDebugBlock(parseErrorData(data), "trace CREATE");
  } else if (event === "error") {
    logErrorInfo(parseErrorData(data));
  } else if (event === "done" || event === "result") {
    try {
      const parsed = JSON.parse(data);
      appendOutput("\n" + JSON.stringify(parsed, null, 2) + "\n");
    } catch {
      appendOutput("\n" + data + "\n");
    }
  } else if (event === "end") {
    logLine("Stream finalizado.", "info");
  }
}

function persistInteractiveHistory(fd, streamed) {
  const msg = fd.get("message");
  if (!msg) return;
  const sys = fd.get("system");
  if (sys && !chatHistory.some((m) => m.role === "system")) {
    chatHistory.push({ role: "system", content: sys });
  }
  chatHistory.push({ role: "user", content: msg });
  if (streamed && lastStreamTokens) {
    chatHistory.push({ role: "assistant", content: lastStreamTokens });
  }

  const histField = cmdForm.querySelector('[name="messages"]');
  if (histField) {
    histField.value = JSON.stringify(chatHistory, null, 2);
  }
  const msgField = cmdForm.querySelector('[name="message"]');
  if (msgField) msgField.value = "";
}

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => selectCommand(btn));
});

$("#btnPing").addEventListener("click", pingTarget);
$("#btnCveScan").addEventListener("click", () => {
  const platform = cmdForm.querySelector('[name="platform"]')?.value || null;
  runCveScan(platform);
});
$("#btnClear").addEventListener("click", () => {
  clearOutput();
  chatHistory = [];
});
cmdForm.addEventListener("submit", executeCommand);

buildForm("list");
logLine("Ollama-hacking-tool cargado. Configura TARGET y selecciona operación.", "info");

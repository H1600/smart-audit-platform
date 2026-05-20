/* ===== State ===== */
const state = {
  selectedTaskId: null,
  recordPage: 1,
  pageSize: 20,
  recordsTotal: 0,
};

const titles = {
  dashboard: ["工作台", "查看系统状态、任务进度与异常提醒"],
  upload: ["文件上传", "上传 PDF、图片、Excel 并生成处理任务"],
  tasks: ["任务详情", "跟踪 OCR、ETL、入库与勾稽校验进度"],
  records: ["数据结果", "按日期、科目、凭证号、金额筛选结构化数据"],
  exports: ["导出中心", "导出 Excel、简易 XBRL 或校验报告"],
  settings: ["系统设置", "配置本地 OCR、输出目录与日志策略"],
};

/* ===== DOM Helpers ===== */
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

/* ===== Formatting ===== */
function money(v) {
  return Number(v || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ===== API ===== */
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `HTTP ${r.status}`);
  }
  return r.headers.get("content-type")?.includes("application/json") ? r.json() : r;
}

/* ===== Navigation ===== */
function switchView(name) {
  $$(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.view === name));
  $$(".view").forEach((el) => el.classList.toggle("active", el.id === name));
  $("#viewTitle").textContent = titles[name][0];
  $("#viewSubtitle").textContent = titles[name][1];
  if (name === "tasks") loadTasks();
  if (name === "records") loadRecords();
  if (name === "dashboard") refreshDashboard();
}

/* ===== Badge ===== */
function badge(status) {
  const map = { pending: "待处理", queued: "排队中", running: "处理中", completed: "已完成", failed: "失败" };
  const cls = status === "completed" ? "ok" : status === "failed" ? "fail" : "warn";
  return `<span class="badge ${cls}">${map[status] || status}</span>`;
}

/* ===== Task Card ===== */
function taskCard(t) {
  const active = state.selectedTaskId === t.id ? "active" : "";
  const step = t.current_step || "";
  const pct = t.progress || 0;
  const name = t.filename || "未命名文件";
  return `<div class="task-card ${active}" data-task="${t.id}">
    <div class="task-card-header">
      <strong title="${name}">#${t.id} ${name}</strong>
      ${badge(t.status)}
    </div>
    <div class="task-meta">${step} · ${pct}%</div>
    <div class="progress-bar"><span style="width:${pct}%"></span></div>
  </div>`;
}

/* ===== Health ===== */
async function checkHealth() {
  try {
    await api("/api/health");
    $("#healthDot").style.background = "var(--success)";
    $("#healthText").textContent = "本地服务正常";
  } catch {
    $("#healthDot").style.background = "var(--danger)";
    $("#healthText").textContent = "服务不可用";
  }
}

/* ===== Tasks ===== */
async function loadTasks() {
  const tasks = await api("/api/tasks");

  // Vertical list (任务详情页)
  const listHtml = tasks.length
    ? tasks.map(taskCard).join("")
    : '<div class="detail-empty">暂无任务</div>';
  $("#taskList").innerHTML = listHtml;

  // Horizontal scroll (工作台)
  const recentHtml = tasks.length
    ? tasks.map(taskCard).join("")
    : '<div class="detail-empty">暂无任务</div>';
  $("#recentTasks").innerHTML = recentHtml;

  // Bind click
  $$(".task-card").forEach((el) =>
    el.addEventListener("click", () => selectTask(Number(el.dataset.task)))
  );
  return tasks;
}

/* ===== Select Task ===== */
async function selectTask(id) {
  state.selectedTaskId = id;
  const task = await api(`/api/tasks/${id}`);
  const report = await api(`/api/reports/${id}`).catch(() => null);

  $("#rerunTaskBtn").disabled = task.status === "running";
  // Sync export task select
  const exportSelect = $("#exportTaskSelect");
  if (exportSelect) {
    const opt = exportSelect.querySelector(`option[value="${id}"]`);
    if (opt) exportSelect.value = id;
  }

  const logs = (task.logs || []).join("\n") || "暂无日志";
  const reportsHtml = (report?.reports || [])
    .map(
      (r) =>
        `<div class="exception-card">
          ${badge(r.passed ? "completed" : "failed")}
          <strong>${r.rule_name}</strong>
          <pre>${JSON.stringify(r.details, null, 2)}</pre>
        </div>`
    )
    .join("") || "暂无报告";

  $("#taskDetail").innerHTML = `
    <div class="detail-content scroll-y">
      <div class="task-card active">
        <div class="task-card-header">
          <strong>#${task.id} ${task.filename}</strong>
          ${badge(task.status)}
        </div>
        <div class="task-meta">${task.current_step} · ${task.progress}%</div>
        <div class="progress-bar"><span style="width:${task.progress}%"></span></div>
      </div>
      <h3>📜 处理日志</h3>
      <pre class="log-block">${logs}</pre>
      <h3>✅ 勾稽校验</h3>
      <div style="display:grid;gap:8px">${reportsHtml}</div>
    </div>`;
  await loadTasks();
}

/* ===== Run / Poll ===== */
async function runTask(id) {
  await api(`/api/tasks/${id}/run`, { method: "POST" });
  state.selectedTaskId = id;
  pollTask(id);
}

async function pollTask(id) {
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 1200));
    await selectTask(id);
    await refreshDashboard();
    const t = await api(`/api/tasks/${id}`);
    if (["completed", "failed"].includes(t.status)) break;
  }
}

/* ===== Upload ===== */
async function uploadFiles(files) {
  const queue = $("#uploadQueue");
  for (const file of files) {
    const row = document.createElement("div");
    row.className = "queue-row";
    row.innerHTML = `<strong>${file.name}</strong><span class="task-meta">⏳ 上传中</span>`;
    queue.prepend(row);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api("/api/files/upload", { method: "POST", body: form });
      row.innerHTML = `<strong>${file.name}</strong><span class="badge info">任务 #${result.task_id}</span>`;
      await runTask(result.task_id);
    } catch (err) {
      row.innerHTML = `<strong>${file.name}</strong><span class="badge fail">${err.message}</span>`;
    }
  }
}

/* ===== Records ===== */
function recordQuery() {
  const p = new URLSearchParams({ page: state.recordPage, page_size: state.pageSize });
  const fields = {
    start_date: $("#startDate").value,
    end_date: $("#endDate").value,
    account: $("#accountFilter").value,
    voucher_no: $("#voucherFilter").value,
    min_amount: $("#minAmount").value,
  };
  Object.entries(fields).forEach(([k, v]) => v && p.set(k, v));
  return p;
}

async function loadRecords() {
  const panel = $(".records-panel");
  panel.classList.add("records-loading");

  try {
    const data = await api(`/api/records?${recordQuery()}`);
    state.recordsTotal = data.total;
    state.recordPage = data.page;

    const totalPages = Math.max(1, Math.ceil(data.total / state.pageSize));
    $("#recordTotal").textContent = `${data.total} 条记录`;
    $("#totalPages").textContent = totalPages;
    $("#pageInput").value = data.page;
    $("#prevPage").disabled = data.page <= 1;
    $("#nextPage").disabled = data.page >= totalPages;

    // 计算汇总
    let debitSum = 0, creditSum = 0, excCount = 0;
    data.items.forEach(r => {
      debitSum += r.debit || 0;
      creditSum += r.credit || 0;
      if (r.is_exception) excCount++;
    });
    $("#scTotal").textContent = data.total;
    $("#scDebit").textContent = `¥${money(debitSum)}`;
    $("#scCredit").textContent = `¥${money(creditSum)}`;
    $("#scException").textContent = excCount;

    // 空值友好展示函数
    const nv = (v, fallback = "—") => (v && String(v).trim()) ? v : `<span class="null-placeholder">${fallback}</span>`;
    const mc = (v) => money(v);

    if (!data.items.length) {
      $("#recordRows").innerHTML = '<tr class="empty-row"><td colspan="9">暂无匹配记录，试试调整筛选条件</td></tr>';
      return;
    }

    $("#recordRows").innerHTML = data.items
      .map(
        (r, i) =>
          `<tr class="${r.is_exception ? "exception" : ""}" data-record="${r.id}">
            <td style="color:var(--text-tertiary);font-size:12px">${(data.page - 1) * state.pageSize + i + 1}</td>
            <td>${nv(r.date)}</td>
            <td>${nv(r.voucher_no)}</td>
            <td>${r.account_code ? `<span style="color:var(--text-secondary)">${r.account_code}</span>` : ""} ${nv(r.account_name, "未映射")}</td>
            <td title="${r.summary || ""}">${r.summary ? r.summary.slice(0, 32) + (r.summary.length > 32 ? "…" : "") : '<span class="null-placeholder">无摘要</span>'}</td>
            <td class="money-cell">${mc(r.debit)}</td>
            <td class="money-cell">${mc(r.credit)}</td>
            <td class="money-cell">${mc(r.balance)}</td>
            <td>${r.is_exception ? '<span class="badge warn">异常</span>' : '<span class="badge ok">正常</span>'}</td>
          </tr>`
      )
      .join("");

    $$("tbody tr").forEach((el) =>
      el.addEventListener("click", () => openRecord(Number(el.dataset.record)))
    );
  } finally {
    panel.classList.remove("records-loading");
  }
}

function goToPage(p) {
  const totalPages = Math.max(1, Math.ceil(state.recordsTotal / state.pageSize));
  const page = Math.max(1, Math.min(totalPages, p));
  if (page !== state.recordPage) {
    state.recordPage = page;
    loadRecords();
  }
}

async function openRecord(id) {
  const detail = await api(`/api/records/${id}`);

  // 空值友好
  const nv = (v, fb = "—") => (v && String(v).trim()) ? v : `<span class="null-placeholder">${fb}</span>`;

  const body = $("#drawerBody");
  body.innerHTML = `
    <div class="drawer-record-card">
      <div class="drawer-field">
        <span class="df-label">记录编号</span>
        <span class="df-value">#${detail.id}</span>
      </div>
      <div class="drawer-field">
        <span class="df-label">任务</span>
        <span class="df-value">任务 #${detail.task_id} ${detail.file_id ? '· 文件 #' + detail.file_id : ''}</span>
      </div>
      <div class="drawer-field">
        <span class="df-label">日期</span>
        <span class="df-value">${nv(detail.date)}</span>
      </div>
      <div class="drawer-field">
        <span class="df-label">凭证号</span>
        <span class="df-value">${nv(detail.voucher_no)}</span>
      </div>
      <div class="drawer-field">
        <span class="df-label">科目</span>
        <span class="df-value">${detail.account_code ? `<span style="color:var(--text-secondary)">${detail.account_code}</span> ` : ""}${nv(detail.account_name, "未映射")}</span>
      </div>
      <div class="drawer-field">
        <span class="df-label">摘要</span>
        <span class="df-value">${nv(detail.summary, "无摘要")}</span>
      </div>
      <div class="drawer-field">
        <span class="df-label">借方金额</span>
        <span class="df-value money">¥${money(detail.debit)}</span>
      </div>
      <div class="drawer-field">
        <span class="df-label">贷方金额</span>
        <span class="df-value money">¥${money(detail.credit)}</span>
      </div>
      <div class="drawer-field">
        <span class="df-label">余额</span>
        <span class="df-value money">¥${money(detail.balance)}</span>
      </div>
      ${detail.is_exception ? `
      <div class="drawer-field">
        <span class="df-label">异常原因</span>
        <span class="df-value exception-reason">${detail.exception_reason}</span>
      </div>` : ''}
      <div class="drawer-section-title">来源定位</div>
      <div class="drawer-field">
        <span class="df-label">来源页码</span>
        <span class="df-value">${detail.source_page || 1}</span>
      </div>
      <div class="drawer-field">
        <span class="df-label">来源行号</span>
        <span class="df-value">${detail.source_row || "—"}</span>
      </div>
      <div class="drawer-raw-json">${JSON.stringify(detail.source_text ? JSON.parse(detail.source_text) : {}, null, 2)}</div>
      <div class="drawer-section-title">完整数据</div>
      <div class="drawer-raw-json">${JSON.stringify(detail, null, 2)}</div>
    </div>`;

  // 打开抽屉
  $("#detailDrawer").classList.add("open");
  $("#drawerOverlay").classList.add("show");
  $(".records-panel").classList.add("drawer-open");
}

function closeDrawer() {
  $("#detailDrawer").classList.remove("open");
  $("#drawerOverlay").classList.remove("show");
  $(".records-panel").classList.remove("drawer-open");
}

/* ===== Dashboard ===== */
async function refreshDashboard() {
  const [tasks, records] = await Promise.all([
    loadTasks(),
    api("/api/records?page=1&page_size=100"),
  ]);

  $("#metricPending").textContent = tasks.filter((t) =>
    ["pending", "running", "queued"].includes(t.status)
  ).length;
  $("#metricDone").textContent = tasks.filter((t) => t.status === "completed").length;
  $("#metricRecords").textContent = records.total;

  const exceptions = records.items.filter((r) => r.is_exception);
  $("#metricExceptions").textContent = exceptions.length;

  $("#exceptionList").innerHTML = exceptions.length
    ? exceptions
        .slice(0, 10)
        .map(
          (r) =>
            `<div class="exception-card">
              <strong>#${r.id} ${r.account_name || r.summary}</strong>
              <div class="status">${r.exception_reason}</div>
            </div>`
        )
        .join("")
    : '<div class="detail-empty">✅ 暂无异常记录</div>';
}

/* ===== Export ===== */
const exportHistoryKey = 'audit_export_history';

function getExportHistory() {
  try { return JSON.parse(localStorage.getItem(exportHistoryKey) || '[]'); }
  catch { return []; }
}

function addExportHistory(entry) {
  const history = getExportHistory();
  history.unshift({ ...entry, time: new Date().toLocaleString() });
  if (history.length > 50) history.length = 50;
  localStorage.setItem(exportHistoryKey, JSON.stringify(history));
  renderExportHistory();
}

function clearExportHistory() {
  localStorage.removeItem(exportHistoryKey);
  renderExportHistory();
}

function renderExportHistory() {
  const history = getExportHistory();
  const el = $("#exportHistory");
  if (!history.length) {
    el.innerHTML = '<div class="detail-empty">暂无导出记录</div>';
    return;
  }
  el.innerHTML = history.map(h => `
    <div class="export-history-item">
      <div class="eh-left">
        <span class="eh-task">任务 #${h.taskId} · ${h.format}</span>
        <span class="eh-meta">${h.time} · ${h.filename || '-'}</span>
      </div>
      <span class="badge ok">✅ 成功</span>
    </div>
  `).join('');
}

async function loadCompletedTasks() {
  try {
    const tasks = await api("/api/tasks");
    const completed = tasks.filter(t => t.status === "completed");
    const select = $("#exportTaskSelect");
    select.innerHTML = '<option value="">— 请选择任务 —</option>' +
      completed.map(t => `<option value="${t.id}">#${t.id} ${t.filename}</option>`).join('');
    return completed;
  } catch { return []; }
}

let currentExportFormat = 'excel';

async function handleExport() {
  const taskId = $("#exportTaskSelect").value;
  const format = currentExportFormat;
  if (!taskId) {
    $("#exportHint").textContent = "⚠️ 请先选择一个已完成任务";
    return;
  }
  const btn = $("#exportBtn");
  btn.disabled = true;
  btn.textContent = '⏳ 导出中...';
  try {
    const resp = await fetch(`/api/export/${taskId}?format=${format}`);
    if (!resp.ok) throw new Error(await resp.text());
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const disposition = resp.headers.get('content-disposition') || '';
    const match = disposition.match(/filename="?(.+?)"?$/);
    a.download = match ? match[1] : `export_${taskId}.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    $("#exportHint").textContent = `✅ 任务 #${taskId} 的 ${format} 已导出`;
    addExportHistory({ taskId, format, filename: a.download });
  } catch (err) {
    $("#exportHint").textContent = `❌ 导出失败：${err.message}`;
  }
  btn.disabled = false;
  btn.textContent = '📥 开始导出';
}

/* ===== Settings ===== */
const settingsKey = 'audit_settings';
const defaultSettings = {
  ocrEngine: 'paddleocr',
  ocrLangs: 'ch,en',
  ocrConf: '0.5',
  ocrModelDir: './models/paddleocr',
  exportDir: './storage/exports',
  logLevel: 'INFO',
  defaultFormat: 'excel',
};

function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(settingsKey) || '{}');
    return { ...defaultSettings, ...saved };
  } catch { return { ...defaultSettings }; }
}

function applySettingsToUI() {
  const s = loadSettings();
  const map = {
    setOcrEngine: s.ocrEngine,
    setOcrLangs: s.ocrLangs,
    setOcrConf: s.ocrConf,
    setOcrModelDir: s.ocrModelDir,
    setExportDir: s.exportDir,
    setLogLevel: s.logLevel,
    setDefaultFormat: s.defaultFormat,
  };
  Object.entries(map).forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el) el.value = val;
  });
}

function saveSettingsToUI() {
  const s = {
    ocrEngine: $("#setOcrEngine").value,
    ocrLangs: $("#setOcrLangs").value,
    ocrConf: $("#setOcrConf").value,
    ocrModelDir: $("#setOcrModelDir").value,
    exportDir: $("#setExportDir").value,
    logLevel: $("#setLogLevel").value,
    defaultFormat: $("#setDefaultFormat").value,
  };
  localStorage.setItem(settingsKey, JSON.stringify(s));
  const hint = $("#settingsHint");
  hint.textContent = '✅ 设置已保存至本地';
  hint.style.color = 'var(--success)';
  setTimeout(() => { hint.textContent = ''; }, 3000);
  return s;
}

function resetSettings() {
  localStorage.setItem(settingsKey, JSON.stringify(defaultSettings));
  applySettingsToUI();
  const hint = $("#settingsHint");
  hint.textContent = '↩️ 已恢复默认设置';
  hint.style.color = 'var(--text-secondary)';
  setTimeout(() => { hint.textContent = ''; }, 3000);
}

async function loadSystemInfo() {
  try {
    await api("/api/health");
    $("#sysBackendStatus").textContent = '✅ 运行中';
    $("#sysBackendStatus").style.color = 'var(--success)';
  } catch {
    $("#sysBackendStatus").textContent = '❌ 不可用';
    $("#sysBackendStatus").style.color = 'var(--danger)';
  }
  try {
    const ocr = await api("/api/ocr/check");
    const isReady = ocr.paddleocr_installed && !ocr.paddleocr_import_error;
    $("#sysOcrStatus").textContent = isReady ? `✅ ${ocr.ocr_engine || 'PaddleOCR'}` : '⚠️ 未就绪';
    $("#sysOcrStatus").style.color = isReady ? 'var(--success)' : 'var(--accent)';
  } catch {
    $("#sysOcrStatus").textContent = '❌ 检测失败';
    $("#sysOcrStatus").style.color = 'var(--danger)';
  }
  try {
    const tasks = await api("/api/tasks");
    $("#sysTaskCount").textContent = tasks.length;
    const records = await api("/api/records?page=1&page_size=1");
    $("#sysRecordCount").textContent = records.total;
  } catch {}
}

/* ===== Events ===== */
function bindEvents() {
  $$(".nav-item").forEach((el) =>
    el.addEventListener("click", () => switchView(el.dataset.view))
  );
  $$("[data-jump]").forEach((el) =>
    el.addEventListener("click", () => switchView(el.dataset.jump))
  );

  $("#refreshTasksBtn").addEventListener("click", refreshDashboard);
  $("#reloadTaskListBtn").addEventListener("click", loadTasks);
  $("#rerunTaskBtn").addEventListener("click", () => state.selectedTaskId && runTask(state.selectedTaskId));
  $("#fileInput").addEventListener("change", (e) => uploadFiles(e.target.files));
  $("#dropZone").addEventListener("dragover", (e) => e.preventDefault());
  $("#dropZone").addEventListener("drop", (e) => {
    e.preventDefault();
    uploadFiles(e.dataTransfer.files);
  });

  $("#searchBtn").addEventListener("click", () => {
    state.recordPage = 1;
    loadRecords();
  });
  // Enter 键在筛选输入框触发查询
  $$("#startDate, #endDate, #accountFilter, #voucherFilter, #minAmount").forEach(el => {
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        state.recordPage = 1;
        loadRecords();
      }
    });
  });
  $("#prevPage").addEventListener("click", () => {
    if (state.recordPage > 1) { state.recordPage--; loadRecords(); }
  });
  $("#nextPage").addEventListener("click", () => {
    if (state.recordPage * state.pageSize < state.recordsTotal) { state.recordPage++; loadRecords(); }
  });
  // 页数输入跳转
  $("#pageInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") goToPage(parseInt(e.target.value, 10));
  });
  $("#pageInput").addEventListener("blur", (e) => {
    goToPage(parseInt(e.target.value, 10));
  });
  // 每页条数切换
  $("#pageSizeSelect").addEventListener("change", (e) => {
    state.pageSize = parseInt(e.target.value, 10);
    state.recordPage = 1;
    loadRecords();
  });

  $$("[data-export]").forEach((el) =>
    el.addEventListener("click", () => exportTask(el.dataset.export))
  );
  $("#closeDrawer").addEventListener("click", closeDrawer);
  $("#drawerOverlay").addEventListener("click", closeDrawer);

  // Export format selection
  $$(".format-option").forEach(el => {
    el.addEventListener("click", () => {
      $$(".format-option").forEach(o => o.classList.remove("active"));
      el.classList.add("active");
      currentExportFormat = el.dataset.format;
    });
  });
  $("#exportBtn").addEventListener("click", handleExport);
  $("#clearExportHistoryBtn").addEventListener("click", clearExportHistory);

  // Settings
  $("#saveSettingsBtn").addEventListener("click", saveSettingsToUI);
  $("#resetSettingsBtn").addEventListener("click", resetSettings);
}

function switchToExports() {
  loadCompletedTasks();
  renderExportHistory();
}

// Patch switchView to load exports/settings data
const origSwitchView = switchView;
switchView = function(name) {
  origSwitchView(name);
  if (name === "exports") {
    loadCompletedTasks();
    renderExportHistory();
  }
  if (name === "settings") {
    applySettingsToUI();
    loadSystemInfo();
  }
};

/* ===== Init ===== */
bindEvents();
checkHealth();
refreshDashboard();
setInterval(checkHealth, 15000);
setInterval(() => {
  if ($("#dashboard").classList.contains("active") || $("#tasks").classList.contains("active"))
    loadTasks();
}, 5000);


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
  analysis: ["分析看板", "月度趋势、科目分布、异常统计与金额区间可视化"],
  sampling: ["审计抽样", "随机抽样、分层抽样、大额抽样并导出结果"],
  ai: ["AI 助手", "语义搜索 · 智能问答 · 审计建议"],
  workflows: ["自动审计", "一键执行多步骤审计流程与底稿生成"],
  exports: ["导出中心", "导出 Excel、简易 XBRL、Word 报告或校验报告"],
  settings: ["系统设置", "配置本地 OCR、输出目录、日志策略与科目分类器"],
};

/* ===== DOM Helpers ===== */
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

/* ===== Formatting ===== */
function money(v) {
  return Number(v || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ===== API ===== */
const AI_API_KEY = "audit-platform-key";

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `HTTP ${r.status}`);
  }
  return r.headers.get("content-type")?.includes("application/json") ? r.json() : r;
}

async function aiApi(path, opts = {}) {
  opts.headers = opts.headers || {};
  opts.headers["Authorization"] = `Bearer ${AI_API_KEY}`;
  return api(path, opts);
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
  if (name === "analysis") loadAnalysis();
  if (name === "sampling") loadSamplingTasks();
  if (name === "ai") { checkAiHealth(); loadAiIndexStatus(); }
  if (name === "workflows") { loadWorkflowTasks(); refreshWfStats(); }
  if (name === "settings") { applySettingsToUI(); loadSystemInfo(); loadClassifierStatus(); }
  if (name === "exports") { loadCompletedTasks(); renderExportHistory(); }
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

  // Analysis
  $("#refreshAnalysisBtn").addEventListener("click", loadAnalysis);

  // Sampling
  $("#sampMethod").addEventListener("change", onSampMethodChange);
  $("#sampleBtn").addEventListener("click", doSample);
  $("#exportSampleBtn").addEventListener("click", exportSample);
}

/* ===== Analysis ===== */
const chartInstances = {};

function destroyCharts() {
  Object.values(chartInstances).forEach(c => { try { c.destroy(); } catch {} });
  Object.keys(chartInstances).forEach(k => delete chartInstances[k]);
}

async function loadAnalysis() {
  if (!$("#analysis").classList.contains("active")) return;
  try {
    const data = await api("/api/analysis/full");
    destroyCharts();
    $("#analysisHint").textContent = `数据加载于 ${new Date().toLocaleTimeString()}`;

    renderTrendChart(data.monthly_trend || []);
    renderAccountPie(data.account_distribution || []);
    renderExceptionChart(data.exception_distribution || {});
    renderAmountHist(data.amount_distribution || []);
    renderAnalysisStats(data.task_statistics || {}, data.exception_distribution || {});
  } catch (err) {
    $("#analysisHint").textContent = `⚠️ 加载失败: ${err.message}`;
    $("#analysisStats").innerHTML = "";
  }
}

function renderTrendChart(data) {
  const ctx = $("#trendChart")?.getContext("2d");
  if (!ctx) return;
  chartInstances.trend = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.map(d => d.month),
      datasets: [
        { label: "借方", data: data.map(d => d.debit), borderColor: "#059669", backgroundColor: "rgba(5,150,105,0.1)", fill: true, tension: 0.3 },
        { label: "贷方", data: data.map(d => d.credit), borderColor: "#d97706", backgroundColor: "rgba(217,119,6,0.1)", fill: true, tension: 0.3 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom" } },
      scales: { y: { beginAtZero: true } },
    },
  });
}

function renderAccountPie(data) {
  const ctx = $("#accountPie")?.getContext("2d");
  if (!ctx) return;
  const top10 = data.slice(0, 10);
  chartInstances.account = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: top10.map(d => d.account_name || d.account_code),
      datasets: [{ data: top10.map(d => d.total_debit), backgroundColor: ["#0f6e8a","#059669","#d97706","#dc2626","#4338ca","#7c3aed","#0891b2","#65a30d","#ca8a04","#e11d48"] }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "right", labels: { font: { size: 10 } } } },
    },
  });
}

function renderExceptionChart(data) {
  const ctx = $("#exceptionChart")?.getContext("2d");
  if (!ctx) return;
  const breakdown = data.breakdown || [];
  chartInstances.exception = new Chart(ctx, {
    type: "bar",
    data: {
      labels: breakdown.map(d => d.reason.length > 12 ? d.reason.slice(0,12)+"…" : d.reason),
      datasets: [{ label: "异常数", data: breakdown.map(d => d.count), backgroundColor: "#f97316" }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true, ticks: { stepSize: 1 } } },
    },
  });
}

function renderAmountHist(data) {
  const ctx = $("#amountHist")?.getContext("2d");
  if (!ctx) return;
  chartInstances.amount = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.map(d => d.range),
      datasets: [{ label: "记录数", data: data.map(d => d.count), backgroundColor: "#0f6e8a" }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true } },
    },
  });
}

function renderAnalysisStats(taskStats, excStats) {
  $("#analysisStats").innerHTML = `
    <div class="stat-mini"><span class="sm-num">${taskStats.total_tasks || 0}</span><span class="sm-label">总任务数</span></div>
    <div class="stat-mini"><span class="sm-num">${taskStats.completed || 0}</span><span class="sm-label">已完成</span></div>
    <div class="stat-mini"><span class="sm-num" style="color:var(--danger)">${excStats.total_exceptions || 0}</span><span class="sm-label">总异常数</span></div>
  `;
}

/* ===== Sampling ===== */
let lastSampleResult = [];

function onSampMethodChange() {
  const method = $("#sampMethod").value;
  $("#sampSizeLabel").textContent = method === "large" ? "最大返回数" : "样本数量";
  $("#sampThresholdGroup").style.display = method === "large" ? "grid" : "none";
}

async function loadSamplingTasks() {
  if (!$("#sampling").classList.contains("active")) return;
  try {
    const tasks = await api("/api/tasks");
    const completed = tasks.filter(t => t.status === "completed");
    $("#sampTaskSelect").innerHTML = '<option value="">全部任务</option>' +
      completed.map(t => `<option value="${t.id}">#${t.id} ${t.filename}</option>`).join('');
  } catch {}
}

async function doSample() {
  const method = $("#sampMethod").value;
  const taskId = $("#sampTaskSelect").value;
  const exception = $("#sampException").value;
  const params = new URLSearchParams();
  if (taskId) params.set("task_id", taskId);
  if (exception) params.set("is_exception", exception);

  let url;
  if (method === "random") {
    params.set("sample_size", $("#sampSize").value || 20);
    url = `/api/sampling/random?${params}`;
  } else if (method === "stratified") {
    params.set("sample_size", $("#sampSize").value || 20);
    params.set("stratify_by", "account_code");
    url = `/api/sampling/stratified?${params}`;
  } else {
    params.set("threshold", $("#sampThreshold").value || 10000);
    params.set("sample_size", $("#sampSize").value || 50);
    url = `/api/sampling/large?${params}`;
  }

  try {
    lastSampleResult = await api(url);
    $("#sampleCount").textContent = `${lastSampleResult.length} 条`;
    renderSampleResults(lastSampleResult);
  } catch (err) {
    $("#sampleResults").innerHTML = `<div class="detail-empty">❌ ${err.message}</div>`;
    $("#sampleCount").textContent = "0 条";
  }
}

function renderSampleResults(items) {
  if (!items.length) {
    $("#sampleResults").innerHTML = '<div class="detail-empty">无匹配结果</div>';
    return;
  }
  $("#sampleResults").innerHTML = items.map((r, i) => `
    <div class="sample-result-card">
      <div class="samp-top">
        <strong>#${r.id} ${r.account_name || ""}</strong>
        <span class="badge ${r.is_exception ? 'warn' : 'ok'}">${r.is_exception ? '异常' : '正常'}</span>
      </div>
      <div>${r.date} · ${r.voucher_no} · ${r.summary ? r.summary.slice(0,40) : ''}</div>
      <div>借 ¥${money(r.debit)} / 贷 ¥${money(r.credit)}</div>
      <div class="samp-meta">方法: ${r.sampling_method}</div>
    </div>
  `).join('');
}

async function exportSample() {
  if (!lastSampleResult.length) {
    alert("请先执行抽样");
    return;
  }
  const method = $("#sampMethod").value;
  const params = new URLSearchParams({ method, sample_size: $("#sampSize").value || 20, fmt: "excel" });
  if (method === "large") params.set("threshold", $("#sampThreshold").value || 10000);
  const taskId = $("#sampTaskSelect").value;
  if (taskId) params.set("task_id", taskId);

  try {
    const resp = await fetch(`/api/sampling/export?${params}`);
    if (!resp.ok) throw new Error(await resp.text());
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `sampling_${new Date().toISOString().slice(0,10)}.xlsx`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    alert(`导出失败: ${err.message}`);
  }
}

/* ===== Classifier Status in Settings ===== */
async function loadClassifierStatus() {
  try {
    const status = await api("/api/accounts/classifier/status");
    const hint = $("#settingsHint");
    if (status.exists) {
      hint.textContent = `✅ ML分类器已训练 · ${status.samples} 样本 · 准确率 ${(status.accuracy*100).toFixed(1)}% · ${status.classes?.length || 0} 个科目`;
      hint.style.color = "var(--success)";
    } else {
      hint.textContent = `⚠️ ML分类器未训练 · 回退关键词匹配(${status.keyword_map_size}条) · 可在已处理任务后自动训练`;
      hint.style.color = "var(--accent)";
    }
  } catch {}
}

/* ===== Init ===== */
bindEvents();
bindAiEvents();
bindWorkflowEvents();
checkHealth();
refreshDashboard();
setInterval(checkHealth, 15000);
setInterval(() => {
  if ($("#dashboard").classList.contains("active") || $("#tasks").classList.contains("active"))
    loadTasks();
}, 5000);

/* ==================== AI 助手 ==================== */

async function checkAiHealth() {
  try {
    const h = await api("/api/ai/health");
    if (h.rag && h.rag.llm_configured) {
      $("#aiModelBadge").textContent = `🤖 ${h.rag.llm_model || 'AI'} 已连接`;
      $("#aiModelBadge").style.background = "var(--success-light)";
      $("#aiModelBadge").style.color = "var(--success)";
    } else {
      $("#aiModelBadge").textContent = "📦 本地模式";
    }
  } catch {
    $("#aiModelBadge").textContent = "⚠️ 未连接";
    $("#aiModelBadge").style.background = "var(--danger-light)";
    $("#aiModelBadge").style.color = "var(--danger)";
  }
}

async function loadAiIndexStatus() {
  try {
    const s = await api("/api/ai/index/status");
    if (s.store) {
      $("#aiIndexCount").textContent = `${s.store.total_vectors} 条`;
      $("#aiIndexDim").textContent = s.store.dimension;
    }
  } catch {
    $("#aiIndexCount").textContent = "不可用";
    $("#aiIndexDim").textContent = "--";
  }
}

function addAiMessage(role, html) {
  const msgs = $("#aiChatMessages");
  const div = document.createElement("div");
  div.className = `ai-msg ai-msg-${role}`;
  div.innerHTML = `<div class="ai-msg-avatar">${role === "user" ? "👤" : "🤖"}</div><div class="ai-msg-bubble">${html}</div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function renderAiResult(data) {
  if (!data) return;
  if (data.answer) {
    let html = `<div class="ai-answer">${markedText(data.answer)}</div>`;
    if (data.sources && data.sources.length) {
      html += `<div class="ai-sources"><strong>📎 参考来源 (${data.sources.length} 条):</strong>`;
      data.sources.forEach((s) => {
        html += `<div class="ai-source-item">
          <span class="ai-source-score">${(s.score * 100).toFixed(0)}%</span>
          <span class="ai-source-text">${s.text || ""}</span>
          ${s.metadata?.account_code ? `<span class="ai-source-meta">科目: ${s.metadata.account_code} ${s.metadata.account_name || ""}</span>` : ""}
        </div>`;
      });
      html += `</div>`;
    }
    if (data.model) html += `<div class="ai-model-info">模型: ${data.model}</div>`;
    $("#aiResults").innerHTML = html;
    $("#aiResultTitle").textContent = "💬 回答";
    return;
  }
  if (data.results) {
    let html = `<p class="ai-search-summary">找到 ${data.total} 条相关记录</p>`;
    data.results.forEach((r) => {
      html += `<div class="ai-source-item">
        <span class="ai-source-score">${(r.score * 100).toFixed(0)}%</span>
        <span class="ai-source-text">${r.text || ""}</span>
        ${r.metadata?.account_code ? `<span class="ai-source-meta">科目: ${r.metadata.account_code} ${r.metadata.account_name || ""} | 凭证: ${r.metadata.voucher_no || ""}</span>` : ""}
      </div>`;
    });
    $("#aiResults").innerHTML = html;
    $("#aiResultTitle").textContent = "🔍 搜索结果";
    return;
  }
  if (data.findings) {
    let html = `<p class="ai-search-summary">${data.summary || ""}</p>`;
    const cats = [
      { key: "large_amounts", label: "💰 大额交易", color: "var(--danger)" },
      { key: "unusual_accounts", label: "📊 异常科目", color: "var(--accent)" },
      { key: "missing_vouchers", label: "📋 凭证缺失", color: "#f59e0b" },
      { key: "duplicate_vouchers", label: "🔄 重复凭证", color: "var(--primary)" },
      { key: "semantic_similar", label: "🔗 语义相似异常", color: "#8b5cf6" },
    ];
    cats.forEach((cat) => {
      const items = data.findings[cat.key] || [];
      if (items.length) {
        html += `<div class="ai-finding-group"><strong style="color:${cat.color}">${cat.label} (${items.length})</strong>`;
        items.slice(0, 5).forEach((f) => html += `<div class="ai-finding-item">${f.message || f.type}</div>`);
        if (items.length > 5) html += `<div class="ai-finding-item">... 还有 ${items.length - 5} 条</div>`;
        html += `</div>`;
      }
    });
    if (data.summary && data.summary.length > 200) html += `<div class="ai-answer"><strong>📝 AI 摘要:</strong><br/>${markedText(data.summary)}</div>`;
    $("#aiResults").innerHTML = html || "<div class='detail-empty'>未发现审计线索</div>";
    $("#aiResultTitle").textContent = "⚠️ 审计建议";
    return;
  }
}

function markedText(text) {
  return String(text || "").replace(/\n/g, "<br/>").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
}

async function handleAiSend() {
  const input = $("#aiInput");
  const mode = $("#aiMode").value;
  const question = input.value.trim();
  if (!question) return;
  addAiMessage("user", `<p>${question}</p>`);
  input.value = "";
  const loadingDiv = addAiMessage("assistant", '<p class="ai-loading">⏳ 分析中...</p>');
  $("#aiResults").innerHTML = '<div class="detail-empty">⏳ 处理中...</div>';
  try {
    let data;
    if (mode === "search") {
      data = await aiApi("/api/ai/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: question, top_k: 10 }) });
      loadingDiv.querySelector(".ai-msg-bubble").innerHTML = `<p>🔍 搜索完成，找到 ${data.total || 0} 条结果</p>`;
    } else if (mode === "qa") {
      data = await aiApi("/api/ai/qa", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, top_k: 10, use_llm: true }) });
      loadingDiv.querySelector(".ai-msg-bubble").innerHTML = data.answer ? `<p>${data.answer.substring(0, 300)}...</p><small>（详见右侧面板）</small>` : `<p>⚠️ 未能生成回答</p>`;
    } else if (mode === "suggestions") {
      data = await aiApi("/api/ai/suggestions");
      loadingDiv.querySelector(".ai-msg-bubble").innerHTML = `<p>⚠️ 审计建议已生成，共 ${data.total_findings || 0} 项发现</p>`;
    }
    renderAiResult(data);
  } catch (err) {
    loadingDiv.querySelector(".ai-msg-bubble").innerHTML = `<p style="color:var(--danger)">❌ 请求失败: ${err.message}</p>`;
    addAiMessage("system", `<p>💡 提示：请确保已上传数据并触发索引</p>`);
  }
  loadAiIndexStatus();
}

async function handleAiRefreshIndex() {
  try {
    await aiApi("/api/ai/index", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ force: false, include_images: true }) });
    addAiMessage("system", "<p>🔄 索引已触发，请稍候刷新状态</p>");
    setTimeout(loadAiIndexStatus, 2000);
  } catch (err) { addAiMessage("system", `<p style="color:var(--danger)">索引失败: ${err.message}</p>`); }
}

async function handleAiReindex() {
  if (!confirm("确定要全量重建 AI 索引吗？")) return;
  try {
    await aiApi("/api/ai/index/reindex-all", { method: "POST" });
    addAiMessage("system", "<p>🔧 全量重建完成</p>");
    loadAiIndexStatus();
  } catch (err) { addAiMessage("system", `<p style="color:var(--danger)">重建失败: ${err.message}</p>`); }
}

/* ==================== 自动审计工作流 v2 ==================== */

async function refreshWfStats() {
  try {
    const tasks = await api("/api/tasks");
    const completed = tasks.filter(t => t.status === "completed").length;
    $("#wfCompletedCount").textContent = completed;
  } catch { $("#wfCompletedCount").textContent = "--"; }
}

async function loadWorkflowTasks() {
  try {
    const tasks = await api("/api/tasks");
    const completed = tasks.filter(t => t.status === "completed");
    const sel = $("#wfTaskSelect");
    sel.innerHTML = '<option value="">— 请选择已处理的任务 —</option>' +
      completed.map(t => `<option value="${t.id}">#${t.id} ${t.filename}</option>`).join("");

    // 存储任务数据供预览使用
    sel._tasks = tasks;
    sel.onchange = () => showTaskPreview(tasks);
  } catch (err) {
    console.error("加载任务列表失败", err);
  }
}

function showTaskPreview(tasks) {
  const taskId = parseInt($("#wfTaskSelect").value);
  if (!taskId) { $("#wfTaskPreview").style.display = "none"; return; }
  const t = tasks.find(x => x.id === taskId);
  if (!t) return;
  $("#wfPreviewName").textContent = `#${t.id} ${t.filename}`;
  $("#wfPreviewMeta").textContent = `${badgeText(t.status)} · ${t.current_step || ""}`;
  $("#wfTaskPreview").style.display = "block";
  // Enable jump
  $("#wfJumpToTask").onclick = () => {
    selectTask(taskId);
    switchView("tasks");
  };
}

function badgeText(status) {
  const m = { pending: "待处理", queued: "排队中", running: "处理中", completed: "已完成", failed: "失败" };
  return m[status] || status;
}

function getWfType() {
  const checked = document.querySelector('input[name="wfType"]:checked');
  return checked ? checked.value : "quick_scan";
}

// ── 进度条 ─────────────────────────────────────────────
function showWfProgress(text, pct) {
  $("#wfProgressBar").style.display = "block";
  $("#wfProgressFill").style.width = `${pct}%`;
  $("#wfProgressText").textContent = text;
}
function hideWfProgress() {
  $("#wfProgressBar").style.display = "none";
}

// ── 执行工作流 ─────────────────────────────────────────
async function runWorkflow() {
  const taskId = $("#wfTaskSelect").value;
  const wfType = getWfType();
  if (!taskId) { alert("请先选择任务"); return; }

  $("#workflowResults").innerHTML = "";
  $("#wfResultTitle").textContent = "⏳ 执行中...";
  $("#runWorkflowBtn").disabled = true;
  $("#wfCollapseAll").style.display = "none";
  $("#exportWfResultBtn").style.display = "none";
  showWfProgress("初始化审计工作流...", 5);

  try {
    // Simulate progress steps
    const progressSteps = ["检索数据中...", "执行异常检测...", "AI 分析中...", "生成报告..."];
    let stepIdx = 0;
    const progressInterval = setInterval(() => {
      if (stepIdx < progressSteps.length) {
        showWfProgress(progressSteps[stepIdx], 20 + stepIdx * 20);
        stepIdx++;
      }
    }, 1500);

    const data = await aiApi("/api/ai/workflows/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workflow_name: wfType, task_id: parseInt(taskId), use_ai_summary: true }),
    });

    clearInterval(progressInterval);
    showWfProgress("审计完成 ✓", 100);
    setTimeout(hideWfProgress, 2000);

    // ── 构建结果 HTML ──
    let html = "";

    // 头部信息
    const wfLabels = {
      quick_scan: "🔍 快速扫描", full_audit: "📋 全面审计", ar_audit: "💰 应收账款专项",
      ap_audit: "💳 应付账款专项", revenue_audit: "📈 收入确认专项", expense_audit: "🧾 费用报销专项",
      four_way: "🔗 四联动核验", multi_perspective: "👁️ 多视角审计"
    };
    html += `<div class="wf-result-header">
      <span class="wf-result-icon">✅</span>
      <div>
        <strong>${wfLabels[wfType] || data.workflow}</strong>
        <small>${data.filename || ""} · ${data.description || ""}</small>
      </div>
    </div>`;

    // 步骤卡片（可展开）
    if (data.steps) {
      data.steps.forEach((s, i) => {
        const hasErr = !!s.error;
        const icon = hasErr ? "❌" : (s.skipped ? "⏭️" : "✅");
        const cls = hasErr ? "err" : "ok";
        const stepId = `wf-step-${i}`;

        // 构建摘要
        let summary = "";
        if (s.total_findings) summary = `发现 <b>${s.total_findings}</b> 条`;
        else if (s.total) summary = `<b>${s.total}</b> 条记录`;
        else if (s.duplicates) summary = `<b>${s.duplicates.length}</b> 项重复`;
        else if (s.balanced !== undefined) summary = s.balanced ? "✅ 平衡" : `⚠️ 差额 ¥${s.diff}`;
        else if (s.score) summary = `质量评分 <b>${s.score}</b>`;
        else if (s.analysis) summary = s.analysis.substring(0, 60) + "...";
        else summary = "完成";

        // 构建详细内容
        let detail = "";
        if (s.top_accounts) {
          detail = '<div class="wf-detail-table"><table><tr><th>科目</th><th>借方</th><th>贷方</th><th>笔数</th></tr>' +
            s.top_accounts.slice(0, 5).map(a =>
              `<tr class="wf-clickable" data-jump="records" data-account="${a.code}"><td>${a.code} ${a.name}</td><td>¥${a.debit.toLocaleString()}</td><td>¥${a.credit.toLocaleString()}</td><td>${a.count}</td></tr>`
            ).join("") + "</table></div>";
        }
        if (s.top5) {
          detail = '<div class="wf-detail-list">' +
            s.top5.map(f => `<div class="wf-detail-item" data-jump="records" data-voucher="${f.voucher_no || ''}"><span class="wf-sev wf-sev-${f.severity || '低'}">${f.severity || '-'}</span> ${f.message || f.type || ''}</div>`).join("") +
            "</div>";
        }
        if (s.analysis) {
          detail = `<div class="wf-detail-text">${markedText(s.analysis)}</div>`;
        }

        html += `<div class="wf-step-card ${cls}" id="${stepId}">
          <div class="wf-step-icon ${cls}">${icon}</div>
          <div class="wf-step-body">
            <div class="wf-step-head" onclick="toggleWfStep('${stepId}')">
              <strong>步骤${i+1}: ${s.step || "未知"}</strong>
              <span class="wf-step-summary">${summary}</span>
              <span class="wf-step-arrow">▾</span>
            </div>
            <div class="wf-step-detail-content" style="display:none">${detail}</div>
          </div>
        </div>`;
      });
    }

    // AI 汇总
    if (data.ai_summary) {
      html += `<div class="wf-ai-summary">
        <div class="wf-ai-summary-head">🤖 AI 审计结论</div>
        <div class="wf-ai-summary-body">${markedText(data.ai_summary)}</div>
      </div>`;
    }

    // 风险评级
    const riskStep = (data.steps || []).find(s => s.risk_level);
    if (riskStep) {
      const lvl = riskStep.risk_level;
      const cls = lvl === "高" ? "wf-risk-high" : lvl === "中" ? "wf-risk-mid" : "wf-risk-low";
      html += `<div class="wf-risk-row">
        <span class="wf-risk-badge ${cls}">🎯 ${lvl}风险</span>
        <span class="wf-risk-detail">评分 ${riskStep.risk_score}/100 · 异常率 ${riskStep.exception_rate}%</span>
        <span class="wf-risk-detail">高严重度 ${riskStep.high_severity_count || 0} 项</span>
      </div>`;
    }

    // 证据链
    if (data.evidence_chain && data.evidence_chain.length) {
      html += `<div class="wf-evidence-section">
        <div class="wf-section-head" onclick="this.nextElementSibling.classList.toggle('hidden')">
          📎 证据链 (${data.evidence_chain.length} 条) <span class="wf-section-arrow">▾</span>
        </div>
        <div class="wf-section-body">`;
      data.evidence_chain.slice(0, 10).forEach(e => {
        html += `<div class="wf-evidence-item" data-record-id="${e.record_id}" onclick="viewRecordDetail(${e.record_id})" title="点击查看记录详情">
          <span class="wf-ev-voucher">${e.voucher_no || '-'}</span>
          <span class="wf-ev-account">${e.account}</span>
          <span class="wf-ev-amount">¥${(e.debit || e.credit || 0).toFixed(2)}</span>
          <span class="wf-ev-arrow">→</span>
        </div>`;
      });
      html += `</div></div>`;
    }

    // 审计追溯
    if (data.audit_trail) {
      html += `<div class="wf-evidence-section">
        <div class="wf-section-head" onclick="this.nextElementSibling.classList.toggle('hidden')">
          🔍 审计追溯 <span class="wf-section-arrow">▾</span>
        </div>
        <div class="wf-section-body hidden">
          <div class="wf-trail-info">
            <span>操作 <b>${data.audit_trail.total_operations || 0}</b> 次</span>
            <span>工具: ${(data.audit_trail.tools_used || ['--']).join(', ')}</span>
            <span>证据 <b>${data.audit_trail.evidence_count || 0}</b> 条</span>
          </div>
        </div>
      </div>`;
    }

    // 二次校验
    if (data.secondary_review) {
      html += `<div class="wf-ai-summary wf-review">
        <div class="wf-ai-summary-head">🔍 质量复核</div>
        <div class="wf-ai-summary-body">${markedText(data.secondary_review.review_result || '')}</div>
      </div>`;
    }

    // 快捷操作
    html += `<div class="wf-quick-actions">
      <button class="btn btn-ghost btn-sm" onclick="switchView('tasks');selectTask(${taskId})">📋 查看任务详情</button>
      <button class="btn btn-ghost btn-sm" onclick="switchView('records');$('#accountFilter').value='1122';document.getElementById('searchBtn').click()">📑 查看相关数据</button>
      <button class="btn btn-ghost btn-sm" onclick="switchView('ai');$('#aiInput').value='请分析任务${taskId}的审计结果';$('#aiMode').value='qa'">🤖 AI 深度追问</button>
    </div>`;

    $("#workflowResults").innerHTML = html;
    $("#wfResultTitle").textContent = "✅ 审计完成";
    $("#wfCollapseAll").style.display = "inline-block";
    $("#exportWfResultBtn").style.display = "inline-block";

    // 绑定详情点击跳转
    bindWfDetailClicks();

  } catch (err) {
    hideWfProgress();
    $("#workflowResults").innerHTML = `<div class="wf-empty-state" style="color:var(--danger)">
      <div class="wf-empty-icon">❌</div>
      <strong>执行失败</strong>
      <p>${err.message}</p>
      <button class="btn btn-ghost btn-sm" onclick="switchView('tasks')">📋 检查任务状态</button>
    </div>`;
    $("#wfResultTitle").textContent = "❌ 执行失败";
  } finally {
    $("#runWorkflowBtn").disabled = false;
  }
}

// ── 交互 ───────────────────────────────────────────────
function toggleWfStep(id) {
  const card = document.getElementById(id);
  if (!card) return;
  const detail = card.querySelector(".wf-step-detail-content");
  const arrow = card.querySelector(".wf-step-arrow");
  if (detail) {
    const isHidden = detail.style.display === "none";
    detail.style.display = isHidden ? "block" : "none";
    if (arrow) arrow.style.transform = isHidden ? "rotate(180deg)" : "";
  }
}

function bindWfDetailClicks() {
  // 点击科目行跳转
  $$(".wf-clickable").forEach(el => {
    el.addEventListener("click", () => {
      const jump = el.dataset.jump;
      const account = el.dataset.account;
      if (jump === "records") {
        switchView("records");
        const af = $("#accountFilter");
        if (af && account) { af.value = account; document.getElementById("searchBtn")?.click(); }
      }
    });
  });
  // 点击异常项跳转
  $$(".wf-detail-item").forEach(el => {
    el.addEventListener("click", () => {
      const voucher = el.dataset.voucher;
      if (voucher) {
        switchView("records");
        const vf = $("#voucherFilter");
        if (vf) { vf.value = voucher; document.getElementById("searchBtn")?.click(); }
      }
    });
  });
}

function viewRecordDetail(recordId) {
  switchView("records");
  // Trigger record detail
  setTimeout(async () => {
    try {
      const r = await api(`/api/records/${recordId}`);
      openDrawer(r);
    } catch { /* ignore */ }
  }, 500);
}

// ── 底稿生成 ───────────────────────────────────────────
async function generateWorkpaper() {
  const taskId = $("#wfTaskSelect").value;
  if (!taskId) { alert("请先选择任务"); return; }

  $("#workflowResults").innerHTML = '<div class="wf-empty-state"><div class="wf-empty-icon">📝</div><strong>正在生成审计底稿...</strong><p>请稍候</p></div>';
  try {
    const data = await aiApi("/api/ai/workpapers/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: parseInt(taskId), format: "standard" }),
    });
    $("#workflowResults").innerHTML = `
      <div class="wf-result-header"><span class="wf-result-icon">📝</span><div><strong>审计底稿已生成</strong><small>${data.filename}</small></div></div>
      <div class="wf-quick-actions">
        <a class="btn btn-primary btn-sm" href="/storage/exports/${data.filename}" download>📥 下载 Word 文档</a>
        <button class="btn btn-ghost btn-sm" onclick="switchView('exports')">📦 前往导出中心</button>
      </div>`;
  } catch (err) {
    $("#workflowResults").innerHTML = `<div class="wf-empty-state" style="color:var(--danger)"><div class="wf-empty-icon">❌</div><strong>生成失败</strong><p>${err.message}</p></div>`;
  }
}

function exportWorkflowResult() {
  const taskId = $("#wfTaskSelect").value;
  if (!taskId) return;
  window.open(`/api/export/${taskId}?format=docx`, "_blank");
}

// ── 工作流类型卡片选择 ─────────────────────────────────
function bindWfTypeCards() {
  $$("#wfTypeCards .wf-type-card").forEach(card => {
    card.addEventListener("click", () => {
      $$("#wfTypeCards .wf-type-card").forEach(c => c.classList.remove("active"));
      card.classList.add("active");
      card.querySelector('input[type="radio"]').checked = true;
    });
  });
}

function bindWorkflowEvents() {
  $("#runWorkflowBtn")?.addEventListener("click", runWorkflow);
  $("#genWorkpaperBtn")?.addEventListener("click", generateWorkpaper);
  $("#exportWfResultBtn")?.addEventListener("click", exportWorkflowResult);
  $("#wfCollapseAll")?.addEventListener("click", () => {
    $$(".wf-step-detail-content").forEach(d => d.style.display = "none");
    $$(".wf-step-arrow").forEach(a => a.style.transform = "");
  });
  bindWfTypeCards();
}

function bindAiEvents() {
  $("#aiSendBtn")?.addEventListener("click", handleAiSend);
  $("#aiInput")?.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleAiSend(); } });
  $("#aiRefreshIndexBtn")?.addEventListener("click", handleAiRefreshIndex);
  $("#aiReindexBtn")?.addEventListener("click", handleAiReindex);
}

/* ===== 附加绑定 ===== */
bindAiEvents();
bindWorkflowEvents();


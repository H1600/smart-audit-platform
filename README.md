# 智能财务审计数据处理平台

一个可本地部署的财务审计数据处理工具，面向“上传文件 - 识别/解析 - 清洗标准化 - 勾稽校验 - 查询 - 导出”的完整闭环场景。项目采用 FastAPI 提供后端 API，前端使用原生 HTML/CSS/JavaScript 构建单页界面，默认数据落地到本地 SQLite 和文件目录，适合离线、内网或本地审计工作站使用。

## 这套系统能做什么

- 上传 PDF、图片、Excel、CSV 等财务文件并自动生成处理任务。
- 对表格文件直接解析，对 PDF 提取文本，对图片执行 OCR 识别。
- 将识别结果做字段归一化、科目映射和异常标记，写入本地数据库。
- 按日期、科目、凭证号、金额筛选结构化数据。
- 查看任务进度、处理日志和勾稽校验结果。
- 导出为 Excel、简易 XBRL 或校验报告。
- 在浏览器里查看系统状态、OCR 状态和导出历史。

## 技术栈

- 后端：FastAPI、Uvicorn
- 数据库：SQLite、SQLAlchemy
- 数据处理：pandas、openpyxl、PyPDF2、Pillow、csv、json
- OCR：PaddleOCR 优先，EasyOCR 作为回退；OCR 状态通过 `/api/ocr/check` 诊断
- 前端：原生 HTML、CSS、JavaScript
- 容器：Docker、docker compose
- 测试脚本：Python 烟雾测试脚本和 API OCR 验证脚本

## 项目界面

前端是一个单页应用，包含 6 个主要区域：

- 工作台：系统状态、统计卡片、最近任务、异常提醒
- 文件上传：拖拽或选择文件上传并自动创建任务
- 任务详情：任务队列、处理日志、勾稽校验
- 数据结果：结果筛选、分页表格、来源定位弹窗
- 导出中心：已完成任务选择、导出格式选择、导出历史
- 系统设置：OCR/输出/日志相关本地配置和系统信息

## 代码结构

- [backend/main.py](backend/main.py)：FastAPI 路由入口，提供健康检查、OCR 诊断、上传、任务、记录、报告和导出接口
- [backend/services.py](backend/services.py)：核心业务逻辑，负责 OCR、解析、标准化、校验和导出
- [backend/models.py](backend/models.py)：SQLite 数据表模型
- [backend/database.py](backend/database.py)：数据库连接与会话
- [backend/settings.py](backend/settings.py)：目录、OCR 和运行时配置
- [frontend/index.html](frontend/index.html)：页面结构
- [frontend/styles.css](frontend/styles.css)：页面样式
- [frontend/app.js](frontend/app.js)：页面交互和 API 调用
- [scripts/](scripts)：OCR 和接口烟雾测试脚本

## 快速启动

### 方式一：Docker 一键启动

```bash
docker compose up --build -d
```

启动后访问：

```text
http://127.0.0.1:8000
```

停止服务：

```bash
docker compose down
```

查看日志：

```bash
docker compose logs -f
```

### 方式二：本地 Python 启动

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\start.ps1
```

`start.ps1` 默认会在 `127.0.0.1:8000` 启动 Uvicorn，也可以传入端口：

```powershell
.\start.ps1 -Port 8001
```

如果你不想用脚本，也可以直接启动：

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Linux / macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

## 运行前说明

- 默认端口是 `8000`。
- 项目会自动创建 `data/`、`storage/`、`logs/`、`storage/uploads/`、`storage/exports/` 目录。
- 业务数据默认保存在本地 SQLite 文件中。
- 前端“系统设置”页保存的是浏览器本地配置，用于记录当前偏好，不会自动写回服务端环境变量。

## OCR 说明

后端 OCR 逻辑采用如下顺序：

1. `OCR_ENGINE=auto` 时优先尝试 PaddleOCR
2. PaddleOCR 不可用时，尝试 EasyOCR
3. 两者都不可用时，图片识别会退回到占位结果，任务仍可继续跑完

可用的环境变量如下：

- `OCR_ENGINE`：`auto`、`paddleocr`、`easyocr`、`off`
- `OCR_LANGS`：OCR 语言列表，默认 `zh,en`
- `OCR_MIN_CONF`：最小置信度阈值，默认 `0.55`
- `OCR_MODEL_DIR`：本地 OCR 模型目录，若存在 `det/rec/cls` 子目录会自动使用
- `OCR_TEXTLINE`：是否启用 PaddleOCR 文本行方向识别，默认开启

如果你在 Windows 本地启用真实 OCR，通常还需要单独安装 `paddleocr`，并确保 `torch` 的 DLL 依赖可正常加载。仓库中的 `scripts/check_paddleocr.py`、`scripts/ocr_test_standalone.py` 和 `scripts/api_ocr_test.py` 可用于验证 OCR 链路。

## 功能说明

### 工作台

- 显示部署模式、处理引擎和存储方式
- 显示待处理任务、已完成任务、结构化记录和异常记录统计
- 展示最近任务和异常提醒列表

### 文件上传

- 支持拖拽或选择文件上传
- 支持格式：`.pdf`、`.png`、`.jpg`、`.jpeg`、`.bmp`、`.tif`、`.tiff`、`.xlsx`、`.xls`、`.csv`
- 上传后自动创建任务并进入处理流程

### 任务详情

- 查看任务队列和当前状态
- 查看处理日志、进度和错误信息
- 查看勾稽校验结果
- 失败任务可以重新执行

### 数据结果

- 支持按日期、科目、凭证号、最小金额筛选
- 支持分页查看结构化记录
- 点击记录可以查看完整来源信息和 JSON 明细

### 导出中心

- 只能对已完成任务导出
- 支持导出 Excel、简易 XBRL 和校验报告
- 浏览器本地保存导出历史

### 系统设置

- 可在页面里调整 OCR 引擎、语言、阈值、模型路径、导出目录和日志级别等偏好
- 当前版本的设置主要保存在浏览器本地，用于界面记录和展示
- 右侧系统信息会显示后端状态、OCR 状态、数据库和统计信息

## API 接口

### 通用说明

- 基础地址通常是 `http://127.0.0.1:8000`，如果你用 `start.ps1 -Port 8001` 启动，则把端口替换为 `8001`。
- 普通业务 API 直接可调用；AI 相关 API 需要在请求头中提供 `Authorization: Bearer <your-api-key>`。
- 上传接口使用 `multipart/form-data`，其余大部分接口使用 JSON 或普通查询参数。
- 成功响应通常返回 JSON；导出接口会返回文件流。
- 常见错误码：`400` 参数错误，`401` 未认证，`403` 无权限，`404` 资源不存在，`500` 服务端异常。

### 1) 健康检查

```http
GET /api/health
```

最小响应：

```json
{
  "status": "ok",
  "service": "smart-audit-platform"
}
```

适合用于：

- 启动后验证后端进程是否可用。
- Docker 或脚本健康检查。
- 前端页面右上角状态灯的基础数据源。

### 2) OCR 诊断

```http
GET /api/ocr/check
```

示例响应：

```json
{
  "python": "3.10.8",
  "ocr_engine": "auto",
  "ocr_langs": ["zh", "en"],
  "ocr_min_conf": 0.55,
  "paddleocr_installed": true,
  "paddle_installed": true,
  "torch_installed": true,
  "paddleocr_import_error": "",
  "paddle_import_error": ""
}
```

你可以把它理解为“环境自检”，重点看这几个字段：

- `ocr_engine`：当前实际使用的 OCR 引擎策略。
- `paddleocr_installed` / `torch_installed`：图片 OCR 是否真正可用。
- `paddleocr_import_error`：如果有报错，这里通常会直接暴露导入失败原因。

### 3) 上传文件并创建任务

```http
POST /api/files/upload
Content-Type: multipart/form-data
```

字段：

- `file`：待上传文件。

支持格式：

- `.pdf`
- `.png`、`.jpg`、`.jpeg`、`.bmp`、`.tif`、`.tiff`
- `.xlsx`、`.xls`、`.csv`

响应示例：

```json
{
  "file_id": 1,
  "task_id": 1,
  "filename": "sample.xlsx",
  "status": "pending"
}
```

说明：

- 上传成功后会同时创建一个文件记录和一个任务记录。
- `task_id` 是后续启动处理、查询进度、导出结果的关键 ID。
- 如果上传失败，通常是文件类型不支持或文件体为空。

### 4) 启动任务

```http
POST /api/tasks/{task_id}/run
```

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/tasks/1/run
```

返回示例：

```json
{
  "task_id": 1,
  "status": "queued",
  "message": "处理任务已启动"
}
```

补充说明：

- 如果任务已经处于 `running`，接口会直接返回当前任务信息。
- 后端通过后台任务执行处理流程，不需要前端额外轮询提交。

### 5) 查询任务

```http
GET /api/tasks
GET /api/tasks/{task_id}
```

查询全部任务：

```bash
curl http://127.0.0.1:8000/api/tasks
```

查询单个任务：

```bash
curl http://127.0.0.1:8000/api/tasks/1
```

说明：

- `/api/tasks` 默认返回最近 20 条任务。
- `/api/tasks/{task_id}` 会返回单条任务的完整状态信息，前端用于刷新任务详情和步骤进度。

### 6) 查询明细记录

```http
GET /api/records?page=1&page_size=20
GET /api/records?start_date=2024-01-01&end_date=2024-12-31&account=1001&voucher_no=记-001&min_amount=1000
```

支持参数：

- `start_date`：起始日期，格式 `YYYY-MM-DD`
- `end_date`：结束日期，格式 `YYYY-MM-DD`
- `account`：科目编码或科目名称片段
- `voucher_no`：凭证号
- `min_amount`：最小金额
- `max_amount`：最大金额
- `page`：页码，默认 `1`
- `page_size`：每页数量，默认 `20`，最大 `100`

推荐调用方式：

```bash
curl "http://127.0.0.1:8000/api/records?page=1&page_size=20&account=1001"
```

这个接口适合：

- 前端分页表格。
- 审计抽样前的条件筛选。
- 定位异常记录。

### 7) 记录详情

```http
GET /api/records/{record_id}
```

示例：

```bash
curl http://127.0.0.1:8000/api/records/123
```

返回信息通常会包含：

- 记录的基础字段。
- 来源文件与任务信息。
- 异常标记原因。
- 结构化后的金额、科目、凭证、日期等字段。

### 8) 校验报告

```http
GET /api/reports/{task_id}
```

示例：

```bash
curl http://127.0.0.1:8000/api/reports/1
```

返回结构：

```json
{
  "task": {"id": 1, "status": "completed"},
  "reports": [
    {"id": 1, "rule_name": "余额平衡检查", "result": "pass"}
  ],
  "exceptions": [
    {"id": 10, "is_exception": true, "reason": "金额异常"}
  ]
}
```

适合用于：

- 任务完成后查看审计结论。
- 把异常记录和规则结果一起展示给审计人员。

### 9) 导出文件

```http
GET /api/export/{task_id}?format=excel
GET /api/export/{task_id}?format=xbrl
GET /api/export/{task_id}?format=report
GET /api/export/{task_id}?format=docx
```

参数说明：

- `excel`：导出 Excel，必要时会回退为 CSV。
- `xbrl`：导出简易 XBRL XML。
- `report`：导出校验报告 JSON。
- `docx`：导出 Word 底稿。

示例：

```bash
curl -o audit-report.xlsx "http://127.0.0.1:8000/api/export/1?format=excel"
```

### 10) 账户分类与分析接口

这一组接口用于辅助科目映射、趋势分析和异常分布查看。

```http
GET /api/accounts/classifier/status
POST /api/accounts/classifier/train
POST /api/accounts/classifier/predict
GET /api/accounts/mappings
GET /api/analysis/full
```

典型用途：

- 根据历史摘要训练科目分类器。
- 输入一条摘要，预测标准科目编码与名称。
- 查看系统当前映射规则。
- 获取趋势、科目、异常、金额、任务等综合图表数据。

例如预测接口：

```bash
curl -X POST http://127.0.0.1:8000/api/accounts/classifier/predict \
  -H "Content-Type: application/json" \
  -d "{\"summary\":\"支付购口罩款\"}"
```

### 11) 抽样与对账接口

```http
GET /api/sampling/random
GET /api/sampling/stratified
GET /api/sampling/large
GET /api/sampling/export
POST /api/reconciliation/parse
POST /api/reconciliation/reconcile
```

用途：

- `random`：随机抽样。
- `stratified`：分层抽样。
- `large`：大额抽样。
- `reconciliation/*`：银行对账单解析与勾稽。

### 12) 发票识别接口

```http
POST /api/invoice/extract
POST /api/invoice/batch
GET /api/invoice/export
```

适合场景：

- 先对 OCR 文本单条识别发票字段。
- 再对整批 OCR 结果批量提取。
- 最后导出发票明细表。

### 13) AI 审计工作流接口

这部分接口需要请求头中提供：

```http
Authorization: Bearer <your-api-key>
```

#### 列出可用工作流

```http
GET /api/ai/workflows
```

返回示例：

```json
{
  "workflows": [
    {
      "id": "full_audit",
      "name": "全面审计流程",
      "description": "数据质量→12项异常扫描→科目分析→风险评级→AI建议",
      "steps": ["data_quality_check", "comprehensive_anomaly", "account_analysis", "risk_assessment", "generate_recommendations"]
    }
  ]
}
```

#### 执行工作流

```http
POST /api/ai/workflows/run
Content-Type: application/json
Authorization: Bearer <your-api-key>
```

请求体示例：

```json
{
  "workflow_name": "full_audit",
  "task_id": 1,
  "use_ai_summary": true
}
```

curl 示例：

```bash
curl -X POST http://127.0.0.1:8000/api/ai/workflows/run \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-api-key>" \
  -d '{"workflow_name":"full_audit","task_id":1,"use_ai_summary":true}'
```

工作流返回通常包含：

- `workflow`：工作流名称。
- `description`：工作流说明。
- `task_id`：任务 ID。
- `steps`：每一步的结果数组。
- `evidence_chain`：异常记录的证据链。
- `ai_summary`：AI 汇总结论。
- `secondary_review`：高风险时的二次校验结果。
- `audit_trail`：执行轨迹。

## 工作流内部说明

### 工作流模板

内部工作流定义集中在 [backend/ai/workflows.py](backend/ai/workflows.py)。当前支持的模板如下：

| ID | 名称 | 典型用途 | 步骤 |
| --- | --- | --- | --- |
| `full_audit` | 全面审计流程 | 适合完整复核 | `data_quality_check` → `comprehensive_anomaly` → `account_analysis` → `risk_assessment` → `generate_recommendations` |
| `quick_scan` | 快速扫描 | 适合快速初筛 | `large_amount_scan` → `duplicate_scan` → `balance_check` → `anomaly_scan` |
| `ar_audit` | 应收账款专项审计 | 应收账款分析 | `ar_balance_check` → `ar_aging_analysis` → `ar_revenue_match` → `ar_risk_summary` |
| `ap_audit` | 应付账款专项审计 | 应付账款分析 | `ap_balance_check` → `ap_vendor_analysis` → `ap_payment_check` → `ap_risk_summary` |
| `revenue_audit` | 收入确认专项审计 | 收入完整性与截止性 | `revenue_period_check` → `revenue_amount_check` → `revenue_account_match` → `revenue_risk_summary` |
| `expense_audit` | 费用报销专项审计 | 费用合规与真实性 | `expense_reasonableness` → `expense_compliance` → `expense_anomaly` → `expense_risk_summary` |
| `four_way` | 四联动核验 | 发票、合同、付款、入账交叉验证 | `four_way_check` |
| `multi_perspective` | 多视角审计 | 风险、合规、业务三方观点合并 | `multi_perspective_analysis` |

### 工作流执行顺序

`run_workflow(db, workflow_name, task_id, use_ai_summary=True)` 会按以下顺序运行：

1. 检查工作流名称是否存在。
2. 读取任务与文件信息。
3. 记录审计轨迹（`AuditTrail`）。
4. 按模板逐步执行同步步骤和异步步骤。
5. 为异常记录构建证据链。
6. 如启用，则调用 LLM 生成 AI 汇总。
7. 如发现高风险步骤，则执行二次校验。
8. 返回完整 JSON 结果。

### 同步步骤与异步步骤

同步步骤由 `STEP_HANDLERS` 承接，典型包括：

- `data_quality_check`
- `comprehensive_anomaly`
- `account_analysis`
- `risk_assessment`
- `large_amount_scan`
- `duplicate_scan`
- `balance_check`

异步步骤由 `ASYNC_STEPS` 承接，主要用于需要 LLM 参与的分析：

- `generate_recommendations`
- `ar_aging_analysis`
- `ar_revenue_match`
- `ar_risk_summary`
- `ap_vendor_analysis`
- `ap_payment_check`
- `ap_risk_summary`
- `revenue_risk_summary`
- `expense_risk_summary`

### 关键内部接口

- `comprehensive_anomaly_scan(db, task_id)`：执行 12 项异常扫描，输出异常总数、严重度分布和重点问题。
- `build_evidence_chain(db, record_ids)`：基于异常记录 ID 组装证据链，给二次复核使用。
- `four_way_verification(db, task_id)`：执行四联动核验，适合票据、合同、付款与入账一致性检查。
- `secondary_review(primary_conclusion, evidence)`：在高风险场景下做二次校验，减少单次模型误判。
- `multi_perspective_audit(db, task_id)`：将多个审计视角并行分析后合并意见。

### 工作流输出字段说明

典型工作流返回包含以下字段：

- `workflow`：中文工作流名称。
- `description`：工作流说明。
- `task_id`：当前任务编号。
- `filename`：文件名。
- `started_at` / `completed_at`：执行时间。
- `steps`：逐步执行结果数组。
- `evidence_chain`：证据链数据。
- `ai_summary`：模型总结。
- `secondary_review`：二次校验结果。
- `audit_trail`：审计执行轨迹。

### 工作流调用建议

- `full_audit` 适合最终审计结论输出。
- `quick_scan` 适合大批量初筛。
- `four_way` 适合票据与资金链核对。
- `multi_perspective` 适合需要多角色意见融合的复杂项目。

### 示例响应片段

```json
{
  "workflow": "全面审计流程",
  "task_id": 1,
  "steps": [
    {"step": "data_quality_check", "total_records": 128, "issues": []},
    {"step": "comprehensive_anomaly", "total_findings": 6},
    {"step": "risk_assessment", "risk_score": 72, "risk_level": "中"}
  ],
  "ai_summary": "...",
  "audit_trail": {"events": []}
}
```

## 数据目录

运行后会生成这些目录：

- `data/`：SQLite 数据库和测试/调试产物
- `storage/uploads/`：上传文件
- `storage/exports/`：导出文件
- `logs/`：应用日志

## 测试与验证脚本

- `scripts/check_paddleocr.py`：检查 PaddleOCR 是否能初始化
- `scripts/ocr_test_standalone.py`：直接调用 PaddleOCR 做独立烟雾测试
- `scripts/api_ocr_test.py`：上传图片到 API，验证任务链路是否真的走 OCR
- `scripts/ocr_status.py`：读取 OCR 诊断信息
- `scripts/ocr_image_smoke.py`：OCR 图片烟雾测试
- `scripts/regression_smoke.py`：回归烟雾测试
- `run_ocr_test.bat`：Windows 下快速执行 OCR 独立测试

示例：

```powershell
python scripts/check_paddleocr.py
python scripts/ocr_test_standalone.py
python scripts/api_ocr_test.py http://127.0.0.1:8000
```

## Docker 说明

Dockerfile 和 docker compose 已经配置了应用启动、健康检查和数据卷挂载，适合快速拉起主程序和前端界面。

需要注意的是，当前镜像默认安装的是项目通用依赖，不会自动把本机虚拟环境里的 OCR 包一起打进去。如果你希望容器内也能做真实图片 OCR，需要额外把 `paddleocr` / `easyocr` 安装进镜像，或者直接在本地虚拟环境中运行。

## 故障排查

- 访问不了页面：先检查 `http://127.0.0.1:8000/api/health`
- 上传失败：确认文件后缀在允许列表内
- OCR 状态显示未就绪：检查 `paddleocr` 是否安装成功，以及 `torch` 相关 DLL 是否可加载
- 图片识别只有占位结果：说明当前环境没有可用 OCR 引擎
- Docker 启动后无法访问：检查端口 8000 是否被占用，或查看 `docker compose logs -f`

## 验收标准与测试用例

如果你想确认这套系统是否已经“可以交付”，建议按下面的标准逐项检查：

### 基础验收

- `GET /api/health` 返回 `{"status":"ok"}`。
- `GET /api/ocr/check` 能返回 Python 版本、OCR 引擎状态和依赖诊断信息。
- 上传一个 Excel 或图片文件后，能够拿到 `file_id` 和 `task_id`。
- 调用 `POST /api/tasks/{task_id}/run` 后，任务状态能够从 `queued` 走到完成态。
- `GET /api/records` 能看到结构化数据分页结果。
- `GET /api/reports/{task_id}` 能看到校验报告和异常记录。
- `GET /api/export/{task_id}?format=excel` 能成功下载文件。

### 前端验收

- 页面打开后，能看到工作流类型卡片、任务预览和进度区域。
- 点击不同工作流卡片时，预览区会同步切换内容。
- 点击任务项后，能跳转并展开对应详情。
- 工作流执行过程中，进度条与步骤状态会同步更新。
- 异常记录、证据链和审计结论能够从结果区直接定位。

### AI 工作流验收

- `GET /api/ai/workflows` 能列出所有工作流模板。
- `POST /api/ai/workflows/run` 能执行 `full_audit`、`quick_scan`、`four_way`、`multi_perspective` 等模板。
- 执行结果中应包含 `steps`、`audit_trail`、`ai_summary`，高风险时还应包含 `secondary_review`。
- 如果任务没有异常记录，`evidence_chain` 可能为空，这是正常结果，不是错误。

### 建议测试用例

1. 上传一个包含正常记录的 Excel，验证结构化解析和导出。
2. 上传一个包含明显异常的数据集，验证异常识别、报告输出和证据链展示。
3. 对同一任务分别运行 `quick_scan` 和 `full_audit`，比较两者输出差异。
4. 使用 `four_way` 检查票据、付款和入账数据的一致性。
5. 用浏览器自动化脚本验证工作流卡片、步骤折叠和跳转交互。

## 许可与使用范围

本项目用于本地/内网审计数据处理和演示，不包含账号体系和多用户权限控制。

## 最近更新 (2026-05-23)

- **重写后端审计工作流**：重写并完善 `backend/ai/workflows.py`，实现异步 AI 步骤、证据链构建、二次校验触发以及特殊工作流分支（four_way、multi_perspective）。已通过语法检查并在本地开发环境验证基本运行。
- **新增/集成模块**：新增或集成 `backend/ai/anomalies.py`（全面异常扫描）、`backend/ai/verification.py`（核验与证据链）、`backend/ai/perspectives.py`（多视角并行审计）。这些模块在工作流中已被调用，请在部署前确认依赖已安装并按需调整配置。
- **前端重构：自动审计页面**：重写 `frontend/index.html`、`frontend/app.js` 与 `frontend/styles.css`，新增工作流类型卡片、任务预览、步骤展开/折叠、进度条、证据链展示与跳转交互。自动化验证（Playwright）已覆盖主要交互场景。
- **修复：文件上传重复触发**：定位并修复了因事件重复绑定导致的一次上传触发两次的 bug（已移除重复的绑定调用）。

## 开发者与贡献指南（简要）

- 在本地创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

- 运行服务（开发模式）：

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

- 提交改动示例：

```bash
git add .
git commit -m "feat(audit): rewrite workflows; add ai modules; revamp frontend auto-audit; fix upload duplicate binding"
git push origin main
```

- 注意：推送到远程需要已配置好 `origin` 远程仓库和有效的凭据（SSH key 或 HTTPS token）。如果推送失败，请按错误提示检查远程和权限。

如果你需要，我可以现在帮你执行 `git add` / `git commit` / `git push`（会在命令输出中回报任何认证或远程错误）。

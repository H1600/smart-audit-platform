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

### 健康检查

```http
GET /api/health
```

返回示例：

```json
{"status":"ok","service":"smart-audit-platform"}
```

### OCR 诊断

```http
GET /api/ocr/check
```

返回示例字段包括：

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

### 上传文件

```http
POST /api/files/upload
Content-Type: multipart/form-data
```

字段：`file`

返回示例：

```json
{
  "file_id": 1,
  "task_id": 1,
  "filename": "sample.xlsx",
  "status": "pending"
}
```

### 启动任务

```http
POST /api/tasks/{task_id}/run
```

返回示例：

```json
{"task_id": 1, "status": "queued", "message": "处理任务已启动"}
```

### 查询任务

```http
GET /api/tasks
GET /api/tasks/{task_id}
```

`/api/tasks` 返回最近 20 条任务。

### 查询记录

```http
GET /api/records?page=1&page_size=20
GET /api/records?start_date=2024-01-01&end_date=2024-12-31&account=1001&voucher_no=记-001&min_amount=1000
```

支持参数：

- `start_date`
- `end_date`
- `account`
- `voucher_no`
- `min_amount`
- `max_amount`
- `page`
- `page_size`

### 记录详情

```http
GET /api/records/{record_id}
```

返回单条结构化记录的完整信息，包括来源文本、行号和异常原因。

### 校验报告

```http
GET /api/reports/{task_id}
```

返回任务对应的校验规则结果和异常记录列表。

### 导出文件

```http
GET /api/export/{task_id}?format=excel
GET /api/export/{task_id}?format=xbrl
GET /api/export/{task_id}?format=report
```

支持格式：

- `excel`：导出 `.xlsx`，若 openpyxl 写入失败则回退为 `.csv`
- `xbrl`：导出简易 XBRL `.xml`
- `report`：导出校验报告 `.json`

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

## 许可与使用范围

本项目用于本地/内网审计数据处理和演示，不包含账号体系和多用户权限控制。

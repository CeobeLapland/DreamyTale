# Backend

后端负责把组委会压缩包转换成统一的单书数据包，并对外提供交互协议与任务接口。
数据契约的唯一事实源是 `contracts/models.py`（v2.0.0），`backend/app/models.py` 只做再导出。

生成数据写入 `temp/`，不进入 Git。

## 环境

- Python 3.11 或更高版本
- 在仓库根目录执行命令

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

## 查看压缩包中的绘本

```powershell
.\.venv\Scripts\python.exe -m backend.app.cli `
  --archive "D:\纸书智伴\纸书智伴企业预选赛绘本素材.zip" `
  --list
```

## 导入一本绘本

```powershell
.\.venv\Scripts\python.exe -m backend.app.cli `
  --archive "D:\纸书智伴\纸书智伴企业预选赛绘本素材.zip" `
  --book "中文绘本01" `
  --output "temp/books" `
  --force
```

## 检查全部绘本

```powershell
.\.venv\Scripts\python.exe -m backend.app.cli `
  --archive "D:\纸书智伴\纸书智伴企业预选赛绘本素材.zip" `
  --inspect-all
```

## 校验和迁移单书数据包

```powershell
.\.venv\Scripts\python.exe -m backend.app.cli --validate zh-01
.\.venv\Scripts\python.exe -m backend.app.cli --migrate zh-01
```

`--validate` 会按 v2 契约校验字段，并检查页图、原始 PDF、音频文件是否存在。
`--migrate` 会把 v1 旧格式 `book.json` 升级成 v2：补齐 `content_type/source_type/status/created_at`，
把 `pdf_path` 改成 `source_path`，并把 `script_path/steps/click_targets` 拆成独立的 QuerySet 文件。

输出目录（与 `pipeline/` 的产物同构）：

```text
temp/books/zh-01/
  book.json                                # v2 BookPackage
  query_sets/zh-01-script-v1.json          # v2 QuerySet（命题组脚本）
  pages/001.png ... 012.png
  audio/01.wav ... 50.wav
  source/book.pdf
  source/script.txt
  source/original-audio.mapping.json
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

## 启动 API

```powershell
.\.venv\Scripts\python.exe -m backend.app.api
```

- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`GET /health`
- 书单：`GET /api/books`
- 单书数据包：`GET /api/books/{book_id}`
- 题目集合：`GET /api/books/{book_id}/query-sets`、`GET /api/books/{book_id}/query-sets/{query_set_id}`
- 能力报告：`GET /api/books/{book_id}/capability`
- 单书静态资源：`GET /api/books/{book_id}/assets/{asset_path}`
- 生成任务：`POST /api/books/{book_id}/generate`
- 查询任务：`GET /api/jobs/{job_id}`
- 交互协议：`POST /api/interact`（请求体 `InteractionRequest`，响应体 `InteractionResponse`）
- 兼容别名：`POST /api/qa`（等价于 `kind=qa`）

生成接口已经具备持久化任务状态、进度、失败信息和后台线程。生成模型尚未接入时，任务会明确进入
`failed` 状态并返回 `generation pipeline is not configured`，不会伪装成生成成功。

## 交互协议的当前边界

`POST /api/interact` 按契约 §9 返回 `action / answer / latency / status / error`。后端目前没有接入
ASR、检索增强问答和 TTS，因此：

- `kind=control`、基于文字层的 `search`/`highlight`、命中热区的 `click`：直接给真实结果，`status="ok"`；
- `kind=qa`、`kind=seek` 以及找不到目标的检索：`status="fallback"`，`answer.tier="guide"`，
  并在 `error` 里说明缺哪一环。

契约明确不允许用占位答案伪装成功，所以缺能力时一律走 `fallback`。

## 当前数据约定

- `QueryKind`：`control` / `seek` / `search` / `highlight` / `click` / `qa`，按脚本中文语义分类。
- `Mandatory`：脚本或子动作中带“必选”标记。
- `Audio`：按脚本编号匹配实际 WAV，忽略 `__MACOSX` 和 `._*` 文件。
- `Click targets`：从 `[点击]` 子动作中提取去重后的对象名称。
- 页面图坐标以 PNG 像素为准，PDF 页面尺寸同时记录在 `book.json` 中。
- 页图的 `sha256`、`render{dpi,renderer,version}` 与 `text_spans` 的 `hash` 都按契约生成。

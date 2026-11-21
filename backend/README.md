# Backend

后端第一阶段负责把组委会压缩包转换为统一的单书数据包。生成数据写入 `temp/`，不进入 Git。

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

`--validate` 会检查数据契约、页面与脚本索引、路径以及音频和页面文件是否存在。`--migrate` 会把旧格式 `book.json` 原地更新为当前契约格式。

输出目录：

```text
temp/books/zh-01/
  book.json
  pages/001.png ... 012.png
  audio/001.wav ... 050.wav
  source/book.pdf
  source/script.txt
  source/original-audio.mapping.json
```

## 测试

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests -v
```

## 启动 API

```powershell
.\.venv\Scripts\python.exe -m backend.app.api
```

- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`GET /health`
- 书单：`GET /api/books`
- 单书数据包：`GET /api/books/{book_id}`
- 单书静态资源：`GET /api/books/{book_id}/assets/{asset_path}`
- 生成任务：`POST /api/books/{book_id}/generate`
- 查询任务：`GET /api/jobs/{job_id}`

生成接口已经具备持久化任务状态、进度、失败信息和后台线程。生成模型尚未接入时，任务会明确进入 `failed` 状态并返回 `generation pipeline is not configured`，不会伪装成生成成功。

问答接口 `POST /api/qa` 已保留数据契约入口；在 ASR、检索和 TTS 适配器接入前返回结构化 `503 qa_not_configured`。

## 当前数据约定

- `Numbered step`：脚本中的编号动作。
- `Mandatory`：脚本或子动作中带“必选”标记。
- `Audio`：按脚本编号匹配实际 WAV，忽略 `__MACOSX` 和 `._*` 文件。
- `Click targets`：从 `[点击]` 子动作中提取去重后的对象名称。
- 页面图坐标以 PNG 像素为准，PDF 页面尺寸同时记录在 `book.json` 中。


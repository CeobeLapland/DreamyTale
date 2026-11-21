# 数据结构限制

本文档是 DreamyTale 前后端、生成链路和评测工具之间的统一数据契约。任何破坏兼容性的修改都必须提升 `schema_version`，并同步通知 A、B、C。

## 当前实现状态

当前后端导入器已经能够生成：

- `schema_version`、`book_id`、`source_name`、`title`、`language` 和页面数量。
- 页面列表、页面图路径、PDF 文本、PDF 尺寸和 PNG 像素尺寸。
- 页面 `text_source`、空 `text_spans` 和空 `hotspots` 数组。
- 50 个脚本步骤、步骤级必选标记、动作类型和点击目标名称。
- 步骤内每个动作的唯一 `action_id`。
- 按脚本编号映射的音频路径。

以下能力已经实现接口和状态模型，但尚未接入具体模型：

- 文件型 Job 状态、进度、失败信息和后台任务线程。
- 书单、单书详情、单书静态资源、生成任务和 Job 查询 API。
- Scene 时间轴的数据模型。
- 问答接口入口；ASR、检索、LLM 和 TTS 适配器尚未接入。

空 `text_spans` 和空 `hotspots` 是合法的契约初始值，OCR/VLM 接入后再填充真实坐标。生成和问答接口不得用占位答案伪装成功。

## 1. 基本原则

- 版本字段：当前为 `schema_version: "1.0.0"`。
- 字段命名：统一使用 `snake_case`。
- 时间：Job 和日志使用 ISO 8601 UTC，例如 `2026-11-16T08:30:00Z`。
- 编号：页面和脚本步骤从 `1` 开始，前端不得使用零基编号。
- 文件路径：统一使用相对于单书包根目录的 POSIX 路径，例如 `pages/001.png`。
- 坐标系：页面像素坐标，原点在左上角，`bbox_px = [x1, y1, x2, y2]`，其中 `x2` 和 `y2` 为排他边界。
- 缺失值：未知字段使用 `null`；不要用空字符串伪装缺失数据。
- 禁止写死：不得把页面内容、坐标、答案或视频地址写死在前后端代码中。

## 2. 单书包目录

```text
<book_package>/
  book.json
  pages/001.png
  pages/002.png
  audio/001.wav
  audio/002.wav
  source/book.pdf
  source/script.txt
  derived/
```

`book.json` 是索引文件。`source/` 保存原始输入快照，`derived/` 保存 OCR、热区、场景和生成结果的中间产物。

## 3. BookPackage

```json
{
  "schema_version": "1.0.0",
  "book_id": "zh-01",
  "source_name": "中文绘本01",
  "title": "一起搭积木吧",
  "language": "zh-CN",
  "pdf_path": "source/book.pdf",
  "script_path": "source/script.txt",
  "page_count": 12,
  "pages": [],
  "steps": [],
  "click_targets": []
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | string | 是 | 语义化版本 |
| `book_id` | string | 是 | 稳定、唯一，如 `zh-01` |
| `source_name` | string | 是 | 原始书籍名称 |
| `title` | string | 是 | 展示标题，可为 `source_name` |
| `language` | string | 是 | `zh-CN` 或 `en` |
| `pdf_path` | string | 是 | 包内相对路径 |
| `script_path` | string | 是 | 包内相对路径 |
| `page_count` | integer | 是 | 必须等于 `pages.length` |
| `pages` | Page[] | 是 | 页面按 `index` 升序 |
| `steps` | ScriptStep[] | 是 | 编号连续，通常 1 至 50 |
| `click_targets` | string[] | 是 | 去重后的点击对象名称 |

## 4. Page

```json
{
  "index": 1,
  "image_path": "pages/001.png",
  "text": "下雨了，小满、花花只好在家里玩。",
  "text_source": "embedded_pdf",
  "width_pt": 1303.9,
  "height_pt": 652.0,
  "width_px": 2608,
  "height_px": 1304,
  "text_spans": [],
  "hotspots": []
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `index` | integer | 是 | 从 1 开始且不重复 |
| `image_path` | string | 是 | 必须是可访问的页面图 |
| `text` | string | 是 | 可用于全文检索的纯文本 |
| `text_source` | enum | 是 | `embedded_pdf`、`ocr`、`manual` |
| `width_pt` | number | 是 | PDF 页面宽度 |
| `height_pt` | number | 是 | PDF 页面高度 |
| `width_px` | integer | 是 | 页面图的像素宽度 |
| `height_px` | integer | 是 | 页面图的像素高度 |
| `text_spans` | TextSpan[] | 是 | 可为空数组 |
| `hotspots` | Hotspot[] | 是 | 可为空数组 |

页面文字必须与页面图尺寸使用同一渲染版本。重新渲染页面后，必须重新生成文字坐标和热区。

## 5. ScriptStep

一个脚本编号对应一条 Query 音频，可包含一个主动作和若干子动作。

```json
{
  "number": 5,
  "instruction": "他们在搭什么？",
  "mandatory": true,
  "audio_path": "audio/005.wav",
  "actions": [
    {
      "action_id": "step-005-a01",
      "type": "question",
      "text": "他们在搭什么？",
      "mandatory": true
    },
    {
      "action_id": "step-005-a02",
      "type": "click",
      "text": "点击积木城堡 | 暂停并展示城堡信息",
      "target": "积木城堡",
      "mandatory": true
    }
  ]
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `number` | integer | 是 | 从 1 开始，单书内唯一 |
| `instruction` | string | 是 | 主指令或问题原文 |
| `mandatory` | boolean | 是 | 任一子动作必选即为 `true` |
| `audio_path` | string | 是 | 必须是有效 WAV 路径 |
| `actions` | Action[] | 是 | 至少一个动作，顺序不可打乱 |

`mandatory` 是步骤级去重结果。同一个步骤中主指令和子动作都标“必选”时，不应被计为两个步骤。

## 6. Action

支持的 `type`：

| 类型 | 含义 | 必要字段 |
| --- | --- | --- |
| `control` | 播放、暂停、继续、结束 | `text` |
| `find_scene` | 找到某个语义画面 | `text` |
| `question` | 对页面、故事或对象提问 | `text` |
| `click` | 点击对象并展示信息 | `target` |
| `search_text` | 在页面文字中查找 | `text` |
| `highlight` | 高亮文字或对象 | `text` |
| `other` | 暂未分类的动作 | `text` |

公共字段：

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `action_id` | string | 是 | 单书内唯一，如 `step-005-a02` |
| `type` | enum | 是 | 使用上表枚举 |
| `text` | string | 是 | 动作原文 |
| `mandatory` | boolean | 是 | 是否必须执行 |
| `target` | string/null | `click` 必填 | 点击对象名称 |

## 7. TextSpan

用于“查找文字”和“高亮文字”。

```json
{
  "span_id": "page-001-span-003",
  "page_index": 1,
  "text": "积木城堡",
  "bbox_px": [842, 310, 1110, 390],
  "source": "ocr"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `span_id` | string | 是 | 单书内唯一 |
| `page_index` | integer | 是 | 必须引用已有页面 |
| `text` | string | 是 | 检索文本 |
| `bbox_px` | integer[4] | 是 | 按页面像素坐标 |
| `source` | enum | 是 | `embedded_pdf`、`ocr`、`manual`、`vlm` |

## 8. Hotspot

用于点击识别和对象信息卡。

```json
{
  "hotspot_id": "page-001-hotspot-001",
  "page_index": 1,
  "label": "积木城堡",
  "bbox_px": [620, 240, 1180, 560],
  "description": "小满和花花一起搭建的积木城堡",
  "source": "manual"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `hotspot_id` | string | 是 | 单书内唯一 |
| `page_index` | integer | 是 | 必须引用已有页面 |
| `label` | string | 是 | 用于点击命中和展示 |
| `bbox_px` | integer[4] | 是 | 必须在页面图范围内 |
| `description` | string | 是 | 点击后展示的信息 |
| `source` | enum | 是 | `pdf_annotation`、`vlm`、`manual` |

同一页面内允许重叠热区，但前端必须使用稳定优先级：后标注的 `manual` 热区优先于自动识别热区。

## 9. Scene 与视频时间轴

视频播放、语义检索和点击坐标必须落到同一时间轴。

```json
{
  "scene_id": "scene-003",
  "page_index": 3,
  "start_ms": 16000,
  "end_ms": 24000,
  "caption": "小满和花花搭出九块积木的城堡",
  "aliases": ["九块积木", "积木城堡", "城堡没有倒"],
  "video_path": "derived/video/scene-003.mp4",
  "thumbnail_path": "derived/video/scene-003.jpg",
  "hotspot_ids": ["page-003-hotspot-001"]
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `scene_id` | string | 是 | 单书内唯一 |
| `page_index` | integer | 是 | 必须引用已有页面 |
| `start_ms` | integer | 是 | 非负，且小于 `end_ms` |
| `end_ms` | integer | 是 | 不得重叠同一视频片段 |
| `caption` | string | 是 | 用于语义检索的主描述 |
| `aliases` | string[] | 是 | 至少包含一个别名 |
| `video_path` | string | 是 | 可为原始片段或页面动画 |
| `thumbnail_path` | string | 是 | 供场景检索和调试 |
| `hotspot_ids` | string[] | 是 | 引用已有 Hotspot |

## 10. 问答接口

请求：

```json
{
  "book_id": "zh-01",
  "page_index": 3,
  "current_time_ms": 18500,
  "hotspot_id": null,
  "question_text": "他们在搭什么？",
  "audio_path": "audio/005.wav"
}
```

响应：

```json
{
  "request_id": "qa-20261116-000001",
  "answer_text": "他们在一起搭积木城堡。",
  "page_index": 3,
  "scene_id": "scene-003",
  "evidence_span_ids": ["page-003-span-004"],
  "answer_audio_path": "derived/qa/answer-001.wav",
  "latency_ms": 1800,
  "status": "completed"
}
```

`latency_ms` 的统计口径是用户语音结束到 TTS 首音开始。问答链路不得调用文生视频模型。

## 11. Job 状态

```json
{
  "job_id": "job-zh01-20261116-001",
  "book_id": "zh-01",
  "status": "running",
  "stage": "video",
  "progress": 0.45,
  "created_at": "2026-11-16T08:30:00Z",
  "updated_at": "2026-11-16T08:31:20Z",
  "error": null
}
```

`status` 枚举：

```text
queued
running
completed
failed
cancelled
```

`stage` 枚举：

```text
ingest
ocr
vlm
story
scene
video
tts
compose
index
```

进度必须是 `0` 到 `1` 的小数。失败时 `error` 必须是可读字符串，不得只返回异常堆栈。

## 12. 校验规则

- `page_count == len(pages)`。
- `page.index` 从 1 开始且连续。
- 单本脚本步骤编号唯一；正式参赛包通常为 1 至 50。
- 每个脚本步骤必须有对应音频。
- 单个音频编号不得重复；必须忽略 `__MACOSX`、`._*` 和 `.DS_Store`。
- `mandatory` 按步骤去重，不以文本中出现次数计数。
- 点击、查找和高亮的目标必须有可解析的文本字段。
- 所有 `page_index`、`hotspot_id`、`span_id` 和 `scene_id` 必须能解析到已有对象。
- 所有路径必须是包内相对路径，不允许绝对路径。
- 不允许提交 `source/` 中的授权原始素材。

## 13. 兼容与变更

- 新增可选字段：提升次版本号，例如 `1.0.0` 到 `1.1.0`。
- 重命名字段、修改类型或删除字段：提升主版本号，例如 `1.1.0` 到 `2.0.0`。
- 修改坐标定义、音频规则或时间轴语义：必须按破坏性变更处理。
- 任何契约变更必须同时更新：

```text
docs/DATA_CONTRACT.md
backend/app/models.py
后端接口样例
前端类型定义
评测结果读取逻辑
```


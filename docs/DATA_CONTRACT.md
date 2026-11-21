# 数据结构契约

本文档是 DreamyTale 前后端、内容工厂、人工审核和评测工具之间的统一数据契约。
任何破坏兼容性的修改都必须提升 `schema_version`，并同步通知 A、B、C。

当前版本：`2.0.0`。

## 0. 2.0.0 变更摘要

2.0.0 不是字段微调，而是把“平台接口契约”扩成“系统契约”。核心变化：

1. **书与题目分离。** `BookPackage` 只描述书；命题组脚本/音频移到独立的 `QuerySet`。没有脚本的书也能进、能生成、能问答。
2. **页级结构化。** `Page` 增加 `blocks`（标题/正文/说明/旁白/页眉页脚/教学文字），保留 `text_spans` 与 `hotspots`。
3. **知识层与人工修正。** 新增 `PageFact`、`QaCard`、`Alias`、`Annotation`、`ReviewItem`；自动产物和人工修正双源，human 优先、auto 保留。
4. **生成产物。** 新增 `StoryPlan`、`ScenePlan`、`VideoSegment`、`BookGenerationResult`、`GenerationManifest`、`Trace`。
5. **统一交互协议。** 六类交互走同一个 `InteractionRequest/Response`；`/api/qa` 只是 `kind=qa` 的兼容别名。
6. **能力报告。** 新增 `CapabilityReport`：任何书跑完，系统要能说清自己会什么、不会什么。
7. **评测。** 新增 `EvalCase`、`EvalRun`、`EvalResult`；默认内部协议，官方格式走适配层。
8. **Job 的失败语义。** 增加 `error_code`、`degraded`、`retryable`、`manifest_path`。

v1 的 `BookPackage.pdf_path`、`script_path`、`steps`、`click_targets` 是 2.0.0 的破坏性变更，迁移见第 14 节。

## 1. 基本原则

- **版本**：每个顶层 JSON 产物（`book.json`、`story_plan.json`、`scene_plan.json`、`manifest.json`、`capability.json` 等）都带 `schema_version`，当前为 `"2.0.0"`；JSONL 产物不逐条重复，版本由所属书包的 `book.json` 统一声明。
- **命名**：结构字段统一 `snake_case`；`attributes` 的键和 `relations` 的值可以用中文。
- **时间**：日志、Job、评测用 ISO 8601 UTC，例如 `2026-11-17T06:30:00Z`；场景/字幕时间用毫秒整数，相对所属页面。
- **编号**：页面、步骤从 `1` 开始；前端不得使用零基编号。
- **路径**：统一使用相对于单书包根目录的 POSIX 路径，例如 `pages/001.png`；不允许绝对路径。
- **坐标**：页面像素坐标，原点左上，`bbox_px = [x1, y1, x2, y2]`，`x2`/`y2` 为排他边界。
- **缺失值**：未知字段用 `null`，不要用空字符串伪装缺失。
- **ID**：
  - 页级：`{type}-{book_id}-{page:03d}-{seq:03d}`，如 `span-zh-01-001-003`。
  - 书级：`{type}-{book_id}-{seq:03d}`，如 `scene-zh-01-003`。
  - `type`：`span` / `hotspot` / `fact` / `card` / `scene` / `segment` / `alias` / `annotation` / `review`。
  - ID 在单书内唯一即可；跨书引用时带上 `book_id`。
- **双源**：自动产物 `source: auto`，人工修正 `source: human`；human 优先，auto 保留，冲突不静默。
- **可复现**：生成产物必须带输入哈希、模型版本、提示词版本、seed、参数和输出哈希。
- **语言**：使用 BCP-47（`zh-CN`、`en`）；中英混排时 `language` 为主语言，`languages` 列全。
- **权限**：`source/` 中的授权原始素材、`book.json`/`query_sets/` 中的原书正文与命题组脚本不得提交到公开 Git；只提交代码、配置、文档和脱敏后的示例数据。
- **禁止写死**：不得把页面内容、坐标、答案、视频地址写死在代码中；一切来自数据。

## 2. 单书包目录

```text
data/books/<book_id>/
  book.json                          # BookPackage
  pages/001.png
  source/book.pdf                    # 或 source/photos/001.jpg
  derived/
    understanding/blocks.jsonl       # PageBlock
    understanding/narrative.jsonl    # 视觉叙事层
    understanding/hotspots.jsonl     # Hotspot（原始识别结果）
    knowledge/facts.jsonl            # PageFact
    knowledge/cards.jsonl            # QaCard
    knowledge/aliases.json           # Alias
    story/story_plan.json            # StoryPlan
    scene/scene_plan.json            # ScenePlan
    scene/timeline.json              # 页面/场景/整本时间轴
    video/scene-001.mp4              # VideoSegment
    video/page-001.mp4
    video/book.mp4
    audio/narration/page-001.wav
    audio/answer/card-zh-01-001-zh.wav
    index/vectors.jsonl
    index/meta.json
    review/queue.jsonl               # ReviewItem
    review/annotations.jsonl         # Annotation
    manifest.json                    # GenerationManifest
    capability.json                  # CapabilityReport
  query_sets/zh-01-script-v1.json     # QuerySet（可选）
  assets/thumbnails/...
```

Trace 落 `data/traces/<yyyy-mm-dd>/`，Turn 落 `data/turns/<yyyy-mm-dd>.jsonl`；与单书包分开，便于跨书审计。

- 包根为 `data/books/<book_id>/`；所有路径相对于它。
- `source/` 保存原始快照，不入 Git；`derived/` 中的媒体缓存不入 Git。
- 本仓库公开：`book.json`、`query_sets/`、`derived/understanding/` 含原书正文/命题组脚本，默认不入 Git。`facts.jsonl`、`cards.jsonl`、`aliases.json`、`story_plan.json`、`scene_plan.json`、`manifest.json`、`capability.json`、`annotations.jsonl` 如要入 Git，必须先脱敏并由三人确认；答辩材料单独打包。

## 3. BookPackage

```json
{
  "schema_version": "2.0.0",
  "book_id": "zh-01",
  "source_name": "中文绘本01",
  "title": "一起搭积木吧",
  "authors": [],
  "language": "zh-CN",
  "languages": ["zh-CN"],
  "content_type": "narrative",
  "source_type": "pdf",
  "source_path": "source/book.pdf",
  "page_count": 12,
  "pages": [],
  "style": {
    "reference_pages": [2, 3, 7],
    "palette": ["#F4E7C5", "#E8A0A0", "#7FAF9B"],
    "line": "手绘水彩，细线勾边",
    "texture": "纸张纹理，轻微颗粒",
    "negative_prompts": ["照片写实", "3D 渲染", "厚涂"]
  },
  "rights": {
    "license": "competition_sample",
    "note": "命题组授权样本，仅用于本次比赛"
  },
  "status": "ready",
  "query_set_ids": ["zh-01-script-v1"],
  "capabilities_path": "derived/capability.json",
  "created_at": "2026-11-17T06:30:00Z",
  "updated_at": "2026-11-17T06:30:00Z"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | string | 是 | 语义化版本，当前 `2.0.0` |
| `book_id` | string | 是 | 稳定、唯一；小写字母开头，允许数字和连字符 |
| `source_name` | string | 是 | 原始书籍名称 |
| `title` | string | 是 | 展示标题，可为 `source_name` |
| `authors` | string[] | 否 | 作者/绘者 |
| `language` | string | 是 | 主语言，BCP-47 |
| `languages` | string[] | 否 | 书中出现的全部语言 |
| `content_type` | enum | 是 | `narrative` / `expository` / `mixed`；可由人工确认 |
| `source_type` | enum | 是 | `pdf` / `photo` / `scan` / `mixed` |
| `source_path` | string | 是 | 包内相对路径；PDF 或照片目录 |
| `page_count` | integer | 是 | 必须等于 `pages.length` |
| `pages` | Page[] | 是 | 按 `index` 升序 |
| `style` | object | 否 | 风格 bible：参考页、色板、线条、纹理、负面提示词 |
| `rights` | object | 否 | 授权/来源信息 |
| `status` | enum | 是 | `draft` / `ingested` / `understood` / `generated` / `reviewed` / `ready` / `failed` |
| `query_set_ids` | string[] | 否 | 关联的 QuerySet；可为空 |
| `capabilities_path` | string | 否 | 能力报告路径 |
| `created_at` / `updated_at` | string | 否 | ISO 8601 UTC |

> 示例省略了 `pages` 内容；实际 `page_count` 必须等于 `pages` 长度。

`BookPackage` 不再包含 `script_path`、`steps`、`click_targets`。这些属于 `QuerySet`。

## 4. Page / PageBlock / TextSpan / Hotspot

### 4.1 Page

```json
{
  "index": 2,
  "image_path": "pages/002.png",
  "width_px": 2608,
  "height_px": 1304,
  "width_pt": 1303.9,
  "height_pt": 652.0,
  "text": "下雨了，小满、花花只好在家里玩。……",
  "text_source": "embedded_pdf",
  "text_confidence": 0.99,
  "language": "zh-CN",
  "blocks": [],
  "text_spans": [],
  "hotspots": [],
  "sha256": "59993a871a161e5f14dd6bd67c162068b33230b066e67a79da3e1969db0336d3",
  "render": { "dpi": 144, "renderer": "pymupdf", "version": "1.28.2" }
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `index` | integer | 是 | 从 1 开始且连续 |
| `image_path` | string | 是 | 可访问的页图 |
| `width_px` / `height_px` | integer | 是 | 页图像素尺寸 |
| `width_pt` / `height_pt` | number/null | 否 | PDF 页面尺寸；照片为 `null` |
| `text` | string | 是 | 可用于全文检索的正文纯文本；不含页眉/页脚/教学辅助 `note`（note 保留在 blocks） |
| `text_source` | enum | 是 | `embedded_pdf` / `ocr` / `vlm` / `manual` / `mixed` / `none`；无字页用 `none` |
| `text_confidence` | number/null | 否 | 0–1 |
| `language` | string/null | 否 | 本页主语言 |
| `blocks` | PageBlock[] | 是 | 可为空数组 |
| `text_spans` | TextSpan[] | 是 | 可为空数组 |
| `hotspots` | Hotspot[] | 是 | 可为空数组 |
| `sha256` | string | 是 | 页图内容哈希 |
| `render` | object | 否 | 渲染参数，复现用 |

页面文字必须与页图使用同一渲染版本。重新渲染后，必须重新生成 block、文字坐标和热区。

### 4.2 PageBlock

```json
{
  "block_id": "block-zh-01-002-001",
  "page_index": 2,
  "type": "body",
  "text": "下雨了，小满、花花只好在家里玩。",
  "bbox_px": [102, 96, 1054, 168],
  "source": "embedded_pdf",
  "confidence": 0.99,
  "reading_order": 1,
  "lang": "zh-CN"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `block_id` | string | 是 | 单书唯一 |
| `page_index` | integer | 是 | 引用已有页面 |
| `type` | enum | 是 | `title` / `body` / `caption` / `sfx` / `note` / `header` / `footer` / `other` |
| `text` | string | 是 | 原文；不要改写 |
| `bbox_px` | integer[4] | 是 | 页面像素坐标，必须在页图内 |
| `source` | enum | 是 | `embedded_pdf` / `ocr` / `vlm` / `manual` |
| `confidence` | number | 是 | 0–1 |
| `reading_order` | integer | 是 | 从 1 开始，Z 字阅读顺序 |
| `lang` | string/null | 否 | 本 block 语言 |

`note` 专指教学辅助文字（“阅读指导”“汉字源流”等）：它是真内容，但不属于故事正文；故事问答排除它，家长提示/阅读指导可以用它。

### 4.3 TextSpan

```json
{
  "span_id": "span-zh-01-002-003",
  "page_index": 2,
  "text": "积木城堡",
  "bbox_px": [842, 310, 1110, 390],
  "source": "ocr",
  "confidence": 0.93,
  "version": 1,
  "status": "active",
  "hash": "0c7b1e93aa42f5d8"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `span_id` | string | 是 | 单书唯一 |
| `page_index` | integer | 是 | 引用已有页面 |
| `text` | string | 是 | 检索文本 |
| `bbox_px` | integer[4] | 是 | 页面像素坐标 |
| `source` | enum | 是 | `embedded_pdf` / `ocr` / `vlm` / `manual` |
| `confidence` | number | 是 | 0–1 |
| `version` | integer | 是 | 从 1 开始 |
| `status` | enum | 是 | `active` / `superseded` |
| `hash` | string | 是 | 除 hash 外字段规范化 JSON 的 sha256 前 16 位 |

### 4.4 Hotspot

```json
{
  "hotspot_id": "hotspot-zh-01-002-001",
  "page_index": 2,
  "label": "积木城堡",
  "bbox_px": [620, 240, 1180, 560],
  "description": "小满和花花一起搭建的积木城堡",
  "source": "vlm",
  "confidence": 0.86,
  "version": 1,
  "status": "active",
  "hash": "5e2a71b0cc9d3f46"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `hotspot_id` | string | 是 | 单书唯一 |
| `page_index` | integer | 是 | 引用已有页面 |
| `label` | string | 是 | 点击命中和展示用 |
| `bbox_px` | integer[4] | 是 | 必须在页图范围内 |
| `description` | string | 是 | 点击后展示的信息 |
| `source` | enum | 是 | `pdf_annotation` / `vlm` / `auto` / `manual` |
| `confidence` | number | 是 | 0–1 |
| `version` | integer | 是 | 从 1 开始 |
| `status` | enum | 是 | `active` / `superseded` |
| `hash` | string | 是 | 内容哈希 |

同一页面允许重叠热区。命中优先级：`manual` > `vlm` > `pdf_annotation` > `auto`；同优先级取 `version` 更大者。

## 5. QuerySet / QueryItem / QueryAction

`QuerySet` 是“题目集”，不是书的一部分。它可以是命题组脚本、人工编写的测试集，或自动生成的回归集。

```json
{
  "schema_version": "2.0.0",
  "query_set_id": "zh-01-script-v1",
  "book_id": "zh-01",
  "name": "命题组脚本",
  "language": "mixed",
  "source": "official_script",
  "items": []
}
```

> 示例省略了 `items`；`QueryItem`/`QueryAction` 见下。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | string | 是 | 当前 `2.0.0` |
| `query_set_id` | string | 是 | 单书/全局唯一 |
| `book_id` | string/null | 否 | 通用题目集可为 `null` |
| `name` | string | 是 | 展示名 |
| `language` | string | 是 | `zh` / `en` / `mixed` |
| `source` | enum | 是 | `official_script` / `human` / `auto` |
| `items` | QueryItem[] | 是 | 至少一个 |

`QueryItem`：

```json
{
  "query_id": "zh-01-q005",
  "number": 5,
  "instruction": "他们在搭什么？",
  "audio_path": "audio/005.wav",
  "mandatory": true,
  "lang": "zh",
  "actions": [
    {
      "action_id": "zh-01-q005-a01",
      "kind": "qa",
      "text": "他们在搭什么？",
      "mandatory": true,
      "expected": { "answer_text": "他们在搭积木城堡。" }
    },
    {
      "action_id": "zh-01-q005-a02",
      "kind": "click",
      "text": "点击积木城堡 | 暂停并展示城堡信息",
      "mandatory": true,
      "target": "积木城堡",
      "expected": { "hotspot_id": "hotspot-zh-01-002-001" }
    }
  ]
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `query_id` | string | 是 | 单 QuerySet 唯一 |
| `number` | integer | 是 | 从 1 开始，单 QuerySet 唯一；参赛脚本通常 1–50 |
| `instruction` | string | 是 | 主指令原文 |
| `audio_path` | string/null | 否 | 包内相对路径；没有音频时为 `null` |
| `mandatory` | boolean | 是 | 任一子动作必选即为 `true` |
| `lang` | string | 是 | `zh` / `en` / `mixed` |
| `actions` | QueryAction[] | 是 | 至少一个，顺序不可打乱 |
| `expected` | object | 否 | 评测用期望；运行时不读 |

`QueryAction`：

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `action_id` | string | 是 | 单 QuerySet 唯一 |
| `kind` | enum | 是 | `control` / `seek` / `search` / `highlight` / `click` / `qa` |
| `text` | string | 是 | 动作原文 |
| `mandatory` | boolean | 是 | 是否必须执行 |
| `control_action` | enum/null | `kind=control` 必填 | `play` / `pause` / `resume` / `stop` |
| `seek_query` | string/null | `kind=seek` 必填 | 语义画面描述 |
| `search_text` | string/null | `kind=search` 必填 | 要查找的原文 |
| `highlight_text` | string/null | `kind=highlight` 必填 | 要高亮的文本 |
| `target` | string/null | `kind=click` 必填 | 点击对象名称 |
| `expected` | object | 否 | `scene_id` / `time_ms` / `span_ids` / `hotspot_id` / `answer_text` / `card_id` |

`QuerySet` 可以没有音频、没有 `expected`；这时只做交互，不做自动评分。

## 6. 知识层

### 6.1 PageFact

```json
{
  "fact_id": "fact-zh-01-002-001",
  "book_id": "zh-01",
  "page_index": 2,
  "subject": "积木城堡",
  "subject_type": "object",
  "attributes": { "颜色": "彩色", "数量": "五块", "状态": "没有倒" },
  "relations": [{ "pred": "由...搭建", "obj": "小满和花花" }],
  "bbox_px": [620, 240, 1180, 560],
  "confidence": 0.9,
  "source": "auto",
  "version": 1,
  "status": "active",
  "hash": "8b1f0c2d4e6a9b3c",
  "created_at": "2026-11-17T06:30:00Z"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `fact_id` | string | 是 | 单书唯一 |
| `book_id` | string | 是 | 引用已有书 |
| `page_index` | integer | 是 | 引用已有页面 |
| `subject` | string | 是 | 用书里的叫法，全书统一 |
| `subject_type` | enum | 是 | 叙事：`character` / `object` / `scene` / `action`；说明：`concept` / `formula` / `passage`；兜底 `other` |
| `attributes` | object | 是 | 受控键，见下 |
| `relations` | array | 是 | `{pred, obj}`；只写看得见的关系 |
| `bbox_px` | integer[4]/null | 否 | 视觉证据锚点；说明型可 `null` |
| `confidence` | number | 是 | 0–1；不许都填 1.0 |
| `source` | enum | 是 | `auto` / `human` |
| `version` | integer | 是 | 从 1 开始 |
| `status` | enum | 是 | `active` / `superseded` |
| `hash` | string | 是 | 内容哈希 |
| `created_at` | string | 是 | ISO 8601 UTC |

`attributes` 受控键：

- 叙事：`颜色` / `数量` / `动作` / `表情` / `位置` / `穿着` / `状态` / `大小` / `材质` / `形状`。
- 说明：`定义` / `性质` / `公式` / `条件` / `例子` / `关系`。

不够用时先改契约，不许自创键。

### 6.2 QaCard

```json
{
  "card_id": "card-zh-01-001",
  "book_id": "zh-01",
  "kind": "qa",
  "intent": "count",
  "scope": "page",
  "langs": ["zh", "en"],
  "question_canonical": "他们搭的城堡用了多少块积木",
  "variants": ["搭了几块积木", "积木有几块呀", "How many blocks"],
  "entities": ["积木城堡", "积木"],
  "answers": {
    "zh": {
      "strong": "九块。",
      "weak": "九块积木。花花搭了下面六块，小满放了上面三块。",
      "guide": "我们一起数数看——从最下面一层开始，你数得到几块？"
    },
    "en": {
      "strong": "Nine blocks.",
      "weak": "Nine blocks. Huahua built the bottom six, and Xiaoman added the top three.",
      "guide": "Let's count together. Start from the bottom row — how many do you see?"
    }
  },
  "evidence": [
    { "page_index": 3, "bbox_px": [312, 208, 486, 340], "fact_id": "fact-zh-01-003-001", "span_id": null }
  ],
  "video_anchor": { "scene_id": "scene-zh-01-003", "start_ms": 2400, "end_ms": 8100 },
  "priority": 1,
  "source": "human",
  "version": 1,
  "status": "active",
  "hash": "0c7b1e93aa42f5d8",
  "created_at": "2026-11-17T06:30:00Z"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `card_id` | string | 是 | 单书唯一 |
| `book_id` | string | 是 | 引用已有书 |
| `kind` | enum | 是 | 当前只允许 `qa` |
| `intent` | enum | `kind=qa` 必填 | `identify` / `count` / `locate` / `attribute` / `why` / `plot` / `predict` / `feeling` / `compare` / `vocab` / `common` / `other` |
| `scope` | enum | 是 | `page` / `book` / `video` |
| `langs` | string[] | 是 | 能应答的语言，如 `["zh","en"]` |
| `question_canonical` | string | 是 | 标准问法 |
| `variants` | string[] | 是 | 5–8 条口语变体，含儿童说法和中英混说 |
| `entities` | string[] | 是 | 涉及的实体 |
| `answers` | object | 是 | 按语言给 `strong` / `weak` / `guide` |
| `evidence` | array | 是 | 至少一条；引用真实 fact/span |
| `video_anchor` | object/null | 否 | `scene_id` + `start_ms` / `end_ms` |
| `priority` | integer | 是 | `1` 必答 / `2` 可能被问 / `3` 补漏 |
| `source` | enum | 是 | `auto` / `human` |
| `version` | integer | 是 | 从 1 开始 |
| `status` | enum | 是 | `active` / `superseded` |
| `hash` | string | 是 | 内容哈希 |

三档答案的写法：

- `strong`：一个事实，中文 ≤30 字，英文 ≤20 词；不许 LLM 改写。
- `weak`：要点清单，中文 ≤80 字；给 LLM 组织语言的骨架。
- `guide`：承认 + 翻页 + 反问，三件事缺一不可；禁止“抱歉，我无法回答”。

### 6.3 Alias

```json
{
  "alias_id": "alias-zh-01-001",
  "book_id": "zh-01",
  "entity": "积木城堡",
  "aliases": ["积木搭的城堡", "九块积木的城堡", "那个城堡"],
  "source": "human",
  "version": 1,
  "status": "active",
  "hash": "a1b2c3d4e5f60718"
}
```

别名表是命中率的最大来源：角色昵称、颜色指代、方位指代、同义说法。每张卡至少挂 3 条。

### 6.4 Narrative

VLM 把页图读成文字后的产物。对无字绘本是唯一的内容来源，对有字绘本是补充。

```json
{
  "page_index": 2,
  "book_id": "zh-01",
  "text": "下雨天，两个女孩在客厅地板上搭积木，左边扎马尾的女孩伸手去拿积木，右边扎冲天辫的女孩笑着举起一块黄色积木。",
  "entities": ["小满", "花花", "积木", "积木城堡"],
  "visible_text": ["下雨了，小满、花花只好在家里玩。"],
  "source": "vlm",
  "confidence": 0.82,
  "version": 1,
  "status": "active",
  "hash": "b2c3d4e5f6071829"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `page_index` | integer | 是 | 引用已有页面 |
| `book_id` | string | 是 | 引用已有书 |
| `text` | string | 是 | 80–150 字，只写看得见的内容 |
| `entities` | string[] | 是 | 本页出现的实体 |
| `visible_text` | string[] | 否 | 图中可见文字，可空 |
| `source` | enum | 是 | `vlm` / `human` |
| `confidence` | number | 是 | 0–1 |
| `version` | integer | 是 | 从 1 开始 |
| `status` | enum | 是 | `active` / `superseded` |
| `hash` | string | 是 | 内容哈希 |

`Narrative` 是连续叙述，不是离散事实；检索要段落，标注要事实，两者不能混。

## 7. 人工修正

### 7.1 Annotation

自动产物不直接改；人工修正是 append-only 的覆盖记录。

```json
{
  "annotation_id": "annotation-zh-01-001",
  "target_type": "hotspot",
  "target_id": "hotspot-zh-01-002-001",
  "field": "bbox_px",
  "value": [600, 220, 1200, 580],
  "old_value": [620, 240, 1180, 560],
  "source": "human",
  "reviewer": "B",
  "created_at": "2026-11-17T06:30:00Z",
  "status": "active",
  "reason": "框略大，收紧到城堡轮廓",
  "hash": "f0e1d2c3b4a59687"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `annotation_id` | string | 是 | 单书唯一 |
| `target_type` | enum | 是 | `page_block` / `text_span` / `hotspot` / `page_fact` / `qa_card` / `alias` / `scene` / `book` |
| `target_id` | string | 是 | 必须能解析到已有对象 |
| `field` | string | 是 | 被修改的字段名 |
| `value` | any | 是 | 新值 |
| `old_value` | any | 是 | 旧值，便于回滚 |
| `source` | enum | 是 | 固定 `human` |
| `reviewer` | string | 是 | 审核人 |
| `created_at` | string | 是 | ISO 8601 UTC |
| `status` | enum | 是 | `active` / `superseded` |
| `reason` | string/null | 否 | 修正原因 |
| `hash` | string | 是 | 内容哈希 |

规则：

1. auto 记录不可变；人工修正只新增 Annotation，不改原记录。
2. 有效值 = 目标字段 + 最新 `active` Annotation；检索/生成读有效值。
3. 人工修正与自动产物冲突时，进 `conflicts` 队列，不静默覆盖。
4. 每次修正保留版本、审核人、时间、原因；可回滚。

### 7.2 ReviewItem

```json
{
  "review_id": "review-zh-01-001",
  "target_type": "hotspot",
  "target_id": "hotspot-zh-01-002-001",
  "reason": "low_confidence",
  "status": "pending",
  "assignee": null,
  "created_at": "2026-11-17T06:30:00Z",
  "resolved_at": null,
  "notes": "置信度 0.52，需人工确认"
}
```

`reason`：`low_confidence` / `conflict` / `missing` / `generated`。
`status`：`pending` / `accepted` / `rejected` / `edited`。

审核队列按置信度、冲突、缺失生成；审核页支持通过/修改/新建/下一页。审核覆盖率写进 `CapabilityReport`。

## 8. 生成产物

### 8.1 StoryPlan

```json
{
  "schema_version": "2.0.0",
  "book_id": "zh-01",
  "language": "zh-CN",
  "title": "一起搭积木吧",
  "logline": "两个孩子搭起一座九块积木的城堡，在争吵和想念之后重新和好。",
  "characters": [
    {
      "character_id": "char-zh-01-001",
      "name": "小满",
      "aliases": ["满满"],
      "appearance": "扎马尾，粉色连衣裙，圆脸",
      "personality": "急性子，嘴硬心软",
      "voice": "zh-CN-XiaoyiNeural",
      "role": "protagonist"
    }
  ],
  "style_bible": {
    "palette": ["#F4E7C5", "#E8A0A0", "#7FAF9B"],
    "line": "手绘水彩，细线勾边",
    "texture": "纸张纹理，轻微颗粒",
    "reference_pages": [2, 3, 7],
    "negative_prompts": ["照片写实", "3D 渲染", "厚涂"]
  },
  "pages": [
    {
      "page_index": 2,
      "beats": [
        {
          "beat_id": "beat-zh-01-002-01",
          "description": "下雨天，两个孩子在客厅地板上搭积木。",
          "narration": "下雨了，小满和花花只好在家里玩。",
          "dialogues": [{ "speaker": "花花", "text": "我们一起搭城堡，搭高高，还不倒。" }],
          "entities": ["小满", "花花", "积木"],
          "duration_ms": 6000
        }
      ],
      "state_before": "两人刚开始搭积木",
      "state_after": "城堡搭到五块，没有倒"
    }
  ],
  "model": "local-llm",
  "prompt_version": "story-v1",
  "source_hash": "3c1e20ebe8faa734",
  "created_at": "2026-11-17T06:30:00Z"
}
```

`StoryPlan` 是叙事层的唯一来源：角色、风格、逐页旁白/台词、页间状态。所有下游（分镜、视频、TTS、QA）都从它派生。

### 8.2 ScenePlan 与 Scene

```json
{
  "schema_version": "2.0.0",
  "book_id": "zh-01",
  "plan_version": 1,
  "page_map": [
    { "page_index": 2, "scene_ids": ["scene-zh-01-002"], "start_ms": 0, "end_ms": 6000 }
  ],
  "scenes": [
    {
      "scene_id": "scene-zh-01-002",
      "page_index": 2,
      "beat_id": "beat-zh-01-002-01",
      "start_ms": 0,
      "end_ms": 6000,
      "caption": "两个孩子在地板上搭积木，城堡搭到五块还没有倒。",
      "aliases": ["搭积木", "五块积木", "城堡没有倒"],
      "entities": ["小满", "花花", "积木城堡"],
      "action": "两人轮流把积木放上城堡",
      "camera": "从左侧缓慢推近到积木城堡",
      "prompt": "手绘水彩绘本风格，两个女孩在客厅搭积木，暖色，纸张纹理",
      "negative_prompt": "照片写实，3D 渲染，文字变形",
      "keyframe_path": "derived/scene/keyframes/scene-zh-01-002.png",
      "video_path": "derived/video/scene-zh-01-002.mp4",
      "thumbnail_path": "derived/video/thumbs/scene-zh-01-002.jpg",
      "subtitles": [
        { "text": "下雨了，小满和花花只好在家里玩。", "start_ms": 0, "end_ms": 2600, "lang": "zh-CN" }
      ],
      "objects": [
        { "entity": "积木城堡", "bbox_px": [620, 240, 1180, 560], "start_ms": 0, "end_ms": 6000 }
      ],
      "hotspot_ids": ["hotspot-zh-01-002-001"],
      "seed": 20261117,
      "style_score": 0.91,
      "source": "auto",
      "status": "ok"
    }
  ],
  "model": "local-llm",
  "prompt_version": "scene-v1",
  "source_hash": "3c1e20ebe8faa734",
  "created_at": "2026-11-17T06:30:00Z"
}
```

`Scene` 的 `start_ms` / `end_ms`、`subtitles`、`objects` 全部**相对所属页面**，不是整本书。整本时间轴由 `BookGenerationResult` / `timeline.json` 汇总。

| Scene 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `scene_id` | string | 是 | 单书唯一 |
| `page_index` | integer | 是 | 引用已有页面 |
| `beat_id` | string | 是 | 引用 StoryPlan |
| `start_ms` / `end_ms` | integer | 是 | 页内时间；`0 <= start < end <= 页时长` |
| `caption` | string | 是 | 语义检索主描述 |
| `aliases` | string[] | 是 | 至少一条，供 seek 命中 |
| `entities` | string[] | 是 | 画面实体 |
| `action` / `camera` | string | 是 | 动作与镜头描述 |
| `prompt` / `negative_prompt` | string | 是 | 生成提示词 |
| `keyframe_path` / `video_path` / `thumbnail_path` | string | 是 | 包内相对路径 |
| `subtitles` | array | 是 | `{text,start_ms,end_ms,lang}`，供 search/highlight |
| `objects` | array | 是 | `{entity,bbox_px,start_ms,end_ms}`，帧坐标，供 click |
| `hotspot_ids` | string[] | 是 | 引用已有 Hotspot |
| `seed` | integer | 是 | 复现用 |
| `style_score` | number/null | 否 | 0–1，风格闸门评分 |
| `source` | enum | 是 | `auto` / `human` |
| `status` | enum | 是 | `ok` / `fallback` / `failed` |

### 8.3 VideoSegment

```json
{
  "segment_id": "segment-zh-01-002",
  "scene_id": "scene-zh-01-002",
  "page_index": 2,
  "path": "derived/video/scene-zh-01-002.mp4",
  "duration_ms": 6000,
  "width": 1280,
  "height": 720,
  "fps": 24,
  "first_frame_path": "derived/scene/keyframes/scene-zh-01-002.png",
  "last_frame_path": "derived/scene/keyframes/scene-zh-01-002-last.png",
  "model": "page-animation-v1",
  "params": { "camera": "push_in", "parallax": true },
  "seed": 20261117,
  "style_score": 0.91,
  "status": "ok",
  "fallback_reason": null,
  "created_at": "2026-11-17T06:30:00Z"
}
```

`status`：`ok` / `fallback` / `failed`。`fallback_reason` 记录为什么没用 I2V（模型不可用、超时、风格不过等）。

### 8.4 BookGenerationResult

```json
{
  "schema_version": "2.0.0",
  "book_id": "zh-01",
  "generation_version": 1,
  "status": "completed",
  "pages": [
    {
      "page_index": 2,
      "video_path": "derived/video/page-002.mp4",
      "start_ms": 6000,
      "end_ms": 12000,
      "scene_ids": ["scene-zh-01-002"],
      "thumbnail_path": "derived/video/thumbs/page-002.jpg"
    }
  ],
  "full_video_path": "derived/video/book.mp4",
  "subtitle_paths": ["derived/video/subtitles.srt"],
  "audio_paths": ["derived/audio/narration/page-002.wav"],
  "timeline_path": "derived/scene/timeline.json",
  "manifest_path": "derived/manifest.json",
  "metrics": {
    "style_score_avg": 0.9,
    "fallback_pages": 0,
    "qa_cards": 0,
    "duration_ms": 60000
  },
  "model_versions": { "llm": "local-llm-v1", "tts": "edge-tts", "video": "page-animation-v1" },
  "prompt_versions": { "story": "story-v1", "scene": "scene-v1" },
  "created_at": "2026-11-17T06:30:00Z"
}
```

`pages[]` 的 `start_ms` / `end_ms` 是整本视频的绝对时间；`Scene` 内部时间是页内时间。

### 8.5 GenerationManifest 与 Trace

```json
{
  "manifest_id": "manifest-zh-01-001",
  "book_id": "zh-01",
  "generation_version": 1,
  "input_hash": "3c1e20ebe8faa734",
  "contract_version": "2.0.0",
  "stages": [
    {
      "name": "scene",
      "provider": "local",
      "model": "local-llm",
      "model_version": "v1",
      "prompt_version": "scene-v1",
      "params": { "temperature": 0.2 },
      "seed": 20261117,
      "started_at": "2026-11-17T06:30:00Z",
      "duration_ms": 1200,
      "status": "completed",
      "error_code": null,
      "degraded": false,
      "output_hash": "a1b2c3d4e5f60718"
    }
  ],
  "artifacts": [
    { "path": "derived/scene/scene_plan.json", "sha256": "..." }
  ],
  "model_versions": { "llm": "local-llm-v1" },
  "prompt_versions": { "story": "story-v1", "scene": "scene-v1" },
  "created_at": "2026-11-17T06:30:00Z",
  "status": "completed"
}
```

`Trace` 用于在线回答或单次生成的可回放记录：

```json
{
  "trace_id": "trace-20261117-000001",
  "kind": "answer",
  "input": { "book_id": "zh-01", "query_text": "他们在搭什么？" },
  "stages": [
    { "name": "route", "ms": 8, "ok": true },
    { "name": "retrieve", "ms": 42, "ok": true },
    { "name": "tts", "ms": 180, "ok": true }
  ],
  "result": { "tier": "strong", "card_id": "card-zh-01-001" },
  "latency_ms": 230,
  "output_hash": "0c7b1e93aa42f5d8",
  "created_at": "2026-11-17T06:30:00Z"
}
```

## 9. 交互协议

六类交互走同一个入口。默认内部协议如下；官方评测格式如果另有规定，只改适配层，不改业务。

### 9.1 InteractionRequest

```json
{
  "request_id": "req-000001",
  "book_id": "zh-01",
  "session_id": "sess-abc",
  "kind": "auto",
  "input": {
    "text": null,
    "audio_path": "audio/005.wav",
    "audio_url": null,
    "language": null,
    "page_index": 2,
    "current_time_ms": 1500,
    "click": null
  },
  "context": {
    "last_page_index": 2,
    "last_scene_id": "scene-zh-01-002",
    "last_entities": ["积木城堡"],
    "last_lang": "zh",
    "history_turn_ids": []
  }
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `request_id` | string | 否 | 客户端可传；服务端不信任重复值 |
| `book_id` | string | 是 | 引用已有书 |
| `session_id` | string | 是 | 会话 ID |
| `kind` | enum | 是 | `auto` / `control` / `seek` / `search` / `highlight` / `click` / `qa` |
| `input.text` | string/null | 二选一 | 文字输入或 ASR 结果 |
| `input.audio_path` / `audio_url` | string/null | 二选一 | 服务端路径或上传 URL |
| `input.language` | string/null | 否 | 已知语言；未知则检测 |
| `input.page_index` | integer/null | 否 | 当前页 |
| `input.current_time_ms` | integer/null | 否 | 当前播放位置 |
| `input.click` | object/null | `kind=click` 必填 | `{x_px,y_px}` 或 `{x_norm,y_norm}` |
| `context` | object | 否 | 上一轮上下文，帮助消歧 |

### 9.2 InteractionResponse

```json
{
  "request_id": "req-000001",
  "book_id": "zh-01",
  "session_id": "sess-abc",
  "kind": "qa",
  "action": {
    "type": "seek",
    "scene_id": "scene-zh-01-003",
    "time_ms": 2400,
    "span_ids": [],
    "hotspot_id": null
  },
  "answer": {
    "text": "他们在一起搭积木城堡。",
    "audio_path": "derived/audio/answer/card-zh-01-001-zh.wav",
    "language": "zh",
    "tier": "strong",
    "evidence": [
      { "page_index": 3, "bbox_px": [312, 208, 486, 340], "span_id": null, "fact_id": "fact-zh-01-003-001", "quote": "积木城堡没有倒。" }
    ],
    "scene_id": "scene-zh-01-003",
    "time_ms": 2400
  },
  "latency": { "asr": 420, "route": 8, "retrieve": 42, "generate": 0, "tts": 180, "total": 650 },
  "status": "ok",
  "error": null
}
```

`action.type`：`play` / `pause` / `resume` / `stop` / `seek` / `highlight` / `show_card` / `none`。
`answer.tier`：`strong` / `weak` / `quote` / `guide`。
`status`：`ok` / `fallback` / `error`；`error` 为 `{code, message, retryable}`。

`latency` 的统计口径：用户语音结束 → TTS 首音开始；无法拆分的阶段填 `null`。报告只记 p50/p95，不记平均值。

`/api/qa` 作为兼容别名保留：等价于 `kind=qa`，请求/响应字段与 `InteractionRequest/Response` 相同。

### 9.3 Turn

```json
{
  "turn_id": "turn-000001",
  "session_id": "sess-abc",
  "book_id": "zh-01",
  "ts": "2026-11-17T06:30:00Z",
  "input_audio": "audio/005.wav",
  "input_text": "他们在搭什么？",
  "input_image": "derived/frames/req-000001.jpg",
  "kind": "qa",
  "tier": "strong",
  "reply_text": "他们在一起搭积木城堡。",
  "reply_audio": "derived/audio/answer/card-zh-01-001-zh.wav",
  "evidence": [{ "page_index": 3, "bbox_px": [312, 208, 486, 340] }],
  "video_time": 2400,
  "latency": { "asr": 420, "route": 8, "retrieve": 42, "generate": 0, "tts": 180, "total": 650 }
}
```

赛题要求保留包含语音和图片的多模态对话历史；`Turn` 是语义记录，`Trace` 是一次调用的技术记录，两者不能互相替代。

## 10. Job

```json
{
  "job_id": "job-zh-01-20261117-001",
  "book_id": "zh-01",
  "status": "running",
  "stage": "video",
  "progress": 0.45,
  "created_at": "2026-11-17T06:30:00Z",
  "updated_at": "2026-11-17T06:31:20Z",
  "error": null,
  "error_code": null,
  "degraded": false,
  "retryable": true,
  "manifest_path": "derived/manifest.json"
}
```

`status`：`queued` / `running` / `completed` / `failed` / `cancelled` / `degraded`。

`stage`：`ingest` / `ocr` / `vlm` / `story` / `scene` / `video` / `tts` / `compose` / `index`。

| 错误码 | 阶段 | 可重试 | 可降级 |
| --- | --- | --- | --- |
| `INGEST_SOURCE_MISSING` | ingest | 否 | 否 |
| `INGEST_RENDER_FAILED` | ingest | 是 | 否 |
| `OCR_FAILED` | ocr | 是 | 是（标 `needs_vision`） |
| `VLM_FAILED` | vlm | 是 | 是（用文本层/引导） |
| `STORY_FAILED` | story | 是 | 是（用原文旁白） |
| `SCENE_FAILED` | scene | 是 | 是（每页一个 scene） |
| `VIDEO_FAILED` | video | 是 | 是（页动画/静态页） |
| `TTS_FAILED` | tts | 是 | 是（字幕） |
| `COMPOSE_FAILED` | compose | 是 | 是（分段播放） |
| `INDEX_FAILED` | index | 是 | 是（字面检索） |

`progress` 必须是 0–1 的小数。失败时 `error` 必须是可读字符串，不得只返回异常堆栈；`error_code` 用于程序判断。

## 11. CapabilityReport

```json
{
  "schema_version": "2.0.0",
  "book_id": "zh-01",
  "generated_at": "2026-11-17T06:30:00Z",
  "content_type": "narrative",
  "languages": ["zh-CN"],
  "pages_total": 12,
  "pages_with_text": 11,
  "ocr_pages": 0,
  "blocks": 63,
  "hotspots": 28,
  "scenes": 14,
  "videos": 12,
  "qa_cards": 18,
  "coverage": { "text_search": 1.0, "video": 1.0, "qa": 0.36 },
  "needs_review": [
    { "target_type": "hotspot", "target_id": "hotspot-zh-01-007-001", "reason": "low_confidence" }
  ],
  "limitations": ["英文三本故事文字在图里，需要 OCR/VLM", "第 1 页为封面，无文本层"],
  "status": "ready"
}
```

能力报告是“任何书都能通用处理”的诚实边界：告诉用户这本书能查文字、能生成视频、QA 覆盖多少、哪些页需要人工看。

## 12. 评测

### 12.1 EvalCase

```json
{
  "case_id": "case-zh-01-005",
  "book_id": "zh-01",
  "query_set_id": "zh-01-script-v1",
  "number": 5,
  "audio_path": "audio/005.wav",
  "query_text": "他们在搭什么？",
  "kind": "qa",
  "lang": "zh",
  "mandatory": true,
  "expected": { "answer_text": "他们在搭积木城堡。", "card_id": "card-zh-01-001" },
  "notes": null
}
```

### 12.2 EvalRun / EvalResult

```json
{
  "run_id": "run-20261117-001",
  "cases_path": "data/eval/cases.jsonl",
  "book_ids": ["zh-01", "en-01"],
  "model_versions": { "asr": "whisper", "llm": "local-llm-v1" },
  "started_at": "2026-11-17T06:30:00Z",
  "finished_at": "2026-11-17T06:40:00Z",
  "results_path": "runs/run-20261117-001/results.jsonl",
  "metrics": {
    "by_kind": { "control": 1.0, "seek": 0.8, "search": 0.9, "highlight": 0.9, "click": 0.8, "qa": 0.6 },
    "qa_correct": 12,
    "qa_total": 20,
    "evidence_rate": 0.92,
    "p50_ms": 700,
    "p95_ms": 1800,
    "fallback_rate": 0.12,
    "asr_wer": 0.08
  },
  "status": "completed"
}
```

`EvalResult`：

```json
{
  "case_id": "case-zh-01-005",
  "request_id": "req-000001",
  "kind": "qa",
  "status": "ok",
  "verdict": "ok",
  "answer_text": "他们在搭积木城堡。",
  "action": null,
  "scene_id": "scene-zh-01-003",
  "evidence": [{ "page_index": 3, "bbox_px": [312, 208, 486, 340] }],
  "latency_ms": 650,
  "asr_text": "他们在搭什么",
  "notes": null
}
```

`verdict`：`ok` / `wrong` / `miss` / `fallback`。

评测报告必须包含：总分、按 kind 分桶、p50/p95、与上次的差值、所有退化 case 明细。没有明细的总分不算报告。

## 13. 校验规则

- `page_count == len(pages)`。
- `page.index` 从 1 开始且连续。
- `BookPackage` 不得包含 `script_path`、`steps`、`click_targets`；脚本属于 `QuerySet`。
- 无字页：`text` 为空、`text_source=none`、`text_confidence=null`。
- `QuerySet` 的 `number` 唯一；参赛脚本通常 1–50；`audio_path` 可为空。
- 每个 `QueryAction.kind` 必填字段齐全；`click.target` 必须能解析到 Hotspot 或页面文字。
- `PageBlock`、`TextSpan`、`Hotspot` 的 `bbox_px` 必须在页图范围内。
- `confidence` 必须在 0–1；不许全部填 1.0。
- 所有 `page_index`、`hotspot_id`、`span_id`、`scene_id`、`fact_id`、`card_id` 必须能解析到已有对象。
- `QaCard` 必须有 `evidence` 和 `guide`；`variants` 至少 5 条。
- `Narrative` 的 `text` 不能为空；`entities` 必须来自画面可见内容。
- `Annotation.target_id` 必须存在；auto 记录不可变；human 修正 append-only。
- `Scene` 时间必须在页时长内；`VideoSegment` 路径必须存在；`style_score` 0–1。
- `BookGenerationResult.manifest_path` 必须指向有效 manifest；manifest 覆盖所有执行阶段。
- `InteractionRequest/Response` 必填字段齐全；`latency` 非负；`status=error` 时必须有 `error`。
- 所有路径必须是包内相对路径，不允许绝对路径。
- 不允许提交 `source/` 中的授权原始素材；不允许把页面内容、坐标、答案、视频地址写死在代码中。
- 每个顶层 JSON 产物必须有 `schema_version`；JSONL 产物由所属书包的 `book.json` 统一声明版本。

## 14. 兼容与变更

### 14.1 从 1.0.0 迁移到 2.0.0

| 1.0.0 | 2.0.0 |
| --- | --- |
| `BookPackage.pdf_path` | `BookPackage.source_path` + `source_type` |
| `BookPackage.script_path` / `steps` / `click_targets` | 移到 `QuerySet` / `QueryItem` / `QueryAction` |
| `Page.text` 扁平文本 | 保留 `text`，新增 `blocks` |
| `ScriptStep` / `Action` | `QueryItem` / `QueryAction`（`kind` 枚举统一） |
| `Scene.start_ms/end_ms` 相对整本 | 改为相对页面；整本时间由 `BookGenerationResult.pages[]` 汇总 |
| `POST /api/qa` | `POST /api/interact` + `kind=qa`；`/api/qa` 保留兼容别名 |
| 无生成产物 | 新增 `StoryPlan` / `ScenePlan` / `VideoSegment` / `BookGenerationResult` / `GenerationManifest` / `Trace` |
| 无知识层 | 新增 `PageFact` / `QaCard` / `Alias` / `Annotation` / `ReviewItem` |
| 无能力报告 | 新增 `CapabilityReport` |
| 无评测契约 | 新增 `EvalCase` / `EvalRun` / `EvalResult` |

### 14.2 变更规则

- 新增可选字段：提升次版本号，例如 `2.0.0` → `2.1.0`。
- 重命名字段、修改类型、删除字段：提升主版本号，例如 `2.1.0` → `3.0.0`。
- 修改坐标定义、音频规则、时间轴语义、交互协议：按破坏性变更处理。
- 任何契约变更必须同时更新：

```text
docs/DATA_CONTRACT.md
contracts/models.py
backend/app/models.py
后端接口样例
前端类型定义
评测结果读取逻辑
```

- `contracts/` 下的 JSON Schema 与本文同步；校验器以本文为准。

### 14.3 代码落点

本文是契约说明，`contracts/models.py` 是唯一的可执行事实源。改字段先改模型，再改本文。

| 契约小节 | 模型 | 产出文件 | 消费方 |
| --- | --- | --- | --- |
| §3 书 | `BookPackage` / `Page` / `PageBlock` | `data/books/<id>/book.json` | `pipeline/ingest.py`、`backend/app/ingest.py` |
| §5 题目 | `QuerySet` / `QueryItem` / `QueryAction` | `data/books/<id>/query_sets/<id>.json` | `pipeline/query_sets.py`、`backend/app/script_parser.py` |
| §6 知识层 | `PageFact` / `QaCard` / `Alias` / `Narrative` | `data/books/<id>/derived/knowledge/*.jsonl` | 检索与问答 |
| §6.4 叙述 | `Narrative` | `data/books/<id>/derived/understanding/narrative.jsonl` | `pipeline/narrative.py` |
| §7 人工修正 | `Annotation` / `ReviewItem` | `data/books/<id>/manual/annotations.jsonl` | `pipeline/manual.py`、审核页 |
| §8 生成产物 | `StoryPlan` / `ScenePlan` / `Scene` / `VideoSegment` / `BookGenerationResult` / `GenerationManifest` / `Trace` | `data/books/<id>/derived/{story,scene,video}/` | 播放器、`/api/interact` |
| §9 交互协议 | `InteractionRequest` / `InteractionResponse` / `Turn` | 请求响应体 | C 的播放器、`/api/interact` |
| §10 Job | `Job` | `data/jobs/<job_id>.json` | `backend/app/jobs.py` |
| §11 能力报告 | `CapabilityReport` | `data/books/<id>/derived/capability.json` | `/api/books/<id>/capability` |
| §12 评测 | `EvalCase` / `EvalRun` / `EvalResult` | `runs/<run_id>/results.jsonl` | 评测 runner |

前端类型在 `contracts/book_api.ts`，与本文和 `contracts/models.py` 同步维护。

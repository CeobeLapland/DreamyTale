# 进度与中心检查

> 写于 2026-11-21（B）。目的：回答“有没有偏离中心、会不会返工”，不是汇报。
> 目标以 `纸书智伴.md` 和当前 `DATA_CONTRACT.md` 为准。

## 1. 中心是什么

一句话：**任何一本纸质书/PDF 进来，都能变成可播放、可检索、可问答、可人工修正的互动读物。**

四条不能丢：

1. 通用：能力层不认书；六本只是样本，不是规格。
2. 内容：OCR/VLM 把图文变成结构化内容，不是只做问答。
3. 生成：故事 → 分镜 → 视频 → 配音 → 合成，风格一致、页间连贯。
4. 交互：语音/触控六类动作，实时、有证据、可降级。

## 2. 现在在哪

| 赛题要求 | 状态 | 证据 | 还差 |
| --- | --- | --- | --- |
| 内容理解 | **跑通了** | `pipeline/understanding.py`（OCR）+ `pipeline/narrative.py`（VLM）；本地 LM Studio 出真实叙述、实体、可见文字 | `zh-02`“小刺猬”已能搜到（原文在 VLM 可见文字里） |
| 互动视频生成 | **有视频了** | `pipeline/story.py`→`StoryPlan`；`pipeline/scene.py`→`ScenePlan`+`timeline.json`；`pipeline/video.py`→页动画 + `book.mp4`（六本全出） | 配音（Edge TTS 没装成）、I2V 真视频、字幕烧录 |
| 实时交互 | **四类真结果** | `POST /api/interact`：control / search / highlight / seek 出真实结果并带证据 | qa 还没有 QA 卡；click 还没有热点 |
| 多 Agent | 只有架构 | `docs/ARCHITECTURE.md` | 编排器、阶段产物、trace |
| 回答正确率 | 未测 | `derived/coverage_report.json` | QA 卡、评测 runner、真实准确率 |
| 延迟 | 未测 | 交互响应已带 `latency` 分段 | 端到端 p50/p95 |
| 可复现 | 契约级 | manifest 字段、内容哈希 | 实际产物和重跑校验 |
| 人工修正 | **能用了** | `pipeline/manual.py`；`data/books/<id>/manual/narrative.json` | 审核队列、审核页 |
| 通用性 | **六本全跑通** | 同一套命令跑完六本：ingest→ocr→narrative→story→scene→index→video | 新书冷启动实测 |

### 六本书现在的产物

| 书 | 页 | VLM | scene | 时长 | 视频 |
| --- | --- | --- | --- | --- | --- |
| zh-01 | 12 | 12/12 | 13 | 78s | `derived/video/book.mp4` |
| zh-02 | 12 | 12/12 | 12 | 72s | 同上 |
| zh-03 | 12 | 12/12 | 15 | 90s | 同上 |
| en-01 | 28 | 28/28 | 28 | 168s | 同上 |
| en-02 | 28 | 28/28 | 28 | 168s | 同上 |
| en-03 | 28 | 28/28 | 28 | 168s | 同上 |

一页动画（推近/拉远/平移，OpenCV 直出 mp4）约 1 秒，一本书 10–20 秒出片。

### 11-21 这一轮做了什么

1. **合并主干**：把 `origin/main` 和 A 的 `origin/feature/backend-contract-api` 合进 `ceobe-backspace`。
   - 之前 `origin/main` 是**坏的**：`backend/app/ocr_stage.py` import `backend.app.models/store/ocr_results`，
     而这些文件只在 A 那个没合并的分支上，主干后端一 import 就报错。A 今天 19:59 推的“补一下后端没交的文件”
     （21 个文件）就是这个修复。合进来之后主干后端才能跑。
   - 冲突只有 `.gitignore` 和 `docs/DATA_CONTRACT.md`，都以 2.0.0 为准。
2. **契约 v1 → v2 对齐**（这是最大的返工源，已消除）：
   - `contracts/models.py` 补齐 §6–§12 全部模型（`PageFact/QaCard/Alias/Narrative/Annotation/ReviewItem/
     StoryPlan/ScenePlan/Scene/VideoSegment/BookGenerationResult/GenerationManifest/Trace/
     InteractionRequest/Response/Turn/Job/CapabilityReport/EvalCase/EvalRun/EvalResult`）。
   - `backend/app/models.py` 不再自带 dataclass，改为从 `contracts.models` 再导出；校验改用 pydantic。
   - 脚本彻底移出 `book.json`：独立 `QuerySet` 文件，`book.json` 只描述书（§14.1 迁移表）。
   - `contracts/book_api.ts` 同步到 v2，C 可以直接照抄。
   - `backend` 默认书籍根目录改成 `data/books`，和 pipeline 共用同一份 v2 数据（之前 API 看不见 pipeline 的书）。
   - 新增 `POST /api/interact`（`/api/qa` 为兼容别名）、`GET /api/books/{id}/capability`。
3. **VLM 接上本地 LM Studio + 人工兜底**：
   - `pipeline/models/openai_compat.py`：本地端点（127.0.0.1:1234）。三个坑都填了：
     推理模型默认 thinking 会把 token 花光并返回空答案（加 `reasoning_effort=none`，单页 47s → 4s）；
     模型把 JSON 分隔符写成中文引号（改用语法约束解码 `response_format`，另加兜底修复解析器）；
     页图 2600px 全量发太慢（客户端降采样到 1024）。
   - `pipeline/manual.py`：人工修正文件；人工叙述优先于 VLM，自动记录保留为 `superseded`，不覆盖。
   - `python -m pipeline manual --book zh-01` 铺人工修正文件；`python -m pipeline vlm-check --book zh-01 --page 2` 一页一提示词测连通性。
4. **StoryPlan / ScenePlan 落地**（赛题另一半的第一截）：
   - `pipeline/story.py`：书级（logline + 角色 + 画风）一次请求，逐页 beats 每页一次请求。
     小模型擅长答窄问题，所以拆成很多小请求；某页失败或模型没起来时自动降级成“原文旁白”节拍，
     产物永远完整且符合契约（契约里的 `STORY_FAILED → 用原文旁白`）。
   - `pipeline/scene.py`：**不调模型**的确定性阶段。beat → scene：页内时间、字幕（search/highlight 用）、
     seek 别名、物体框（click 用）、视频提示词（画风一致）、seed；外加 `timeline.json` 整本绝对时间轴。
   - 实测 `zh-01`：12 页 → 13 个 scene，总时长 78 秒，0 错误；logline 抓到真实情节
     （搭积木 → 倒塌争吵 → 生日和好 → 搭更高的城堡）。
5. **检索索引 + 交互接上真实数据**：
   - `contracts/retrieval.py`：pipeline 和 backend 共用的检索函数，覆盖率报告和接口不会两套口径。
   - `pipeline/index.py`：OCR 文本层 + VLM 可见文字 + 页面正文 + scene 字幕合成搜索索引，
     另出 scene 索引（别名 + 字幕 + 叙述）。
   - story 阶段额外产出“孩子会怎么说”的中文关键词（“城堡晃动”“两人吵架”），变成 scene 别名，
     官方指令是中文的，英文书也用中文别名。
   - 效果：search/highlight **全中**（含之前唯一缺的“小刺猬”），seek 中文三本 35/36。
6. **视频出片**：
   - `pipeline/video.py`：页动画（推近/拉远/平移）用 OpenCV 直出 mp4，一页约 1 秒；
     六本全部产出 `derived/video/book.mp4`（72–168 秒）+ 每个 scene 的缩略图。
   - 同时产出契约产物 `derived/generation_result.json`（`BookGenerationResult`）和 `derived/manifest.json`
     （`GenerationManifest`，含阶段状态、产物哈希）。
   - `pipeline/tts.py`：Edge TTS 配音（可选）；本机没装成 edge-tts，按契约降级为“只有字幕”。

### 测试现状

```text
python -m pytest backend/tests -q   → 95 passed
python -m pytest tests -q            → 56 passed
python -m pipeline validate          → ok: 6 book(s), 6 query set(s)
```

### 覆盖检查（OCR + VLM + scene 之后）

- 六本 300 个 QueryItem、328 个动作、90 个必选动作。
- control 65/65；search/highlight **37/38 → 全中**（唯一缺的那条“小刺猬”在 VLM 可见文字里，现在能搜到）；
  seek **0/79 → 大部分命中**（中文三本 35/36，英文三本靠中文别名）。
- 剩下的缺口：`qa`（需要 QA 卡 + 检索回答）和 `click`（需要热点坐标，VLM 定位或人工标）。
- 这些数字只代表“能找到文字/时间轴数据”，不代表执行准确率已达标（评测 runner 还没写）。

## 3. 有没有偏离

**没有偏离，而且生成链路已经通了第一遍。**

契约、OCR、VLM 理解、QuerySet 拆分、人工修正、StoryPlan、ScenePlan、页动画视频、检索索引
这一整条都跑通了六本书，不该再回头精修文字层。
**现在还为 0 的是两件事：知识层（QA 卡 + 热点）和评测。** 理由是：

- `qa` 是 117 个动作、占全部动作的三分之一，没有 QA 卡就答不了任何问题。
- `click` 是 28 个动作，VLM 定位或人工标热点才能点。
- 没有评测 runner，0.60 的正确率没法证明。

## 3.1 现在的完整链路

```text
PDF → pages + book.json(v2)          pipeline ingest
    → OCR 文本层 + 坐标                pipeline understand
    → VLM 叙述/实体/可见文字            pipeline narrative   (本地 LM Studio)
    → StoryPlan（角色/梗概/逐页节拍）   pipeline story       (本地 LM Studio)
    → ScenePlan（时间/字幕/别名/提示词） pipeline scene       (确定性)
    → 检索索引 + 场景索引               pipeline index
    → 页动画视频 + book.mp4            pipeline video       (OpenCV)
    → 配音（可选，缺了就是字幕）        pipeline tts         (Edge TTS)
    → 能力报告                          backend /api/books/{id}/capability
    → 交互（control/search/highlight/seek 真实，qa 降级） POST /api/interact
```

## 4. 返工风险

| 风险 | 会怎么返工 | 现在怎么防 |
| --- | --- | --- |
| main 还没人合 | 队友基于坏主干继续写，越走越远 | 已推到 `ceobe-backspace`，代理起来后快进合进 `main` |
| 生成产物没人接 | C 的播放器对着空气写 | `derived/scene/scene_plan.json` + `timeline.json` 已就位，C 可直接接 |
| VLM 一直空着 | 英文叙事、实体、任意点击识别缺内容 | 已接本地 LM Studio；`pipeline models` 一眼看出缺哪环 |
| 本地模型很笨 | 故事/分镜质量不够 | 小请求 + 语法约束 + 人工修正兜底；模型挂了自动降级成原文旁白 |
| 数据只在本地 | A/C 拿不到页图/OCR 结果 | 仓库不提交原书正文，共享走网盘；代码里不写死路径 |
| 没有评测 | 不知道 0.60 到没到，容易自我感觉良好 | Scene/QA 之后立刻接 300 条回放 |
| 没有视频模型 | 质量停在“动态绘本” | 页动画为主、重点页 I2V；ComfyUI 里要自己下视频模型，提前说清 |

## 5. 分工边界（避免撞车）

- **字幕数据**：B 在 `Scene.subtitles` 里产出文本/时间/语言；**C 只负责播放器渲染、开关、样式和同步**；A 负责媒体与接口。B 不做前端字幕组件。
- **审核页**：C 主责 UI；B 提供 `Annotation`/`ReviewItem` 数据和 overlay 图；A 落库和版本化。
- **overlay 图**：`python -m pipeline review --book zh-01 --page 6 --target "我又不是故意的"` 生成本地 PNG，是审核辅助，不是前端页面。
- **契约**：`contracts/models.py` 是唯一事实源，改字段先改模型，再改 `docs/DATA_CONTRACT.md` 和 `contracts/book_api.ts`。
- **人工修正**：只写 `data/books/<id>/manual/`，不直接改自动产物；自动记录保留为 `superseded`。
- **视频生成**：B 写 `pipeline/video.py` 调 ComfyUI，A 接进 job 任务系统；C 只负责播放、字幕同步、状态展示。

## 6. 下一步

1. **知识层 QA 卡**（`PageFact` / `QaCard` / `Alias`）：每页生成问答卡（strong/weak/guide 三档），
   `/api/interact` 的 qa 就能从 fallback 变成真答案 —— 这是 117 个动作的入口。
2. **热点**：VLM 定位（问模型要 bbox，按缩放比例还原到原图坐标）或人工标，解 28 个 click 动作。
3. **评测 runner**：300 条回放、按 kind 分桶、p50/p95、重跑一致，给出真实正确率。
4. **视频升级**：重点页走 ComfyUI I2V（需要先下视频模型），配音补 Edge TTS（需要装 edge-tts）。

## 7. 什么时候需要人

- **已做**：`ceobe-backspace` 已快进合进 `main`（`3bb7f60..cf5d078`），主干后端不再是坏的，契约统一到 v2。
- **已做**：VLM 和故事/分镜都接上本地 LM Studio（`qwen/qwen3.5-9b`，多模态），六本全跑通，视频已出片。
- **现在**：ComfyUI 里下视频模型（LTX-Video 快，Wan2.1 I2V 质量好），否则视频只有页动画。
- **现在**：`pip install edge-tts`（本机装失败了），否则只有字幕没有配音。
- **现在**：告诉 A 和 C：接口按 `contracts/book_api.ts`（v2）接，`/api/interact` 是主入口，`/api/qa` 只是别名；
  播放器按 `derived/scene/scene_plan.json` + `timeline.json` + `derived/video/book.mp4` 做，
  字幕在 `Scene.subtitles`，音频在 `derived/audio/narration/`。
- **后面**：QA 卡、热区的人工抽检；演示视频和说明书。
- **代码上**：暂时不需要你动手，我继续做知识层和评测 runner。

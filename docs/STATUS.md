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
| 内容理解 | 有骨架，VLM 空转 | `pipeline/ingest.py`、`pipeline/understanding.py`、`pipeline/narrative.py`；六本 120 页 OCR 已跑 | 真实 VLM 产出；`zh-02`“小刺猬”未命中 |
| 互动视频生成 | **未开始** | 契约 `StoryPlan/ScenePlan/VideoSegment` 已建模 | 分镜、视频、TTS、合成 |
| 实时交互 | 接口通，模型空 | `POST /api/interact`（`/api/qa` 为别名）；control/search/highlight/click 出真实结果 | qa/seek 需要 ASR + 知识层 + 场景时间轴 |
| 多 Agent | 只有架构 | `docs/ARCHITECTURE.md` | 编排器、阶段产物、trace |
| 回答正确率 | 未测 | `derived/coverage_report.json` | QA 卡、评测 runner、真实准确率 |
| 延迟 | 未测 | 交互响应已带 `latency` 分段 | 端到端 p50/p95 |
| 可复现 | 契约级 | manifest 字段、内容哈希 | 实际产物和重跑校验 |
| 人工修正 | **能用了** | `pipeline/manual.py`；`data/books/<id>/manual/narrative.json` | 审核队列、审核页 |
| 通用性 | 设计+部分代码 | Book/QuerySet 分离、provider 适配层 | 新书冷启动实测 |

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
3. **VLM 走本地 Ollama + 人工兜底**：
   - `pipeline/models/ollama_provider.py`：Ollama 原生 `/api/chat`，图片 + JSON 输出，不出本机。
   - `pipeline/manual.py`：人工修正文件；人工叙述优先于 VLM，自动记录保留为 `superseded`，不覆盖。
   - `python -m pipeline manual --book zh-01` 铺人工修正文件；`python -m pipeline models` 看当前 provider 和失败原因。

### 测试现状

```text
python -m pytest backend/tests -q   → 95 passed
python -m pytest tests -q            → 37 passed
python -m pipeline validate          → ok: 6 book(s), 6 query set(s)
```

### 覆盖检查（OCR 后）

- 六本 300 个 QueryItem、328 个动作、90 个必选动作。
- 现在可解析：control 65/65；search/highlight 37/38；seek 0/79；qa 0/117；click 0/28。
- 唯一缺的文本目标：`zh-02` 第 42 步“小刺猬”。
- 这 37/38 只代表“能找到文字/时间轴数据”，不代表执行准确率已达标。

## 3. 有没有偏离

**没有偏离，而且地基现在只有一份。**

契约、OCR、理解、QuerySet 拆分、人工修正这一层已经做完，不该再回头精修文字层。
**当前唯一还为 0 的，是赛题的另一半：互动视频生成。** 下一阶段必须切到
`StoryPlan → ScenePlan → 视频 → TTS → 合成`，理由是：

- 契约模型已就位，`contracts/models.py` 里 `StoryPlan/ScenePlan/VideoSegment` 都能直接用。
- `Scene` 时间基准已定为“相对页面”，C 的播放器可以先按 mock 数据做。
- 视频不产出来，`seek` 的 79 个动作和 `qa` 的 117 个动作都永远返回不了真实结果。

## 4. 返工风险

| 风险 | 会怎么返工 | 现在怎么防 |
| --- | --- | --- |
| main 还没人合 | 队友基于坏主干继续写，越走越远 | 本轮已把修好的版本推到 `ceobe-backspace`，需要有人把它合进 `main` |
| 生成产物没人接 | C 的播放器对着空气写 | 先给一页 mock `ScenePlan` + timeline，C 能接 |
| VLM 一直空着 | 英文叙事、实体、任意点击识别缺内容 | 本地 Ollama + 人工兜底；`models` 命令能一眼看出缺哪环 |
| 数据只在本地 | A/C 拿不到页图/OCR 结果 | 仓库不提交原书正文，共享走网盘；代码里不写死路径 |
| 没有评测 | 不知道 0.60 到没到，容易自我感觉良好 | Scene/QA 之后立刻接 300 条回放 |
| 没有视频预算 | 质量停在“动态绘本” | 页动画为主、重点页 I2V；提前说清，不画饼 |

## 5. 分工边界（避免撞车）

- **字幕数据**：B 在 `Scene.subtitles` 里产出文本/时间/语言；**C 只负责播放器渲染、开关、样式和同步**；A 负责媒体与接口。B 不做前端字幕组件。
- **审核页**：C 主责 UI；B 提供 `Annotation`/`ReviewItem` 数据和 overlay 图；A 落库和版本化。
- **overlay 图**：`python -m pipeline review --book zh-01 --page 6 --target "我又不是故意的"` 生成本地 PNG，是审核辅助，不是前端页面。
- **契约**：`contracts/models.py` 是唯一事实源，改字段先改模型，再改 `docs/DATA_CONTRACT.md` 和 `contracts/book_api.ts`。
- **人工修正**：只写 `data/books/<id>/manual/`，不直接改自动产物；自动记录保留为 `superseded`。

## 6. 下一步

1. **StoryPlan / ScenePlan**：逐页旁白、scene 时间、字幕、aliases、物体框；先给一页 mock 给 C。
2. **视频/配音/合成**：页动画 + 重点页 I2V + Edge TTS。
3. **知识层**：PageFact / QaCard / Alias + 人工审核，把 `zh-02`“小刺猬”补上。
4. **在线交互**：`/api/interact` 接 ASR、QA 卡检索、场景时间轴。
5. **评测**：300 条回放、按 kind 分桶、p50/p95、重跑一致。

## 7. 什么时候需要人

- **现在**：把 `ceobe-backspace` 合进 `main`（我这边 `git push origin ceobe-backspace:main` 就能快进，但按分工规则应该由 A 或三人确认后再动主干）。
- **现在**：装 Ollama 并拉一个视觉模型（`ollama pull qwen2.5vl:7b`），否则 VLM 一直是空转。
- **后面**：QA 卡、热区、OCR 错字的人工抽检；演示视频和说明书。
- **代码上**：暂时不需要你动手，我继续做 StoryPlan/ScenePlan。

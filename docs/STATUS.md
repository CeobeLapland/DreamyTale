# 进度与中心检查

> 写于 2026-11-24（B）。目的：回答"有没有偏离中心、会不会返工"，不是汇报。
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
| 内容理解 | **跑通** | `pipeline/understanding.py`（OCR）+ `pipeline/narrative.py`（本地 VLM）出页级叙述、实体、可见文字 | 英文书的 visible_text 靠 VLM，质量待人工抽检 |
| 互动视频生成 | **跑通** | `pipeline/story.py`→`ScenePlan`→页动画→`final.py` 字幕+H.264+AAC；edge-tts 旁白与 retime 已生效；六本 `final.mp4` 均为 H.264+AAC（1:54–3:27） | 真正的文生视频（I2V 要火山方舟密钥） |
| 实时交互 | **六类真结果** | `POST /api/interact`：control / search / highlight / seek / qa / click 都返回真实结果与证据；ASR 走本地 faster-whisper，低置信时要求复述；答案 TTS 返回 `answer.audio_path`；官方 click 28/28 | 脚本外物体、TTS 首次合成延迟 |
| 多 Agent | **跑通** | `pipeline/orchestrator.py` 14 阶段（含 Critic）、缓存、manifest、trace；`backend/app/conductor.py` 在线工具注册表与多意图 | 并发执行、ArtDirector 汇总、逐工具 provider/model 记录 |
| 回答正确率 | **能测了** | `pipeline/eval.py` 回放 328 个动作：315/328（96.0%）；qa 116/117，seek 67/79，click 28/28，意图分类 328/328 | qa 的语义对错还要人工抽检；seek 剩余多为抽象目标 |
| 延迟 | 已测 | 语音卡片问答 + 缓存 TTS total 180ms（ASR 179ms）；首次 TTS 合成约 2.4s；服务内分 kind p95：seek 16ms、search 4ms、highlight 3ms、qa 3ms、control/click 0ms | 端到端含前端/媒体未测；LLM+首次 TTS 超 2s |
| 可复现 | 有清单 | `derived/manifest.json`（阶段、哈希、降级原因）；zh-01 14 阶段全链 | 六本重跑一致性的自动校验 |
| 人工修正 | **能用了** | `pipeline/annotations.py` + 阅读器“审核修正”标签：热区/文字块/问答卡、冲突队列、批量 JSON | alias/fact 编辑、字段级回滚 |
| 通用性 | 六本全跑通 | 同一套命令跑完六本；素材路径走环境变量；中文名乱码兜底 | 真·没见过的书冷启动实测 |

### 各人这一段做了什么（都在同一棵树上，没有重复造轮子）

- **A（运行时/平台）**：`backend/app/generation_runner.py` 把内容工厂接进 API job；
  `pipeline/final.py`、`pipeline/retime.py` 做配音重定时与终版合成；
  `pipeline/models/volcengine_i2v.py` 接火山方舟 I2V；`backend/app/knowledge.py` 写 QA 卡匹配器；
  `backend/app/plans.py` 暴露生成产物接口；`backend/app/reader_upload.py` 支持 PDF/ZIP 上传；
  `pipeline/config.py` 让素材路径可配置。
- **C（体验/评测）**：`frontend/` 阅读器初版——书架、上传、任务轮询、视频与逐页播放、字幕（读 `Scene.subtitles`）、
  翻页、文字提问、录音与音频上传、回答音频、浏览器朗读降级、点击识别、结果导出；附 A/B 待办清单。
- **B（内容工厂，本文档作者）**：`contracts/` v2 契约全量模型 + `contracts/retrieval.py` 共用检索；
  `pipeline/` 的 ingest / understanding / narrative / story / scene / index / knowledge / hotspots / video / tts / eval；
  把 `docs/DATA_CONTRACT.md` 变成唯一契约，`backend/` 迁到 v2。

### 评测数字（`python -m pipeline eval --all`，328 个动作打真实服务）

```text
overall        315/328  96.0%（run-20261125-080126）
control        65/65    100%
search         20/20    100%
highlight      19/19    100%
qa             116/117  99%（有答案且有证据；不代表语义正确，需人工抽检）
seek           67/79    84.8%（词面 + 热点页 + 跨语言选页）
click          28/28    100%（文字层 + VLM 定位；重叠框按中心点归属）
routing        328/328  100%（服务端返回 kind 与期望一致）
latency        p50=1ms  p95=10ms（服务内；不含 LLM/ASR）
latency kind   seek p95 16ms / search 4ms / highlight 3ms / qa 3ms / control·click 0ms
必选动作        87/91
```

qa 的 99% 是“不退回引导、且有证据”的比例，不是语义正确率；竞品抽检仍需做。
seek 的 84.8% 里，视觉目标优先复用同一目标的 click 热点页；剩下的 fallback 多是描述里没有的抽象目标。
click 的 28/28 来自本次为官方目标生成的热点；页面里其他未出现在脚本中的物体仍可能点不中。

### 覆盖检查（OCR + VLM + scene 之后）

- control 65/65；search/highlight **全中**（含之前唯一缺的"小刺猬"）；
  seek 大部分命中（中文三本 35/36）。
- click 28/28：文字层能定位的直接用；纯视觉目标先由文本模型跨语言选页，再由 VLM 出框；
  同一页重叠框按点击点到框中心的距离归属。未出现在脚本里的物体仍可能没有热点。

## 3. 有没有偏离

**没有偏离，而且分工现在是清楚的。**

赛题四项里，内容理解、互动视频生成、实时交互都已经在同一条链路上跑出真实产物；
多 Agent 编排也已有 14 阶段编排器、Critic 与在线 Conductor。
剩下的 I2V 真实生成、纯视觉物体定位、评测面板与六本一致性校验是明确的后续，不是返工。

对照赛题原文：

| 赛题核心任务 | 状态 |
| --- | --- |
| (1) 内容理解：OCR/VLM 提取图文与叙事结构 | ✅ |
| (2) 互动视频生成：含文生故事、文生视频、语音，风格一致与页间连贯 | ✅ 故事/分镜/页动画/字幕/旁白有；I2V 按可选接入 |
| (3) 实时交互：语音提问、触控式万物识别 | ✅ 文字六类 + 本地 ASR + 运行时 LLM 兜底；纯视觉物体定位待补 |
| (4) 多 Agent 协同：可编排、可复用 | ✅ 编排器 + Critic + 缓存/manifest/trace + 在线工具注册表 |

**基础门槛**：正确率 ≥0.60 —— 文字回放 315/328（96.0%）；qa 语义对错待人工抽检；
延迟已测；可复现有 manifest 与哈希，缺重跑一致性校验。

**材料清单**：源代码 ✅；5 分钟演示视频 `[部分]`（逐镜脚本 `docs/DEMO_SCRIPT.md`，片待录）；网页 Demo ✅（`frontend/`）；
一键启动与离线说明 ✅（`start.ps1`/`start.bat`，README「一键启动 / 离线说明」）；
项目说明书 `[部分]`（初稿 17 页：`项目说明书_纸书智伴.docx`，待填队伍信息与校对）；数据与模型来源清单 ✅（`docs/MODEL_SOURCES.md`）。

## 4. 现在的完整链路

```text
PDF → pages + book.json(v2)            pipeline ingest
    → OCR 文本层 + 坐标                 pipeline understand
    → VLM 叙述/实体/可见文字             pipeline narrative   (本地 LM Studio)
    → StoryPlan（角色/梗概/逐页节拍）    pipeline story       (本地 LM Studio)
    → ScenePlan（时间/字幕/别名/提示词）  pipeline scene       (确定性)
    → 检索索引 + 场景索引                pipeline index
    → QA 卡（官方问题 → 三档答案）        pipeline knowledge  (本地 LM Studio，可选)
    → 页动画视频                         pipeline video       (OpenCV)
    → 配音重定时 + 字幕烧录              pipeline retime/final (A 做的)
    → 能力报告 / 生成产物 / manifest      backend /api/books/{id}/capability
    → 交互（control/search/highlight/seek/qa 真实，click 降级） POST /api/interact
    → 评测回放（按 kind 分桶 + p50/p95）  pipeline eval
```

## 5. 返工风险

| 风险 | 会怎么返工 | 现在怎么防 |
| --- | --- | --- |
| 契约再变 | 后端/前端/工厂三处都要改 | `contracts/models.py` 唯一事实源，v2 已统一 |
| 两条链路数据打架 | API 看不到工厂产物 | 工厂产物按契约落进包目录，后端按同一路径读 |
| 火山方舟 I2V 花钱/闭源 | 现场跑不起来或材料说不清 | 没密钥自动降级页动画；来源清单已写明调用范围 |
| 模型没开会毁产物 | 降级结果覆盖已跑好的分镜 | `story` 检测到无模型直接跳过；`narrative` 保留旧记录 |
| 没有人工抽检 | 数字好看但答案不对 | qa 语义对错必须人工抽检，评测报告里注明 |
| 数据只在本地 | A/C 拿不到页图/OCR 结果 | 仓库不提交原书正文，共享走网盘；代码里不写死路径 |

## 6. 分工边界（避免撞车）

- **字幕数据**：B 在 `Scene.subtitles` 里产出文本/时间/语言；**C 只负责播放器渲染、开关、样式和同步**；A 负责媒体与接口。B 不做前端字幕组件。
- **审核页**：C 主责 UI；B 提供 `Annotation`/`ReviewItem` 数据和 overlay 图；A 落库和版本化。
- **overlay 图**：`python -m pipeline review --book zh-01 --page 6 --target "我又不是故意的"` 生成本地 PNG，是审核辅助，不是前端页面。
- **契约**：`contracts/models.py` 是唯一事实源，改字段先改模型，再改 `docs/DATA_CONTRACT.md` 和 `contracts/book_api.ts`。
- **检索逻辑**：`contracts/retrieval.py` 是 pipeline 与 backend 共用的唯一实现，覆盖率报告和接口不会两套口径。
- **QA 卡**：B 出草稿（`pipeline/knowledge.py` → `derived/knowledge/cards.jsonl`），A 的运行时直接消费；人工审核在 `data/books/<id>/manual/`。
- **评测**：`pipeline/eval.py` 出回放结果与指标（契约 §12 的 `EvalRun`/`EvalResult`）；C 做评测面板与结果展示。

## 7. 下一步

1. **开模型补齐 qa 与 click**：`python -m pipeline knowledge --all --use-llm`（117 条问题全覆盖，约 12 分钟）
   和 `python -m pipeline hotspots --all --use-vlm`（纯视觉物体定位）。现在是 74 张卡、12 个热点。
2. **ASR**：A 接适配器到 `/api/interact/audio`，B 供模型与提示词；打通"孩子说话→系统回答"。
3. **多 Agent 编排**：把现有阶段做成可编排、可重试、可追溯的任务链（阶段产物 + trace）。
4. **说明书（≤20 页）+ 评测面板**：把 `runs/` 的回放结果做成可展示的报告。

## 8. 什么时候需要人

- **已做**：主干后端可运行、契约统一到 v2、六本全链路跑通并出片、前端初版可运行、
  评测回放 315/328（96.0%）、来源清单、一键启动与离线说明都已就位。
- **现在**：演示前开着 LM Studio（无卡问答与视觉热点定位用）；语音/旁白依赖已经装好。
- **现在**：要真跑 I2V 就给火山方舟 `ARK_API_KEY`（要钱、调用范围已写进来源清单）；否则用队友好外部成片做视频变体。
- **后面**：QA 卡语义对错的人工抽检；说明书与演示视频。
- **代码上**：暂时不需要你动手，我继续做多 Agent 编排与说明书素材。

# 系统架构

> 目标：任何一本纸质书/PDF 进来，都能变成可播放、可检索、可问答、可人工修正的互动读物。
> 本文讲“怎么搭”。字段定义以 `DATA_CONTRACT.md` 为准；两份冲突时，契约优先。

## 1. 产品边界

**做什么**

- 书页理解：文本层 / OCR / VLM，block 级内容、阅读顺序、叙事结构。
- 互动视频：以原书页为视觉锚的页动画 + 重点页 I2V，风格一致、页间连贯。
- 实时交互：语音与触控，六类动作（control / seek / search / highlight / click / qa），答案带证据。
- 多 Agent 生产链：可编排、可复用、可复现。
- 人工修正：自动产物可审核、可覆盖、可回滚。

**不做什么**

- 不做无边界的通用聊天。
- 不做实时文生视频；生成全部在离线链。
- 不做“只针对这六本书”的查表应答。
- 不做社交、账号、创作平台。

**通用性三条**

1. **能力层不认书。** 代码里不出现书名、页号、角色名、答案；六类交互只依赖契约。
2. **知识层按书生成。** 任何书都走同一套 schema 和同一条管线；质量可以不同，流程必须相同。
3. **没有脚本也能跑。** 命题组脚本是评测/交互集，不是书的一部分；新书没有 50 条脚本，系统照样要能理解、生成、问答。

## 2. 两条主链

```
离线（每本书一次）
PDF/照片 → 页图 → 内容理解 → 故事 → 分镜/时间轴 → 视频 → 配音 → 合成 → 索引/知识 → 能力报告
                                      ↓
                                 人工审核/修正
                                      ↓
在线（每次交互）
麦克风/点击 → ASR/事件 → 路由 → 检索/执行 → TTS/播放器动作 → 多模态历史
```

两条链只通过契约连接：

```text
BookPackage + QuerySet
  → PageBlock / TextSpan / Hotspot
  → PageFact / QaCard / Alias
  → StoryPlan → ScenePlan → VideoSegment / BookGenerationResult
  → InteractionRequest / InteractionResponse
  → EvalCase / EvalRun
```

## 3. 离线内容工厂

### 3.1 阶段

| 阶段 | 输入 | 输出 | 失败时 |
| --- | --- | --- | --- |
| ingest | PDF/照片 | `BookPackage`、页图、source 快照 | 报 `INGEST_*`，保留原文件 |
| understand | 页图 + 文本层 | `PageBlock`、`TextSpan`、`PageFact`、`Hotspot`、narrative | 降级到纯页图；标 `needs_vision` |
| story | 页面内容 | `StoryPlan`（角色、逐页旁白、beat） | 直接使用原书文字作旁白 |
| scene | StoryPlan + 页面布局 | `ScenePlan`（scene、时间、字幕、aliases、物体框） | 每页一个 scene，均分时长 |
| video | ScenePlan + 页图 | `VideoSegment`、`BookGenerationResult` | 回退页动画或静态页 |
| voice | 旁白/台词 | 音频文件 + 时间轴 | 回退字幕，不阻塞播放 |
| compose | 视频 + 音频 | 每页/整本 MP4、字幕、缩略图 | 保留分段，前端按段播放 |
| index | 全部文本/场景/卡片 | 检索索引、`CapabilityReport` | 只做字面检索 |

每个阶段都必须：幂等、可单独重跑、输出落盘、记录耗时/模型/提示词版本/错误码。

### 3.2 多 Agent 编排

不是让几个 Agent 聊天，是一条**确定性 DAG**。每个 Agent 只交接结构化产物：

| Agent | 职责 | 产物 |
| --- | --- | --- |
| Librarian | 导入、拆页、版权/来源记录 | `BookPackage`、页图 |
| Reader | 文本层/OCR/VLM、block 与实体 | `PageBlock`、`PageFact`、narrative |
| Storyteller | 角色 bible、逐页旁白、beat | `StoryPlan` |
| Director | 分镜、时间、字幕、aliases、物体框 | `ScenePlan` |
| ArtDirector | 风格 bible、提示词、关键帧 | prompts、keyframes |
| Animator | 页动画 / I2V、风格闸门 | `VideoSegment` |
| VoiceActor | TTS、音色、字幕对齐 | 音频、字幕 |
| Critic | 风格/安全/文字准确性/连贯性检查 | 评分、打回原因 |
| Curator | 事实、QA 卡、别名、索引、能力报告 | 知识库、`CapabilityReport` |

编排器负责：阶段注册、依赖顺序、重试、缓存、超时、并发、全链 trace。换一本书只换输入和配置，不改图。

### 3.3 模型适配层

业务代码不直接调 SDK。所有模型能力走统一接口：

```text
LLM       chat(messages, schema, stream) -> text/json
VLM       describe(image, prompt) -> text/json
OCR       extract(image) -> blocks[]
ASR       transcribe(audio) -> text, segments, lang, confidence
TTS       synthesize(text, voice, lang) -> audio
I2V       animate(image, prompt, duration, seed) -> video
Embedding embed(texts) -> vectors
```

`config/models.yaml` 描述 provider、model、base_url、key_env、timeout、retry、并发、成本。支持本地（Ollama/LM Studio/vLLM、faster-whisper、Edge TTS、diffusers）与远程（OpenAI 兼容、云视频 API）两种实现。

当前默认：OCR = `rapidocr`（本地免费），VLM = `null`（配置本地或远程视觉模型后启用）。`python -m pipeline models` 查看当前生效的提供方。

**没有预算时先用本地/免费栈**：Edge TTS、Whisper、本地 LLM/VLM、2.5D 页动画；适配层保证以后换 API 不改业务。

### 3.4 通用性处理

- **按页判断文本层**，不是按书：有文本层直接抽；没有才 OCR；两者都失败标 `needs_vision`，不假装读过。
- **文本层不等于完整**：插画里的手写对白、拟声字、特别排版可能不在 PDF 文本层。例：`zh-01` 第 6 页的“我又不是故意的”在插图里，必须 OCR/VLM 按页/区域补。覆盖检查要能列出这些未命中目标。
- **OCR 去重与去水印**：与 PDF 文本重叠的识别结果直接丢弃；栅格化水印按 `config/models.yaml` 的 `watermark_phrases` 过滤。OCR 结果写 `source: ocr`，与 PDF 文本共存为 `text_source: mixed`。
- **内容类型**：`narrative` 走故事/分镜/视频；`expository` 走概念/段落/公式，视频可选；`mixed` 按页决定。
- **水印/页眉页脚/教学辅助文字**：用“同一段文字出现在 50% 以上页面”等规则过滤；`note` 类型单独保留，供阅读指导用，不混进故事问答。
- **能力报告**：每本书跑完输出“能查文字/能生成视频/QA 覆盖多少/哪些页需要人工看”，让系统对自己的边界诚实。

### 3.5 人工修正层

自动产物不能直接当最终数据。规则：

1. 自动产物写 `source: auto`、`confidence`；人工修改写 `source: human`，旧版本标 `superseded`，auto 保留。
2. 低置信度、自动与人工冲突、缺失项进入审核队列。
3. 审核页：页面图 + 叠框，支持改文字、标签、bbox、答案、aliases，键盘快捷键（通过/修改/新建/下一页）。
4. 人工优先于自动，但自动不丢；检索时 human 命中优先，auto 兜底。
5. 修正记录 append-only，可回滚、可审计。

### 3.6 视频策略

- **主路径**：以原书页/关键帧为视觉锚。原图保证风格；镜头运动、分层视差、转场、字幕、局部动效负责“动起来”。
- **增强**：重点页用 I2V，第一帧用原页裁切，提示词带风格 bible；风格闸门（CLIP/SSIM/颜色直方图）不达标就重生成或回退页动画。
- **不做全量从零文生视频**：风格会飘、成本不可控、不可复现。
- **合成**：ffmpeg 统一输出 H.264/AAC、faststart；每页一段 + 整本一条；字幕轨与语义时间轴同源。

### 3.7 语音

- 旁白/台词预生成，按角色分配音色；字幕与音频对齐。
- 已知问答的答案音频预生成；动态答案流式 TTS，首句先出。
- ASR 支持中英混说；低置信度时确认，不硬猜。

### 3.8 质量与复现

- **Manifest**：输入哈希、模型/提示词版本、参数、seed、每阶段耗时与输出哈希。
- **缓存**：按内容哈希缓存模型调用与生成产物；同输入重跑应命中缓存或产出相同结果。
- **风格闸门**：生成帧与原书页的相似度评分，低于阈值打回。
- **质量指标**：OCR 置信度、QA 覆盖率、证据完整率、风格相似度、p50/p95 延迟。

## 4. 在线交互

### 4.1 会话状态

```text
book_id, page_index, current_time_ms, play_state,
last_scene_id, last_entities[], last_lang, history[]
```

翻页是最高优先级事件：清 seek 状态，跳到新页起点。seek 成功后，后续 qa 默认限定在当前 scene/页附近，答不到再退全书。

### 4.2 链路

```text
音频/文字/点击
  → ASR（音频）
  → 语言检测
  → 路由（六类）
  → 执行：播放器控制 / scene 定位 / 字幕检索 / 热区命中 / 知识检索
  → 响应：action + answer + evidence + latency
  → TTS（答案）
  → Turn 落盘
```

### 4.3 六类动作

| kind | 做什么 | 依赖 |
| --- | --- | --- |
| control | 播放/暂停/继续/结束 | 播放器状态 |
| seek | 跳到某个语义画面 | Scene 时间轴 + aliases |
| search | 在字幕/页面文字中查找 | TextSpan / 字幕轨 |
| highlight | 高亮文字或对象 | TextSpan / Hotspot |
| click | 点击对象展示信息卡 | Hotspot + 页面/帧坐标 |
| qa | 回答问题 | PageFact / QaCard / 检索 |

路由先分类再检索；误分类比检索不中更致命。规则 + 小模型即可，带上下文（上一句 kind/entities）。

### 4.4 延迟预算

| 环节 | 目标 |
| --- | --- |
| ASR | 300–800ms |
| 路由 | < 20ms |
| 检索 | < 100ms |
| 答案（预置卡） | < 100ms |
| 答案（LLM 兜底） | 1–2s，流式 |
| TTS 首音（预生成） | < 100ms |
| TTS 首音（流式） | 300–800ms |
| 总 p95 | < 2s；控制类 < 200ms |

### 4.5 失败降级

```text
页识别不确定 → 候选页/手动选页
ASR 低置信 → 复述确认
seek 无命中 → 当前页/全书候选
qa 无命中 → 引用原句 → 引导（承认 + 翻页 + 反问）
视频缺失 → 静态页 + 字幕
模型不可用 → 缓存/规则路径，绝不空答
```

## 5. 知识层

- **PageFact**：实体、属性、关系、bbox、证据。
- **QaCard**：标准问法、变体、三档答案、证据、视频锚点、语言。
- **Alias**：角色昵称、颜色/方位指代。
- **检索**：字面 + 拼音 → 向量 → 结构化过滤；重排后分档。
- **答案**：strong（卡命中，不改写）/ weak（要点 + LLM 组织）/ guide（承认 + 翻页 + 反问）。
- **证据**：page_index + bbox + span/fact + scene/time，前端可点“依据”高亮。
- **语言**：答案跟提问语言；中英混问都支持。

## 6. 评测

- 默认协议：内部 `InteractionRequest/Response` + JSONL 回放；官方格式以后只改 `adapters/`。
- 用例：`QuerySet` + 音频；QA 的参考答案由自动草稿 + 人工审核产生。
- 指标：分类准确率、执行准确率、QA 正确率、证据完整率、p50/p95、降级率、ASR WER。
- 报告：按 kind 分桶，列出所有退化 case；没有明细的总分不算报告。

## 7. 目录与运行时

```text
backend/        API、任务、媒体、适配器
pipeline/       内容工厂、阶段编排、生成
prompts/        可版本化提示词
contracts/      JSON Schema、校验器、样例
frontend/       阅读器、审核页、评测面板
evaluation/     评测脚本、结果、演示素材
data/books/     单书数据包（source 不入 Git，媒体缓存不入 Git）
docs/           架构、契约、决策
```

运行时本地优先：FastAPI + 静态前端 + 本地模型/Edge TTS；所有媒体本地可播，断网能走完主流程。

## 8. 关键决策

1. **页图是视觉锚。** 视频从原页出发，不从零生成；风格一致性和可复现都靠它。
2. **语义时间轴在生成时产出。** 不做视频理解；seek/search/highlight/click 全走结构化数据。
3. **实时不生成。** 生成全部离线；在线只做 ASR、路由、检索、TTS。
4. **书与题目分离。** 脚本是 QuerySet，不是 Book 的必填字段；没有脚本的书也能跑。
5. **人工修正是一等公民。** 自动 + 人工双源，human 优先、auto 保留、冲突进队列。
6. **默认协议自持。** 官方没给格式就自己定；业务只依赖内部契约，官方格式走适配层。

## 9. 分工与产物所有权（建议）

当前 `TEAM_DIVISION.md` 按代码目录分人，实际执行容易互相等。建议改成按产物分：

| 角色 | 主责产物 | 不主责 |
| --- | --- | --- |
| A · 运行时/平台 | `backend/`、API、Job、媒体、适配器、评测 runner、启动 | 生成质量、知识内容 |
| B · 内容工厂 | `pipeline/`、`prompts/`、`data/books/*/derived`、生成质量、知识自动草稿 | 前端主体验、任务队列 |
| C · 体验/审核/评测 | `frontend/`、审核页、评测面板、演示视频 | 模型调用、生成适配器 |

三个真正的耦合点：

1. `BookPackage` + 媒体路径：A ↔ B ↔ C；
2. `Scene` 时间轴：B ↔ C；
3. `Interaction` 协议：A ↔ B ↔ C。

这三处由契约定死，其余并行。B 兜底“卡住链路”的部分（导入器、API 骨架、审核页），但完整前端和任务队列仍由 A/C 主责，避免三人撞车。

## 10. 质量预期

- **系统完整**：任意 PDF 能进；六类交互可用；人工能改；能评测、能复现。
- **质量分层**：重点书精修，其他书自动跑出可用结果；不承诺每本都达到动画电影级。
- **视频上限**：没有模型/算力预算时，停在“动态绘本”级；有 I2V 资源再提升重点页。

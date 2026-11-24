# 剩余工作总清单（按文档逐条对照）

> 依据：`纸书智伴.md`、`docs/ARCHITECTURE.md`、`docs/DATA_CONTRACT.md`、
> `docs/MODEL_SOURCES.md`、`docs/STATUS.md`、`docs/TEAM_DIVISION.md`、
> `docs/HANDOFF.md`、`README.md`。
>
> 目的：把“赛题要求 / 架构要求 / 契约要求”全部摊开，逐条对照代码与产物，
> 不再靠口头提醒。每一条都写：现状、缺口、下一步、验收、负责人。
>
> 状态：
> - `[完成]` 有代码、有产物、有测试或实测证据
> - `[部分]` 能跑，但只覆盖一部分或不满足契约
> - `[未做]` 没有实现、没有产物或没有验证
>
> 负责人：A = 运行时/平台；B = 内容工厂/契约；C = 前端/评测；三人 = 需共同确认。

---

## 0. 赛题硬门槛（`纸书智伴.md`）

| ID | 要求 | 现状 | 缺口 / 下一步 | 验收 | 负责人 |
| --- | --- | --- | --- | --- | --- |
| S0-1 | 系统可运行 | `[完成]` API 8000、阅读器 `/reader/`、生成任务可提交 | 需要一键启动脚本与离线启动说明 | 断网、冷启动能打开阅读器并完成一次文字问答 | A |
| S0-2 | 四项核心任务均完成 | `[部分]` 1 部分、2 部分、3 部分、4 未做 | 见第 1–4 节 | 四项都能现场演示 | 三人 |
| S0-3 | 回答正确率 ≥0.60 | `[部分]` 文字回放 218/328；qa 76/117；音频回放 qa 74/117 | qa 语义对错没人工抽检；任意问题答不上 | 官方 qa 抽检通过；任意书内问题能答或引导 | B/C |
| S0-4 | 交互延迟达门槛 | `[部分]` 语音总 p50 647ms / p95 750ms；服务内检索 p95 约 5ms | 控制类 <200ms、端到端含前端/媒体未测 | 报告给出分 kind 的 p50/p95 与端到端数据 | A/C |
| S0-5 | 关键生成内容可复现 | `[部分]` 有 `generation_result.json`、单阶段 `manifest.json` | 没有全阶段 manifest、没有缓存、没有重跑一致性校验 | 删一个阶段产物，重跑只补该阶段；同输入命中缓存 | B |
| S0-6 | 5 分钟演示视频 | `[未做]` 六本 `book.mp4` 可剪，但没有录 | 按官方 50 步脚本录一条完整 Demo | 5 分钟内展示生成、语音、点击、问答、证据 | C |
| S0-7 | 项目说明书 ≤20 页 | `[未做]` | 按模板写需求/架构/算法/数据来源/功能/测试/局限 | 20 页内，含四项任务与指标 | 三人 |
| S0-8 | 源代码/关键流程配置 | `[部分]` 代码齐全 | 缺一键启动、第三方闭源服务调用范围说明 | 评委能按 README 跑起来 | A |
| S0-9 | 来源清单 + IP 承诺 | `[部分]` `docs/MODEL_SOURCES.md` 已有 | 未列 faster-whisper/ASR 模型；未列演示用三方 API | 每个模型/API 有许可、用途、是否出本机 | 三人 |

---

## 1. 内容理解（赛题任务 1）

| ID | 要求（来源） | 现状 | 缺口 / 下一步 | 验收 | 负责人 |
| --- | --- | --- | --- | --- | --- |
| I-1 | PDF 入库、拆页、页图（ARCH §3.1） | `[完成]` `pipeline/ingest.py`、`book.json` | 无 | 新 PDF 能进、页数正确 | B |
| I-2 | 照片/扫描件入库（ARCH §1、DATA §3 `source_type`） | `[未做]` 只有 PDF | 增加图片目录/逐页照片入库 | 一组 JPG 能生成 `source_type=photo` 的书 | B |
| I-3 | 页级文本层判断（ARCH §3.4） | `[完成]` 有文本层直接抽，无字页标 `none` | 需抽检 `text_source` 准确性 | 无字页不伪造文字 | B |
| I-4 | OCR + 坐标（ARCH §3.1） | `[完成]` RapidOCR，`PageBlock/TextSpan` | 英文书 visible_text 质量待抽检 | OCR 结果能叠框核对 | B |
| I-5 | OCR 去重/去水印（ARCH §3.4） | `[部分]` 有水印短语过滤 | 需验证与 PDF 文本重叠去重 | 水印不进入正文与字幕 | B |
| I-6 | block 类型/阅读顺序（DATA §4.2） | `[部分]` `blocks.jsonl` 存在 | 需核对 `title/body/note/header/footer` 分类 | 阅读顺序与页图一致 | B |
| I-7 | VLM 页叙述/实体/可见文字（ARCH §3.1） | `[部分]` `narrative.jsonl` 有六本 | LM Studio 未开；质量未人工抽检 | 抽检 20 页，叙述只写画面可见内容 | B |
| I-8 | 页级人工叙述修正（ARCH §3.5） | `[完成]` `manual/narrative.json` 被 narrative/story 读取 | 需补“人工修正覆盖率”报告 | 改一页叙述，下游重建 | B |
| I-9 | 内容类型 narrative/expository/mixed（ARCH §3.4） | `[部分]` 只跑 narrative | 说明型书的段落/概念/公式未实现 | 一本说明型 PDF 能出结构，视频可选 | B |
| I-10 | 页眉/页脚/教学 note 过滤（ARCH §3.4） | `[部分]` 有规则与 `note` 类型 | 需抽检：note 不混进故事问答 | 故事问答不引用页眉页脚 | B |
| I-11 | 覆盖检查（ARCH §3.4） | `[完成]` `pipeline/coverage.py` | 需把“未命中目标”写进报告 | 报告列出缺 OCR/VLM/场景/热区的目标 | B |
| I-12 | 能力报告（ARCH §3.4、DATA §11） | `[完成]` `/api/books/{id}/capability` | 需补 review 覆盖率、模型版本 | 每本书能说清“会什么/不会什么” | A/B |
| I-13 | OCR/VLM 人工抽检 | `[未做]` | 六本各抽若干页，记录错误 | 抽检记录与修正进入 `manual/` | B/C |
| I-14 | PageFact（DATA §6.1） | `[未做]` `derived/knowledge/facts.jsonl` 不存在 | 从叙述/OCR 抽实体、属性、关系、bbox | 每页至少一条可引用 fact | B |
| I-15 | Alias（DATA §6.3） | `[未做]` `derived/knowledge/aliases.json` 不存在 | 角色昵称、颜色/方位指代 | 每张卡至少挂 3 条别名 | B |
| I-16 | Hotspot 原始文件（DATA §2、§4.4） | `[部分]` 热区在 `book.json`，`hotspots.jsonl` 不存在 | 按契约落 `derived/understanding/hotspots.jsonl` | 文件存在且与 book.json 一致 | B |

---

## 2. 互动视频生成（赛题任务 2）

| ID | 要求（来源） | 现状 | 缺口 / 下一步 | 验收 | 负责人 |
| --- | --- | --- | --- | --- | --- |
| V-1 | StoryPlan（角色/旁白/beat，ARCH §3.1） | `[完成]` 六本有 `story_plan.json` | 需人工抽检角色/旁白质量 | 每页有旁白与 beat | B |
| V-2 | ScenePlan + timeline + subtitles（ARCH §3.1） | `[完成]` 六本有 `scene_plan.json`、`timeline.json` | 需检查字幕与页时长连续性 | 字幕不越界、不空洞 | B/C |
| V-3 | aliases/objects/hotspot_ids（DATA §8.2） | `[部分]` aliases 有；`objects` 与 `hotspot_ids` 为 0 | 把页内物体框与热区写进 Scene | 视频帧上能点物体 | B |
| V-4 | 页动画视频（ARCH §3.6） | `[完成]` 六本 `book.mp4`、分段 mp4 | 无 | 可播放、页间连贯 | B |
| V-5 | 重点页 I2V（ARCH §3.6） | `[部分]` 适配器与配置在，无密钥/模型 | 决定是否启用火山方舟或本地视频模型 | 重点页有 I2V 或明确降级原因 | B/A |
| V-6 | 风格 bible/提示词/关键帧（ARCH §3.2） | `[部分]` 风格在 StoryPlan、prompt 在 ScenePlan、keyframes 有 | 需要 ArtDirector 阶段汇总与校验 | `derived/art/art_direction.json` 完整 | B |
| V-7 | 风格闸门（SSIM/颜色直方图/CLIP，ARCH §3.6） | `[未做]` `style_score` 为空 | 实现每页首帧与原页图相似度评分 | 报告给出平均分与最低页 | B |
| V-8 | 旁白/台词 TTS（ARCH §3.7） | `[完成]` edge-tts 已接入；六本共 120 页旁白（中文 12×3，英文 28×3） | 无 | 六本有旁白音轨 | B |
| V-9 | 音频重定时/字幕对齐（ARCH §3.7） | `[完成]` `pipeline/retime.py` 按音轨重定时，各本 changed=8–18 页 | 无 | 字幕与音频时间一致 | B |
| V-10 | 终版合成 H.264/AAC/faststart（ARCH §3.6） | `[完成]` 六本 `final.mp4` 均为 H.264 High + AAC，时长 1:54–3:27 | 无 | `final.mp4` 同时有画面、字幕、声音 | A/B |
| V-11 | 每页一段 + 整本一条（ARCH §3.6） | `[完成]` 分段与整本都有 | 无 | 前端可按段或整本播 | B/C |
| V-12 | SRT 字幕（ARCH §3.6） | `[完成]` 六本 `subtitles.srt` | 无 | 字幕可独立加载 | B/C |
| V-13 | 页间连贯检查（ARCH §3.2 Critic） | `[未做]` | 检查相邻页 caption/角色/场景连续性 | 报告列出不连贯页 | B |
| V-14 | 视频内动态对象点击（C README） | `[未做]` Scene `objects` 为空 | 物体框随时间轴移动，前端按帧命中 | 视频播放中能点中移动物体 | B/C |
| V-15 | 播放器（C） | `[完成]` 视频/逐页/原图/字幕/翻页 | 无 | 浏览器可完整阅读 | C |
| V-16 | 5 分钟演示视频 | `[未做]` | 见 S0-6 | 见 S0-6 | C |

---

## 3. 实时交互（赛题任务 3）

| ID | 要求（来源） | 现状 | 缺口 / 下一步 | 验收 | 负责人 |
| --- | --- | --- | --- | --- | --- |
| R-1 | 六类动作（ARCH §4.3） | `[部分]` control/seek/search/highlight/qa 真实；click 部分 | 补齐 click 与动态物体 | 六类现场可用 | A/B/C |
| R-2 | 语音提问（赛题任务 3） | `[完成]` faster-whisper large-v3，本地 GPU | 模型/路径写进来源清单 | 300 条官方 WAV 可回放 | B |
| R-3 | 中英混说（ARCH §3.7） | `[部分]` 实测中英夹说可用 | 需低置信度复述确认 | 低置信不硬猜 | B |
| R-4 | ASR 低置信确认（ARCH §4.5） | `[未做]` | 用置信度/二次确认 | 低置信时让用户复述 | A/B |
| R-5 | 意图路由（ARCH §4.3） | `[部分]` 规则分类；Conductor 已能拆分“先……然后……”多意图 | 模糊句、上下文消歧未做 | “先找画面再问为什么”可执行 | A/B |
| R-6 | 会话状态（ARCH §4.1） | `[部分]` C 传 page/time/history；后端只记上一轮检索目标 | 缺 `last_scene_id/last_entities/last_lang` 持久化 | 多轮指代可用 | A |
| R-7 | 翻页优先/seek 后限定场景（ARCH §4.1） | `[部分]` Conductor 把 seek 落点页传给后续问答；卡片检索仍全书 | 问答卡按当前场景过滤 | 跳页后问答不串页 | A |
| R-8 | 答案 TTS（ARCH §4.2） | `[部分]` C 浏览器朗读降级；无服务端 `answer.audio_path` | 接 TTS，返回音频路径 | 回答可听、可续播 | B/C |
| R-9 | 证据展示/点击“依据”（ARCH §5） | `[完成]` 回答带依据 chip；点击翻到证据页并画 bbox 框，文字证据也能用 span 拼出框 | 无 | 答案旁能点“依据” | C |
| R-10 | 触控万物识别（赛题任务 3） | `[部分]` 文字层热区可用；纯视觉物体缺 | VLM 定位物体 bbox，扩大热区 | 官方 click 目标全命中 | B |
| R-11 | 视频内动态对象点击 | `[未做]` | 见 V-14 | 见 V-14 | B/C |
| R-12 | 运行时 LLM 兜底（ARCH §5 `weak`） | `[完成]` `backend/app/llm_answer.py`；Qwen3.5-9B 本机；证据约束 | 无 | 没卡的问题也能答 | A/B |
| R-13 | 任意书内问题 | `[部分]` 可回答的问题已带证据；假前提/无依据退回 guide | 需要抽检更多书 | 任意问题有答案或引导 | A/B |
| R-14 | 多模态对话历史（赛题任务 3、DATA §9.3 Turn） | `[完成]` 每轮写 `data/turns/<date>.jsonl`；刷新后用同一 session 回放 | 图片输入仍未产生 Turn 字段 | 刷新后历史可回放 | A |
| R-15 | 交互 Trace（DATA §8.5） | `[完成]` 每轮写 `data/traces/<date>/<request_id>.json`，含 route/tool 阶段与耗时 | 无 | 每次回答可审计 | A |
| R-16 | 延迟预算（ARCH §4.4） | `[部分]` 文字问答 0.46–2.6s；语音实测：control 353ms、卡片问答 260ms（ASR 252ms）；LLM 兜底语音约 1.5s | 还没有分 kind 的 p50/p95 报告 | 分 kind 报告达标 | A/C |
| R-17 | 失败降级（ARCH §4.5） | `[完成]` qa/seek/click 有 guide/fallback | 低置信 ASR、页识别不确定未做 | 不空答、不假装成功 | A/B |
| R-18 | 禁止无边界聊天（ARCH §1） | `[完成]` 没有开放聊天 | 保持 | 只答书内内容 | A/B |
| R-19 | `transcript` 展示 | `[完成]` 语音回答气泡显示“听到：……” | 无 | 语音问答能看到转写 | C |
| R-20 | 语音交互评测（ARCH §6） | `[部分]` `pipeline eval --audio` 可跑 | 指标缺 ASR WER、分类准确率 | 报告含 ASR WER | B |

---

## 4. 多 Agent 协同（赛题任务 4）

| ID | 要求（来源） | 现状 | 缺口 / 下一步 | 验收 | 负责人 |
| --- | --- | --- | --- | --- | --- |
| M-1 | 九个 Agent 定义（ARCH §3.2） | `[部分]` 阶段函数存在，但没有注册为 Agent | 建 Agent 注册表 | 每个 Agent 有输入/输出/依赖 | B |
| M-2 | 确定性 DAG + 依赖顺序（ARCH §3.2） | `[完成]` `pipeline/orchestrator.py`，`run --dry-run` 可列 14 阶段 | 并发未做 | `--dry-run` 打印 DAG | B |
| M-3 | 重试/超时/并发（ARCH §3.2） | `[部分]` 重试/超时已实现；并发串行 | 并发后续再做 | 失败可重试、超时记录 | B |
| M-4 | 缓存（ARCH §3.8） | `[完成]` `stage_key` + manual 哈希；zh-01 稳定后大多命中缓存 | 其余五本待验证 | 同输入重跑命中缓存 | B |
| M-5 | 全阶段 Manifest（DATA §8.5） | `[部分]` zh-01 产出 14 阶段、40 artifacts；其余五本当前是 tts→critic 的 8 阶段 tail | 其余五本需补跑一次全链 | 每阶段有 model/prompt/duration/hash | B |
| M-6 | 全链 Trace（DATA §8.5） | `[完成]` 生成 trace 落 `data/traces/<date>/` | 在线 trace 另见 R-15 | 每次生成可回放 | B/A |
| M-7 | 接入 A 的 Job/API（ARCH §3.2） | `[完成]` runner 调编排器；Job 返回 degraded + manifest_path | 无 | `/generate` 真跑全链，C 进度不变 | A/B |
| M-8 | 阶段幂等/可单独重跑（ARCH §3.1） | `[部分]` 大多数阶段可重跑 | 用编排器验证 `--from`/`--to` | 单阶段重跑不破坏下游 | B |
| M-9 | Critic（ARCH §3.2） | `[完成]` 新增 `pipeline/critic.py` 与 orchestrator `critic` 阶段，产出 `derived/critic/report.json`（页/场景/时间轴/字幕/音轨/终版视频检查） | 风格相似度评分仍未做 | `derived/critic/report.json` | B |
| M-10 | ArtDirector（ARCH §3.2） | `[未做]` 风格/prompt/keyframe 散落 | 汇总并校验 `derived/art/art_direction.json` | 风格资产可审计 | B |
| M-11 | Curator 统一产物（ARCH §3.2） | `[部分]` index/knowledge/hotspots 分散 | 注册成 Curator 阶段 | 索引/卡/热区/能力报告一次产出 | B |
| M-12 | 一条命令跑全链（ARCH §3.2） | `[完成]` `python -m pipeline run --book zh-01` | 六本待跑 | 新书一条命令出片 | B |
| M-13 | 可复现验收（ARCH §3.8） | `[部分]` zh-01 全链/断点/缓存已验证 | 六本与哈希一致待验 | 报告可复现 | B |
| M-14 | 在线 Conductor（用户要求 + ARCH §4.2） | `[完成]` `backend/app/conductor.py`：工具注册表、规则快路径、多意图拆分、seek 后限定后续问答页 | 复杂模糊句仍靠规则 | 多步请求可执行、有 trace | A/B |
| M-15 | 动态工具调用（用户要求） | `[部分]` control/seek/search/highlight/click/qa 已注册；ASR 在入口记录为 trace 阶段；TTS 未接 | 接 TTS 工具 | 按请求选工具 | A/B |
| M-16 | Trace 记录 provider/model/成本 | `[部分]` trace 记录工具名、阶段耗时、tier；qa.llm 可区分 | 未逐工具记录 provider/model/费用 | 材料 d 能说清调用范围 | A/B |

---

## 5. 人工修正（ARCH §3.5、DATA §7、TEAM §12.2）

| ID | 要求 | 现状 | 缺口 / 下一步 | 验收 | 负责人 |
| --- | --- | --- | --- | --- | --- |
| H-1 | Annotation/ReviewItem 模型 | `[完成]` `contracts/models.py` | 无 | 模型可校验 | B |
| H-2 | 页级人工叙述 | `[完成]` `manual/narrative.json` 被 narrative/story 读取 | 需补审核覆盖率 | 改叙述下游生效 | B |
| H-3 | 字段级人工修正文件 | `[完成]` `manual/annotations.jsonl` 有读写与运行时消费 | 审核页待接 | 改卡片/bbox/alias 能生效 | B |
| H-4 | 运行时 human 优先 | `[完成]` `interaction.py` 先套 Annotation 再读包/卡 | 场景/alias 覆盖待补 | 人工答案优先于 auto | A |
| H-5 | 冲突队列 | `[完成]` 冲突写 `derived/review/queue.jsonl` | 低置信/缺失未生成 | 冲突不静默 | A/B |
| H-6 | 审核队列生成 | `[部分]` 冲突已生成；低置信/缺失未生成 | 补低置信/缺失规则 | 队列可被审核页消费 | B |
| H-7 | 审核页（C） | `[完成]` 已合并进阅读器右侧“审核修正”标签：热区/文字块/问答卡编辑、已有修正、冲突队列、JSON 批量 | alias/fact 编辑与键盘快捷键 | 人能改文字/标签/bbox/答案 | C |
| H-8 | 写入 API/版本化（A） | `[部分]` `POST /annotations` append-only 已通；回滚/版本状态未做 | 补回滚与 superseded | 修正可审计、可回滚 | A |
| H-9 | 回滚/审计 | `[部分]` 叙述有 version/superseded | 字段级缺 | 旧值可恢复 | A/B |
| H-10 | 能力报告含审核覆盖 | `[部分]` `needs_review` 有结构 | 需真实统计 | 报告显示审核覆盖率 | A/B |
| H-11 | 路径一致 | `[完成]` 契约 §2 已改为 `manual/annotations.jsonl` | 无 | 只有一套路径 | 三人 |
| H-12 | 人工改卡片/bbox/alias/hotspot/答案 | `[部分]` 卡片/bbox/热区已生效；alias/fact/scene 未做 | 补 alias/fact/scene | 五类修正都能生效 | A/B/C |

---

## 6. 知识层（ARCH §5、DATA §6）

| ID | 要求 | 现状 | 缺口 / 下一步 | 验收 | 负责人 |
| --- | --- | --- | --- | --- | --- |
| K-1 | PageFact | `[未做]` `facts.jsonl` 不存在 | 抽事实/属性/关系/bbox | 事实可被答案引用 | B |
| K-2 | QaCard | `[部分]` 74 张卡，40 题未覆盖；zh-01 仅 3 张 | 开 LLM 补卡；中文书优先 | 官方 qa 全覆盖 | B |
| K-3 | QaCard 契约（5–8 variants、evidence、guide） | `[部分]` 样例 7 variants、1 evidence | 校验所有卡；补齐 guide/evidence | 契约校验通过 | B |
| K-4 | Alias | `[未做]` `aliases.json` 不存在 | 角色/颜色/方位/同义说法 | 每卡 ≥3 别名 | B |
| K-5 | Narrative | `[部分]` 有六本 narrative | 质量抽检；人工修正覆盖 | 叙述 80–150 字、只写可见内容 | B |
| K-6 | 检索：字面 + 拼音 | `[部分]` 字面检索有；拼音未做 | 加拼音/别名 | 口语说法能命中 | B |
| K-7 | 检索：向量 | `[未做]` `vectors.jsonl` 不存在 | Embedding + 向量索引 | 语义相近能召回 | B |
| K-8 | 结构化过滤/重排分档 | `[部分]` 有分档与打分 | 需按契约重排 | 结果分 strong/weak/guide | B |
| K-9 | strong/weak/guide | `[完成]` strong 卡、weak LLM、guide 降级都通了 | 需更多抽检 | 三档齐全 | A/B |
| K-10 | 证据 | `[完成]` answer.evidence | 前端未渲染 | 见 R-9 | C |
| K-11 | 语言跟随提问 | `[完成]` zh/en 跟随 | 混说需抽检 | 中英问中英答 | A/B |
| K-12 | 无脚本新书也能问答 | `[部分]` 可 guide；无卡 | 见 R-12；冷启动测试 | 新书无脚本能问 | B/A |

---

## 7. 评测（ARCH §6、DATA §12）

| ID | 要求 | 现状 | 缺口 / 下一步 | 验收 | 负责人 |
| --- | --- | --- | --- | --- | --- |
| E-1 | EvalCase/EvalRun/EvalResult | `[完成]` 契约与 `pipeline/eval.py` | 无 | 回放产出契约 JSONL | B |
| E-2 | 文字回放 | `[完成]` 328 动作 | 无 | 可复跑 | B |
| E-3 | 音频回放 | `[完成]` `--audio` 300 条 | 无 | 可复跑 | B |
| E-4 | ASR WER | `[未做]` 只有 CER 诊断 | 写进 `EvalRun.metrics.asr_wer` | 报告有 WER | B |
| E-5 | 分类准确率 | `[未做]` | 统计 kind 是否判对 | 报告有分类准确率 | B |
| E-6 | 执行准确率 | `[部分]` 按 kind 判定 | seek/click 基准不可靠 | 人工抽检基准 | B/C |
| E-7 | QA 正确率 | `[部分]` 只看 tier，不看语义 | 参考答案 + 人工抽检 | qa 语义正确率 | B/C |
| E-8 | 证据完整率 | `[完成]` evidence_rate | 无 | 报告有 | B |
| E-9 | p50/p95 | `[完成]` 服务内延迟 | 端到端未测 | 报告有端到端 | A/C |
| E-10 | 降级率 | `[完成]` fallback_rate | 无 | 报告有 | B |
| E-11 | 按 kind 分桶 | `[完成]` | 无 | 报告有 | B |
| E-12 | 退化 case 明细 | `[部分]` report 有明细 | 需补“与上次差值” | 报告含所有退化 case | B |
| E-13 | 与上次差值 | `[未做]` | 对比上一 run | 报告有 delta | B |
| E-14 | 评测面板（C） | `[未做]` `evaluation/` 不存在 | 接 `runs/` 与 report | 页面可筛选/回放 | C |
| E-15 | 官方格式适配层 | `[未做]` | `adapters/` | 官方输入输出可适配 | A/B |
| E-16 | QA 参考答案 + 人工审核 | `[未做]` | 自动草稿 + 人工确认 | 有参考答案库 | B/C |
| E-17 | 端到端延迟 | `[未做]` | 含前端、媒体、TTS | p50/p95 可展示 | A/C |
| E-18 | seek 判定基准 | `[部分]` 用页正文重叠，误判多 | 人工抽检/目标页标注 | seek 判定可信 | B/C |
| E-19 | click 判定基准 | `[部分]` 依赖热区 | 纯视觉目标需人工标注 | click 判定可信 | B/C |

---

## 8. 通用性、模型与材料

| ID | 要求 | 现状 | 缺口 / 下一步 | 验收 | 负责人 |
| --- | --- | --- | --- | --- | --- |
| G-1 | 任意 PDF 能进（ARCH §1） | `[完成]` A 的 reader upload + B ingest | 需冷启动实测 | 没见过的 PDF 能进 | A/B |
| G-2 | 没有 50 条脚本也能跑（ARCH §1） | `[部分]` 能生成，但无卡只能 guide | 见 R-12；用新书实测 | 新书能理解/生成/问答 | B/A |
| G-3 | 照片/扫描件（ARCH §1） | `[未做]` | 见 I-2 | 照片书能进 | B |
| G-4 | 说明型内容（ARCH §3.4） | `[未做]` | 见 I-9 | 说明型 PDF 能出结构 | B |
| G-5 | 不写死内容/坐标/答案（ARCH §1、DATA §1） | `[部分]` 主要逻辑不写死；ASR 模型路径在配置 | 全局 grep 检查 | 代码无书名/页号/答案 | B |
| G-6 | 模型适配层（ARCH §3.3） | `[部分]` OCR/VLM/LLM/ASR/I2V 有；TTS/Embedding 缺 | 补 TTS/Embedding 接口 | 换 provider 不改业务 | A/B |
| G-7 | local/demo profile（用户要求） | `[未做]` 只有一套本地配置 | `profiles: local/demo` | `models --profile demo` 可查 | A/B |
| G-8 | 三方 API 适配/成本/密钥（用户要求） | `[未做]` | LLM/VLM/ASR/TTS/I2V 云适配 | 演示能切 API，失败回退本地 | A/B |
| G-9 | 来源清单（材料 d） | `[部分]` 缺 ASR/云 API/TTS | 补许可、用途、是否出本机 | 材料 d 完整 | 三人 |
| G-10 | IP 承诺 | `[完成]` 有承诺 | 随 G-9 更新 | 承诺与调用范围一致 | 三人 |
| G-11 | 5 分钟演示视频 | `[未做]` | 见 S0-6 | 见 S0-6 | C |
| G-12 | 项目说明书 | `[未做]` | 见 S0-7 | 见 S0-7 | 三人 |
| G-13 | 一键启动/离线运行 | `[部分]` 有命令，无脚本 | 启动脚本、离线检查 | 断网能演示主流程 | A |
| G-14 | 显存/模型冲突 | `[完成]` Qwen3.5-9B 85% GPU + faster-whisper small 可共存；语音问答已实测 | 全 GPU 语音会超 2s，演示建议 API | 演示不 OOM | A/B |
| G-15 | ffmpeg/edge-tts 依赖 | `[未做]` 未安装 | 安装/适配 | 配音与混音可用 | B |

---

## 9. 契约、流程、文档一致性

| ID | 要求 | 现状 | 缺口 / 下一步 | 验收 | 负责人 |
| --- | --- | --- | --- | --- | --- |
| C-1 | 契约 2.0.0 唯一事实源（DATA §14） | `[完成]` `contracts/models.py` | 无 | 模型与文档同步 | 三人 |
| C-2 | `transcript` 字段版本 | `[部分]` 已加字段，但 `SCHEMA_VERSION` 仍 2.0.0 | 按 §14.2 升 2.1.0，或移出契约 | 版本与变更规则一致 | 三人 |
| C-3 | 前端类型同步（DATA §14.2） | `[部分]` `contracts/book_api.ts` 未含 transcript | 同步类型 | 前端类型与契约一致 | C |
| C-4 | 校验覆盖（DATA §13） | `[部分]` 只校验 book/query set | 校验 cards/scene/manifest | 产物不合契约能报错 | B |
| C-5 | 全阶段 manifest | `[部分]` zh-01 已验证 13 阶段；其余五本待跑 | 六本全跑 | 见 M-5 | B |
| C-6 | Trace/Turn 落盘路径 | `[完成]` 生成 trace 在 `data/traces/`；在线 Turn/Trace 同根目录、按日期分文件 | 无 | 路径与契约一致 | A/B |
| C-7 | Annotation 路径一致 | `[完成]` 契约 §2 与 §7/代码统一为 `manual/annotations.jsonl` | 无 | 文档与代码一致 | 三人 |
| C-8 | `prompts/` 版本化 | `[未做]` 目录不存在 | 提示词落到 `prompts/` | 提示词可版本化 | B |
| C-9 | `evaluation/` 目录 | `[未做]` 目录不存在 | C 的评测面板/结果 | 目录存在且可用 | C |
| C-10 | 契约变更三人确认（TEAM §9） | `[部分]` transcript 变更未确认 | 补确认记录 | 变更可追溯 | 三人 |
| C-11 | 文档更新 | `[部分]` STATUS/README/HANDOFF/MODEL_SOURCES/C README 有过期内容 | 逐份更新或标注 | 文档与代码一致 | 三人 |
| C-12 | 测试 | `[完成]` 224 passed | 继续补人工修正/评测测试 | 回归全绿 | B/A |
| C-13 | 分支/提交 | `[部分]` 工作区有 C 的未提交前端、B 的未提交检索改动 | 按 TEAM §9 评审合并 | 分支干净、可回滚 | 三人 |

---

## 10. 建议顺序（按“赛题门槛 + 依赖”）

1. **M-2～M-8 离线编排器 + 缓存 + 全阶段 manifest**：接 A 的 Job/runner，先让“四项任务均完成”里的第 4 项从 0 变 1。
2. **H-3～H-8 人工修正闭环**：字段级 Annotation 合并、运行时 human 优先、冲突队列、写入 API、审核页。
3. **R-12/R-13 运行时 LLM 问答**：任意书内问题能答或引导；接 A 的 interact，不另起入口。
4. **V-8/V-10/V-7 视频配音 + 风格/连贯检查**：让第 2 项真正“含语音”。
5. **R-10/R-11/V-14 触控万物 + 动态对象**：补齐第 3 项的触控半边。
6. **E-4～E-7/E-14/E-16 评测指标与面板**：ASR WER、分类准确率、QA 语义抽检、评测面板。
7. **G-7/G-8 三方 API profile**：本地测试 → 演示 API，trace 记 provider/model/cost。
8. **S0-6/S0-7 演示视频 + 说明书**：最后按真实能力录，不按 PPT 吹。

## 11. 当前最硬的三个缺口

1. **第 4 项多 Agent 编排是 0**：没有编排器、全阶段 manifest、缓存、trace；这是“四项均完成”门槛的直接阻塞。
2. **第 3 项只能答预设问题**：语音已通，但没有运行时 LLM，任意问题只能 guide；触控万物也只覆盖一部分。
3. **第 2 项没有声音**：六本视频只有字幕，没有旁白/音轨；风格一致性与页间连贯没有量化报告。

这三项不补，材料 a–d 做得再漂亮也过不了“四项核心任务均完成”。

---

## 12. 进度更新

### 2026-11-24 · 第 1 步：编排器 + 缓存 + manifest/trace

已完成：

- 新增 `pipeline/orchestrator.py`：注册 13 个阶段（ingest / scripts / ocr / vlm / story / scene / tts / retime / index / knowledge / hotspots / video / compose），带依赖顺序、重试、超时、缓存、全阶段 manifest、生成 trace。
- `python -m pipeline run --book zh-01 --dry-run`：能列出 13 个阶段、Agent、依赖和缓存状态。
- `python -m pipeline run --book zh-01`：全链真实跑通，首次 106.9s（OCR 70s、video 12s、compose 11s）；稳定后 0.1s，13 个阶段里 12 个命中缓存（TTS 不可用，每次 1ms 重试）。
- `python -m pipeline run --book zh-01 --from index --to compose`：可断点续跑；三次后 5/5 命中缓存。
- 产出 `data/books/zh-01/derived/manifest.json`（13 个阶段、27 个 artifacts）和 `data/traces/2026-11-24/*.json`。
- `backend/app/generation_runner.py` 改为调用编排器；`POST /api/books/zh-01/generate` 返回 `degraded=True` 且带 `manifest_path`，C 的 `jobWait` 不用改。
- 测试 209 passed；新增 `tests/test_orchestrator.py`，更新 A 的 runner 适配测试和 Job degraded/manifest 测试。

当前边界：

- `vlm` / `story` / `tts` / `compose` 目前是 `degraded`：LM Studio 没开、LLM 不在、edge-tts 未装、没有音轨。这是真实降级，不是失败。
- 并发未实现，阶段按 DAG 串行；Windows 上硬超时不能杀线程，实际靠各 provider 的 HTTP 超时。
- `ingest` 对已有书默认命中缓存，不会覆盖 `book.json`；要重新入库必须显式 `--from ingest --force`。
- 人工修正、在线 trace、评测面板仍未动，见第 5、7 节。

### 2026-11-24 · 第 2 步：人工修正闭环（后端/数据）

已完成：

- 新增 `pipeline/annotations.py`：append-only `Annotation`、最新 active 有效值、包/卡片 overlay、冲突 `ReviewItem`。
- `interaction.py` 在任何 click/search/qa 之前先套人工修正；`qa_card` 的 `answers.zh.strong` 这类字段也能覆盖。
- API：`GET/POST /api/books/{id}/annotations`、`GET /api/books/{id}/review-items`。
- 路径统一：`manual/annotations.jsonl`（人工输入）+ `derived/review/queue.jsonl`（系统队列）；契约 §2 已同步。
- 新增 `frontend/review.html`（`http://127.0.0.1:8000/review`）：选书/页、热区叠框、热区/文字块/问答卡编辑、已有修正、冲突队列、JSON 批量。（该独立页已在第 4 步合并进阅读器“审核修正”标签，文件已删除。）
- 在真实 `zh-01` 上实测：给“积木城堡”热区写一条 description 修正，点击同一位置返回人工描述；验证后已删除测试记录。
- 测试 224 passed。

当前边界：

- 审核页已有基础版；缺键盘快捷键、批量审核、alias/fact 编辑。
- 低置信/缺失项还不会自动进审核队列。
- alias/fact/scene 的覆盖还没做；只支持 hotspot/text_span/page_block/qa_card/book。
- 字段级回滚还没做：文件 append-only，但“标记 superseded + 恢复旧值”的接口未提供。
- `transcript` 字段仍未按契约 §14.2 升版本，见 C-2。

### 2026-11-24 · 第 3 步：运行时 LLM（`weak` 档）

已完成：

- 新增 `backend/app/llm_answer.py`：从页正文/画面叙述/故事旁白里取相关页，交给 Qwen3.5-9B；答案必须能在原文里找到支撑句，找不到就退回 `guide`。
- 加了四类 grounding 约束：数量词（“九块”）必须在证据句里；问题人物和证据人物不一致时拒绝；`因为……` 的原因必须在同页；封面/版权页不作为证据。
- LM Studio 加载 `qwen/qwen3.5-9b`（85% GPU，给 ASR 留显存）；ASR 本地测试改用 `faster-whisper small`，`large-v3` 仍在磁盘上，单人跑评测时可切回。
- 实测文字：
  - “花花为什么生气？”→ `weak`，第 6 页证据，约 1.3s
  - “小满和花花最后和好了吗？”→ `weak`，第 11 页，约 1.2s
  - “她们搭了几块积木？”→ `weak`，“九块”，第 12 页，约 0.5s
  - “小满为什么哭了？”/“这本书的作者是谁？”→ `guide`（假前提/无依据）
- 实测语音：“花花为什么生气？”→ ASR 215ms + LLM 1.7s，总 3.65s。
- 测试 224 passed。

当前边界：

- 语音总延迟 3.65s > 2s 目标；Qwen 85% GPU 有 CPU 卸载。演示用三方 API 可解。
- 有些答案仍然偏“复述原文”，不是精炼回答；需要更多抽检和更好的模型。

### 2026-11-24 · 第 4 步：在线 Conductor + Turn/Trace + 统一界面

已完成：

- 新增 `backend/app/conductor.py`：工具注册表（router/player/seek/retrieve/highlight/click/qa）、规则快路径、`然后/接着/并且` 多意图拆分；seek 落点页会传给后续问答。
- 新增 `backend/app/session_log.py`：每轮写 `data/turns/<date>.jsonl` 与 `data/traces/<date>/<request_id>.json`；API 增加 `GET /api/books/{id}/turns|traces`、`GET /api/tools`、`GET /api/eval/latest`。
- `POST /api/interact`、`POST /api/qa`、`POST /api/interact/audio` 全部走 Conductor；语音 ASR 阶段写入 trace，Turn 记录转写文本。
- 修正延迟拆分：`route` 不再包含 LLM 时间；实测“花花为什么生气？”文字问答 total≈1.19s（generate≈1.18s）。
- LLM 证据补 bbox：把支撑句覆盖到的 text span 合并成框；前端点“依据”翻页并画橙色框。
- 前端合并为单页：阅读器右侧“对话 / 审核修正 / 生成链路 / 评测”四个标签；对话显示档位、耗时、转写、依据 chip；链路显示工具表、本轮阶段耗时、manifest 阶段；评测显示能力报告与最近 eval run。
- Turn 用 localStorage 记住每本书的 session，刷新后回放历史对话。
- 视频编码修复：OpenCV 的 `mp4v` 浏览器不认；`pipeline/video.py`、`pipeline/final.py` 统一在落盘前用 imageio-ffmpeg 转 H.264 + faststart，六本已有 `final.mp4` 已重编码并实测可播放。
- 旁白音轨：安装 edge-tts；六本全部生成旁白（中文 12 页×3，英文 28 页×3），retime 重排 8–18 页，compose 混入 AAC；六本 `final.mp4` 均为 H.264 High + AAC，时长 1:54–3:27。
- Critic：新增 `pipeline/critic.py` 与编排器第 14 个阶段，检查页/场景/时间轴/字幕/音轨/终版视频，写 `derived/critic/report.json`；六本均 `ok=true`、0 warnings。
- 新增 `GET /api/providers`：返回 OCR/VLM/LLM/ASR/I2V/TTS 的配置 provider、模型、可用状态；前端“生成链路”展示。
- 语音实测（官方 WAV）：`01.wav` → 转写“播放”，control，ASR 348ms / total 353ms；`14.wav` → “为什么倒了”，qa strong，ASR 252ms / total 260ms；Turn/Trace 均落盘。
- `/review` 改为跳转 `/reader/#review`，删除独立审核页。
- 测试：新增 `backend/tests/test_conductor.py`、`tests/test_critic.py`；相关后端测试 38 passed，critic/orchestrator 10 passed。

当前边界：

- 多意图仍是规则拆分，没有额外 LLM planner；复杂模糊句会退回单意图。
- Trace 记录工具名/耗时/tier，但还没有逐工具记录 provider/model/费用。
- 评测标签只读 `runs/` 里最近一次结果，不能从界面发起评测。
- Critic 只做结构性检查（缺页/空字幕/断时间轴/缺音轨），不做风格相似度与语义连贯评分。
- 其余五本 manifest 只覆盖 tts→critic 的 8 个阶段；补全 14 阶段需要再跑一次全链（缓存会跳过已完成阶段，但早期 OCR/VLM 可能重跑）。

### 人工修正怎么用（当前接口）

**最简单：打开阅读器，切到“审核修正”标签**

```text
http://127.0.0.1:8000/reader/#review
```

选绘本 → 阅读器翻到要改的页 → 在右侧“审核修正”里点热区/文字块/问答卡的“编辑” → 改新值 → 填审核人 → 保存。
标签页已支持：当前页热区与文字块、问答卡、已有修正、冲突队列、JSON 批量修正。

改完后不需要重启后端，下一次 `/api/interact` 立即生效。

命令行接口（备用）：

```powershell
# 1) 查现有修正
Invoke-RestMethod http://127.0.0.1:8000/api/books/zh-01/annotations

# 2) 改热区描述（点“积木城堡”返回人工描述）
$body = @{
  target_type = "hotspot"
  target_id = "hotspot-zh-01-005-03"
  field = "description"
  value = "人工修正：小满和花花一起搭的积木城堡"
  reviewer = "B"
  reason = "自动描述太泛"
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/books/zh-01/annotations `
  -ContentType "application/json" -Body $body

# 3) 改问答卡的强答案
$body = @{
  target_type = "qa_card"
  target_id = "card-zh-01-006"
  field = "answers.zh.strong"
  value = "不开心，因为她想和小满一起过生日。"
  reviewer = "B"
  reason = "原答案没有回答情绪"
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/books/zh-01/annotations `
  -ContentType "application/json" -Body $body

# 4) 查冲突队列
Invoke-RestMethod http://127.0.0.1:8000/api/books/zh-01/review-items
```

支持的 `target_type`：`hotspot` / `text_span` / `page_block` / `qa_card` / `book`。
常用 `field`：`description`、`label`、`bbox_px`、`text`、`answers.zh.strong`、`question_canonical`、`variants`。
如果传 `old_value` 且与当前 auto 值不一致，返回 `conflict=true`，并写 `derived/review/queue.jsonl`。
人工记录 append-only 写在 `data/books/zh-01/manual/annotations.jsonl`。

# 进度与中心检查

> 写于 2026-11-17。目的：回答“有没有偏离中心、会不会返工”，不是汇报。
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
| 内容理解 | 半成品 | `pipeline/ingest.py`、`pipeline/understanding.py`；六本 120 页；OCR 已跑 | 真实 VLM 叙事/实体/热区；`zh-02`“小刺猬”未命中 |
| 互动视频生成 | 未开始 | 契约 `StoryPlan/ScenePlan/VideoSegment` | 分镜、视频、TTS、合成 |
| 实时交互 | 只有契约 | `InteractionRequest/Response`、`/api/interact` | 运行时、ASR/TTS、播放器、UI |
| 多 Agent | 只有架构 | `docs/ARCHITECTURE.md` | 编排器、阶段产物、trace |
| 回答正确率 | 未测 | `derived/coverage_report.json` | QA 卡、评测 runner、真实准确率 |
| 延迟 | 未测 | 延迟预算 | 运行时埋点、p50/p95 |
| 可复现 | 契约级 | manifest 字段、内容哈希 | 实际产物和重跑校验 |
| 人工修正 | 契约级 | `Annotation` / `ReviewItem` | 审核队列、审核页/CLI |
| 通用性 | 设计+部分代码 | Book/QuerySet 分离、provider 适配层 | 新书冷启动实测 |

### 覆盖检查（OCR 后）

- 六本 300 个 QueryItem、328 个动作、90 个必选动作。
- 现在可解析：control 65/65；search/highlight 37/38；seek 0/79；qa 0/117；click 0/28。
- 唯一缺的文本目标：`zh-02` 第 42 步“小刺猬”。
- 这 37/38 只代表“能找到文字/时间轴数据”，不代表执行准确率已达标。

## 3. 有没有偏离

**没有偏离，但重心要立刻切。**

前一段做的是文档、契约、入库、QuerySet、OCR。这些是地基，不是绕路：

- 没有统一契约，三个人一定各写一套字段，第三周必崩。
- 没有 OCR，英文 84 页和中文书里的手写对白进不了系统，后面所有问答/分镜都是空的。
- OCR 也验证了“按页判断文本层”这条通用性判断，不是只为这六本。

但赛题的另一半——**互动视频生成**——现在是 0。下一阶段必须切到 `StoryPlan → ScenePlan → 视频 → TTS`，不能再在文字层上精修。这是当前唯一需要警惕的偏离风险。

## 4. 返工风险

| 风险 | 会怎么返工 | 现在怎么防 |
| --- | --- | --- |
| A/C 还没评审 v2 契约 | Book/QuerySet、Scene 时间基准、`/api/interact` 一变，代码要改 | 下一步先让 A/C 看契约，再写 scene/video |
| C 的播放器对着空气写 | Scene/字幕/热区字段对不上 | 先给一页 mock `ScenePlan` + timeline，让 C 能接 |
| VLM 一直空着 | 英文叙事、实体、任意点击识别缺内容 | 先用人工修正补重点页；决定本地 Ollama 还是免费 API |
| 数据只在本地 | A/C 拿不到页图/OCR 结果 | 网盘/工作区共享；代码里不写死路径 |
| 没有评测 | 不知道 0.60 到没到，容易自我感觉良好 | Scene/QA 之后立刻接 300 条回放 |
| 没有视频预算 | 质量停在“动态绘本” | 页动画为主、重点页 I2V；提前说清，不画饼 |

## 5. 分工边界（避免撞车）

- **字幕数据**：B 在 `Scene.subtitles` 里产出文本/时间/语言；**C 只负责播放器渲染、开关、样式和同步**；A 负责媒体与接口。B 不做前端字幕组件。
- **审核页**：C 主责 UI；B 提供 `Annotation`/`ReviewItem` 数据和 overlay 图；A 落库和版本化。
- **overlay 图**：`python -m pipeline review --book zh-01 --page 6 --target "我又不是故意的"` 生成本地 PNG，是审核辅助，不是前端页面。

## 6. 下一步

1. `StoryPlan` / `ScenePlan`：角色、逐页旁白、scene 时间、字幕、aliases、物体框。先给一页 mock 给 C。
2. 视频/配音/合成：页动画 + 重点页 I2V + Edge TTS。
3. 知识层：PageFact / QaCard / Alias + 人工审核。
4. 在线交互：`/api/interact`、播放器、对话历史。
5. 评测：300 条回放、按 kind 分桶、p50/p95、重跑一致。

## 7. 什么时候需要人

- **现在**：请 A/C 评审 v2 契约（尤其 `BookPackage`/`QuerySet` 分离、`Scene` 时间基准、`Interaction` 协议）；这是最大返工源。
- **现在**：决定 VLM 走本地 Ollama/LM Studio，还是免费 API，还是先空着靠人工修正。
- **后面**：QA 卡、热区、OCR 错字的人工抽检；演示视频和说明书。
- **代码上**：暂时不需要你动手，我继续做 StoryPlan/ScenePlan。

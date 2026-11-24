# 交接文档（写给接手的人）

> 写于 2026-11-24，项目：DreamyTale / 纸书智伴。
> 接手人请**先读这一页**，再读 `docs/STATUS.md`（进度中心检查）、`docs/ARCHITECTURE.md`（架构）、`docs/DATA_CONTRACT.md`（唯一契约）。
>
> **本文档最重要的一节是第 0 节**。前面的人在这条路上走错过一次，
> 走错的原因写在那里，避免你重走一遍。

---

## 0. 先说这个：不要用正确率当唯一指标，也不要用字词匹配去补模型的缺

### 0.1 发生过什么

用户（B 角色，内容工厂/生成链路技术牵头）两次纠正，第二次是这么说的：

> "我感觉你做的所有事情全都是为了提高正确率做的，而且我理解的交互式问答不是靠 LLM 和人工修正的缓存提示完成的吗，
> 我感觉你一直在纠结检索和字词匹配，是不是偏离最初计划？"
> "这不还是在做字词匹配和检索吗？"

前一轮的具体错误：

1. **把检索规则当成了产品能力。**
   为了让 qa 的正确率从 65% 涨到 69%，在 `contracts/retrieval.py` 加了
   `term_score` / `char_coverage`，在 `pipeline/knowledge.py` 加了四路信号打分
   （页正文 / 视觉叙述 / 故事节拍 / 别名实体）和 `_is_grounded` 门槛。
   这些规则**只对官方脚本里那 117 道题有效**，评委换个说法问就失效。
   涨的是数字，不是能力。

2. **在运行时重做 pipeline 已经做好的事。**
   为此写了 450 行的 `backend/app/guide.py`：算相关度、挑"最相关的一页"、
   过滤页眉页脚、英文分词、中文字覆盖率……
   而 pipeline 产出的 `QaCard` 里**早就烘焙好了**引导话术、该引的原话、
   该翻到的页码和场景锚点：
   ```
   问: 他们在搭什么？
     guide : 我们翻到第 2 页看看吧："我们一起搭城堡，搭高高，还不倒……你从画面里看出他们在搭什么了吗？
     anchor: {'scene_id': 'scene-zh-01-002', 'start_ms': 0}  ev: 2
   ```
   运行时再去猜一遍，是把对的答案推翻。

3. **在错误的层打补丁。**
   真正缺的是 LLM（本地 LM Studio 没开），于是用规则去替代模型。
   规则替代模型 = 过拟合测试集 = 数字好看但演示时一问就穿帮。

### 0.2 正确的分层（照这个做，不要改）

| 层 | 负责人 | 做什么 | 不做什么 |
| --- | --- | --- | --- |
| `pipeline/` | B | LLM 写卡：三档答案（strong/weak/guide）、引哪句原话、翻到第几页、场景锚点；写 `derived/knowledge/uncovered.json` 列出答不上的题 | 不做运行时检索 |
| `backend/` | A | 读卡、照做（`strong` 原样、`weak` 组织语言、`guide` 翻页+反问）；**人工修正优先于自动** | 不猜"该翻到哪一页" |
| `frontend/` | C | 播放器、字幕、依据高亮、评测面板 | 不直接调模型 SDK |

关键概念（`docs/ARCHITECTURE.md` §5）：

> - **检索**：字面 + 拼音 → 向量 → 结构化过滤；重排后分档
> - **答案**：`strong`（卡命中，不改写）/ `weak`（要点 + LLM 组织）/ `guide`（承认 + 翻页 + 反问）
> - **证据**：page_index + bbox + span/fact + scene/time，前端可点"依据"高亮

**契约 §6.2 的硬要求**：`QaCard` 必须有 `evidence` 和 `guide`，`variants` 至少 5 条；
`guide` 三件事缺一不可，且**禁止"抱歉，我无法回答"**。

### 0.3 什么叫"做对了"

- 指标要看的是**效果**（成片时长、字幕条数、能答的问题数、能点的热区数、证据率），
  正确率只是其中一行。报告页已经把效果放前面、正确率放最后一行。
- 一道题"答不上"时，正确的表现是**引导**（承认 + 翻到相关页 + 引用原句 + 反问），
  不是硬凑一个答案，更不是回一句"没找到"。
- 检索/匹配规则只用来**找卡**（卡命中），不用来**编答案**。

---

## 1. 当前状态（截至最后一次提交 `4187dcf`）

### 1.1 已完成并已提交

| 项 | 状态 | 位置 |
| --- | --- | --- |
| 数据契约 v2.0.0 | ✅ 全量模型，`contracts/models.py` 是唯一事实源 | `contracts/` |
| 六本绘本全链路 | ✅ ingest→ocr→vlm→story→scene→index→knowledge→hotspots→video→final | `pipeline/` |
| 成片 | ✅ 六本都有 `derived/video/final.mp4`（1280×720@12fps，**烧录字幕**）+ `subtitles.srt` | `data/books/<id>/derived/video/` |
| 五类交互真结果 | ✅ control / search / highlight / seek / qa | `backend/app/interaction.py` |
| QA 卡 | ✅ pipeline 产出 `derived/knowledge/cards.jsonl`，A 的运行时能读 | `pipeline/knowledge.py`、`backend/app/knowledge.py` |
| 评测回放 | ✅ 328 个动作打真实服务，出 `EvalRun`/`EvalResult` | `pipeline/eval.py` |
| 人工修正（部分） | ⚠️ `pipeline/manual.py` 能写 `manual/annotations.jsonl`，**但后端还没读它** | 见第 4 节 |
| 来源清单 | ✅ 材料 d 要求 | `docs/MODEL_SOURCES.md` |

### 1.2 本次未提交的工作（工作区里，直接看 diff）

> ⚠️ **提交时注意**：`frontend/` 下三个文件有 **C 的未提交改动**（528 行），
> **不要连带着提交**，那是 C 的前端工作。要提交就只挑 `backend/ contracts/ pipeline/` 里的文件。

| 文件 | 改动 | 该不该提交 |
| --- | --- | --- |
| `backend/app/guide.py`（新增） | 引导式回答。**不含任何检索**：停在孩子当前页、引该页第一句原句、承认+翻页+反问 | ✅ 提交 |
| `backend/tests/test_guide.py`（新增） | 引导的契约测试（三要素、无"抱歉"、绝对时间轴） | ✅ 提交 |
| `backend/app/interaction.py` | qa 无卡时走引导（原来回"没找到问答卡"，违反 §6.2）；**修 seek 时间轴 bug**（原来返回页相对时间，播放器按全书绝对时间找页 → 永远落在第 1 页） | ✅ 提交 |
| `backend/tests/test_interaction.py`、`backend/tests/test_api.py` | 跟着改：原来断言"回退"，现在断言"给引导" | ✅ 提交 |
| `contracts/models.py` | `EvalResult` 加 `tier` 字段（评测按档位分桶用） | ✅ 提交 |
| `pipeline/eval.py` | 按 tier 分桶；引导**不算答对**（判 fallback）；回放时带上"当前页"（模拟真实播放器会翻页） | ✅ 提交 |
| `pipeline/report.py`（新增） | 可视化报告：效果面板 + "自己动手试"实时提问面板 + 评测明细 | ✅ 提交 |
| `pipeline/cli.py` | 加 `report` 命令 | ✅ 提交 |
| `contracts/retrieval.py` | **+154 行字词匹配规则**（`term_score`/`char_coverage`） | ❌ **不提交**（第 0 节：过拟合） |
| `pipeline/knowledge.py` | **+153 行四路信号打分** + `_is_grounded` 门槛 + `uncovered.json` | ⚠️ **拆分提交**：`uncovered.json` 那部分要留（四路打分那部分不要） |
| `frontend/index.html`、`frontend/src/app.js`、`frontend/style.css` | C 的前端改动 | ❌ **不提交** |

> 用户明确指示："保留但不提交，不再继续调"（指 `contracts/retrieval.py` 和 `pipeline/knowledge.py` 里的字词匹配那批）。

### 1.3 测试

```
python -m pytest tests backend/tests -q   →  181 passed
python -m pipeline validate                →  ok: 6 book(s), 6 query set(s)
```

---

## 2. 效果与数字（要给人看效果，不要只给百分比）

最新评测 `runs/run-20261124-035918/`（用最终代码跑的）：

```
overall        223/328  68.0%
control         65/65   100%
search          12/12   100%
highlight       25/25   100%
qa              81/117   69%   （strong/weak 才算答对）
seek            26/79    33%   （判定以页正文为基准，会低估）
click           12/28    43%   （纯视觉物体要开 VLM 才能定位）
evidence_rate   72%      ← 引导也带证据，所以比之前高
必选动作        58/91
延迟            p50=0ms  p95=4ms（服务内，不含前端与媒体）
```

**看效果的入口**（这是给用户/评委看的，别只给数字）：

```powershell
# 1) 报告页（效果面板 + 自己动手提问 + 明细）—— 已验证可用
python -m pipeline report
#    → runs/<run_id>/report.html
python -m http.server 8080      # 另开一个终端
#    → http://127.0.0.1:8080/runs/run-20261124-035918/report.html

# 2) 真正的阅读器（C 的前端）
python -m uvicorn backend.app.c_demo:app --host 127.0.0.1 --port 8000
#    → http://127.0.0.1:8000/reader/

# 3) 六本成片
data/books/<id>/derived/video/final.mp4
```

报告页现在长这样（浏览器实测）：
`6 绘本 · 12分24秒 成片总时长 · 124 字幕条数 · 79 可答问题 · 12 可点热区 ·
120 画面页数 · 223/328 评测正确（参考） · 4 ms 响应 p95`
三个页签：**① 效果**（每本书：成片播放器 + 逐页画面墙，蓝框＝可点热区 +
孩子会问的问题和答案）、**② 自己动手试**（现场向服务提问，看返回原文与证据框）、
**③ 评测明细**（每条动作：判定 + **档位** + 回答 + 页图证据框 + 延迟）。

---

## 3. 环境事实（别再踩一遍）

| 事项 | 事实 |
| --- | --- |
| LM Studio | **已装但没运行**（用户之前为了省内存关掉了）。模型在 `D:\LLM\models\`：`Qwen3.5-9B-Q4_K_M.gguf`（5.24GB）、`mmproj-Qwen3.5-9B-BF16.gguf`（0.86GB，多模态投影）、`NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf`（2.64GB）。启动后端点 `http://127.0.0.1:1234/v1` |
| 内存 | 16GB，可用约 4GB（开模型会更紧）。**用户明确要求"测试能通就行，别爆我内存"** |
| 显卡 | RTX 4060 Laptop，8GB VRAM |
| 模型配置 | `config/models.yaml`：vlm/llm 都指 `openai_compatible` → LM Studio，`reasoning_effort: none`（**不关的话 token 被 thinking 吃光、返回空答案，47s→4s**），`max_side: 1024` |
| `imageio-ffmpeg` | **装不上**（网络/依赖冲突）。因此 `pipeline/final.py` 的音轨合并（`_mux_audio`）跑不了，只有字幕烧录那条路可用 |
| `edge-tts` | **装不上**，所以只有字幕没有配音 |
| ComfyUI | 在 `D:\Comfy-Desktop`，**没有视频模型**（只有 Qwen-Image 2.1 + 文本编码器），8188 不通 |
| 火山方舟 I2V | `config/models.yaml` 已配好，需要 `ARK_API_KEY` + `ARK_MODEL_ID`，**花钱**，调用范围要写进材料 d |
| 后台服务（当前在跑） | `8000` = uvicorn `backend.app.c_demo:app`（PID 会变，重启后查 netstat）；`8080` = `python -m http.server 8080` |
| 提交 | 分支 `ceobe-backspace`；`git push` 时若代理掉线用 `git -c http.proxy= -c https.proxy= push` |
| PowerShell 提交信息含引号/换行会失败 | 用 `git commit -F $env:TEMP\commit_msg.txt` |

---

## 4. 下一步（按"评委能看见什么"排序，不是按数字排）

### 4.1 【最高优先】开 LM Studio，把 LLM 接进生成链路

这是**真正的解法**，不是打补丁。用 LLM 写卡，卡就覆盖全部问题，
运行时读卡就行，检索规则可以全部退休。

```powershell
# 1) 启动 LM Studio，load Qwen3.5-9B（或 Nemotron-Nano-4B 更省内存），开 Local Server (1234)
# 2) 确认通：
curl.exe http://127.0.0.1:1234/v1/models
# 3) 用 LLM 重写 QA 卡（117 条问题全覆盖）：
python -m pipeline knowledge --all --use-llm
# 4) 用 VLM 定位纯视觉物体（英文书 15 个热区）：
python -m pipeline hotspots --all --use-vlm
# 5) 重跑评测与报告：
python -m pipeline eval --all
python -m pipeline report
```

要点：
- `pipeline/knowledge.py` 里 `_answer_with_llm()` 已经写好了（schema 约束 JSON 输出），
  **LLM 负责选页 + 写三档答案**，运行时只读卡。
- `pipeline/knowledge.py` 里 `_best_page()` 现在是那套四路打分——**开了 LLM 之后它只该当降级兜底**，
  不要让它当主路径。
- 内存紧就先用 Nemotron-Nano-4B 试通流程，再换 9B。

### 4.2 【高】人工修正闭环

契约 §7：人工修正 append-only、**优先于自动**、`auto` 保留、冲突进队列。
现状：`pipeline/manual.py` 能写 `manual/annotations.jsonl`，
但 **`backend/` 从来不读它** —— 人改了卡，运行时一点变化没有。这是"人工修正"唯一真正的缺口。

要做的：
- `backend/app/knowledge.py` 读 `manual/annotations.jsonl`，把 `source: human` 的记录覆盖到卡上；
- 提供写入接口（`TEAM_DIVISION.md` §12.2：修正落库、版本化、通过接口暴露是 A 的事）；
- 冲突不静默：自动值保留，进 `conflicts` 队列。

### 4.3 【高】ASR（语音提问）

赛题核心任务 (3) 写的是"实现**语音**提问"，命题组给的是 **50 条 WAV 音频**，
评测也是打音频。**现在整套评测在打文本，等于绕过了最关键那环。**

- `backend/app/c_demo.py` 的 `POST /api/interact/audio` 现在明确返回"ASR 尚未配置"；
- 需要：`faster-whisper`（本地、免费、CPU 可跑，16GB 内存吃得下）；
- 加上之后评测回放应改打 WAV，产出 ASR WER（`ARCHITECTURE.md` §6 列的指标之一）。

### 4.4 【高】多 Agent 编排（赛题第 4 项，目前 ❌）

`docs/ARCHITECTURE.md` §3.2 有设计（确定性 DAG，不是让 Agent 聊天）：
Librarian → Reader → Storyteller → Director → ArtDirector → Animator → VoiceActor → Critic → Curator。
缺：**编排器**（阶段注册、依赖顺序、重试、缓存、超时、并发、全链 trace）。

现在各阶段是 `python -m pipeline xxx` 手动串的，`derived/manifest.json` 有阶段与哈希，
但没有 DAG 执行器和 `Trace`。

### 4.5 【中】项目说明书（≤20 页）+ 评测面板

- 说明书 ❌ 未写（材料 b）。`docs/STATUS.md` §3 已经把四项核心任务的完成度列好了，可直接取用；
- 评测面板归 C（`evaluation/`），`pipeline/report.py` 产出的 HTML 可以直接喂给它。

### 4.6 【中】seek 只有 33% 的两处真问题

不是数字问题，是两个 bug：
1. **时间轴**：原来 `seek` 返回页相对时间，播放器按全书绝对时间找页 → 永远落第 1 页。
   **已在本次改动中修好**（`backend/app/interaction.py` 用 timeline 页偏移换算）。
2. **判定基准**：官方脚本没写 seek 的目标页，评测用"页正文重叠最大"当基准，
   有 49/79 条根本推不出基准（`not in []`）。这些既不算对也不算错，需要人工抽检。
   **不要用改判定规则的方式刷这个数字**——那正是第 0 节犯的错。

### 4.7 【低】清理

- `data/books/*/derived/knowledge/uncovered.json`：本次新增，列出答不上的问题，**留着用**；
- `contracts/retrieval.py` 那 154 行：用户说保留但不提交。将来若确认无用再删。

---

## 5. 关键文件速查

| 想改什么 | 去哪 |
| --- | --- |
| 数据结构 | `contracts/models.py`（唯一事实源，改完同步 `docs/DATA_CONTRACT.md`） |
| 问答卡怎么生成 | `pipeline/knowledge.py` |
| 运行时怎么答 | `backend/app/interaction.py`、`backend/app/knowledge.py` |
| 引导式回答 | `backend/app/guide.py`（本次新增，无检索） |
| 共享检索 | `contracts/retrieval.py`（pipeline 与 backend 共用唯一实现） |
| 场景/分镜 | `pipeline/story.py`、`pipeline/scene.py` |
| 视频与字幕 | `pipeline/video.py`、`pipeline/final.py`（字幕烧录可用，音轨合并缺 ffmpeg） |
| 评测 | `pipeline/eval.py`、`pipeline/report.py` |
| 人工修正 | `pipeline/manual.py`（写）→ **后端还没读（待做）** |
| 模型配置 | `config/models.yaml` |
| 分工边界 | `docs/TEAM_DIVISION.md`（§12.2 QA/标注归属、§12.3 三个耦合点） |
| 进度与中心检查 | `docs/STATUS.md` |

---

## 6. 硬约束（别违反）

1. **契约是唯一事实源**：`contracts/models.py` 改字段先改模型，再改 `docs/DATA_CONTRACT.md`；
   破坏性修改要三人确认（`TEAM_DIVISION.md` §8）。
2. **目录所有权**：`frontend/` 是 C 的，`evaluation/` 是 C 的，`contracts/` 三人共管。
   **别人没提交的工作区改动不要带进自己的提交。**
3. **不写死内容**：页面内容、坐标、答案、视频地址一律来自数据，不许硬编码。
4. **原书正文与脚本不入 Git**（`source/`、`book.json` 正文、query_sets 原脚本）；仓库公开可读。
5. **降级不许伪装成功**：没有能力就返回 `status="fallback"`，但**要按契约 §6.2 给引导**——
   "没找到"这种死胡同是不合格的。
6. **来源要写进材料 d**：用了什么模型/数据/工具、调用范围、知识产权承诺。

---

## 7. 一句话总结现状

链路是通的、产物是全的、六本都能出片；
**缺的是"模型在链路里"**——LLM 没接进卡的生产，ASR 没接进提问入口，多 Agent 没做成编排器。
下一位接手的人，请先开 LM Studio 跑 `python -m pipeline knowledge --all --use-llm`：
这一步做完，很多"检索规则"就能退休，运行时也能简单得多。

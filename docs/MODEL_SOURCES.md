# 数据与模型来源清单

> 提交材料 d 要求：数据、模型、工具、图片、文本、音频等素材来源清单及知识产权承诺。
> 本文按"来源 / 许可 / 用在哪 / 是否出本机"四栏列清楚，谁要补谁加一行。

## 一、比赛提供的原始素材

| 素材 | 来源 | 许可 / 使用范围 | 是否出本机 |
| --- | --- | --- | --- |
| 6 本纸质绘本 PDF（中文 3 本、英文 3 本） | 命题组下发（`企业预选赛绘本素材/`） | 授权/脱敏样本，仅限本次比赛 | 否 |
| 每本 50 条 Query 测试音频（WAV） | 命题组下发 | 同上 | 否 |
| 命题组脚本 TXT | 命题组下发 | 同上 | 否 |
| 赛题原文 `纸书智伴.md` | 命题组下发 | 同上 | 否 |

原始素材不进入本仓库（`data/books/`、素材目录已在 `.gitignore` 中），只在本机与网盘共享。队友放在 `data/remote/` 的外部 I2V 成片同样不入 Git。

## 二、模型与工具

| 名称 | 版本 / 获取方式 | 许可 | 用在哪 | 是否出本机 |
| --- | --- | --- | --- | --- |
| RapidOCR | `rapidocr-onnxruntime 1.2.3`，ONNX 权重随包分发；<https://github.com/RapidAI/RapidOCR> | Apache-2.0 | 页面 OCR 文本层与坐标 | 否，本机推理 |
| Qwen3.5-9B（多模态 GGUF + mmproj） | LM Studio 本地模型 `qwen/qwen3.5-9b`；本机路径 `D:\LLM\models\lmstudio-community\Qwen3.5-9B-GGUF` | 以模型卡为准（当前按 Apache-2.0 使用） | 视觉理解（页级叙述/实体/可见文字）、故事与分镜、运行时问答（`weak` 档） | 否，本机推理（LM Studio localhost） |
| faster-whisper small（CTranslate2） | `faster-whisper 1.2.1`；模型 `Systran/faster-whisper-small`，本机目录 `D:\LLM\models\faster-whisper\small` | MIT（faster-whisper）/ MIT（OpenAI Whisper 权重） | 本地测试用语音识别；与 Qwen 共存 | 否，本机推理 |
| faster-whisper large-v3（CTranslate2） | `faster-whisper 1.2.1`；模型 `Systran/faster-whisper-large-v3`，本机目录 `D:\LLM\models\faster-whisper\large-v3` | MIT | 单人跑 300 条官方音频评测时使用；与 Qwen 同跑会 OOM | 否，本机推理 |
| NVIDIA Nemotron-3-Nano-4B-GGUF | LM Studio 本地下载 | NVIDIA Open Model License | 备用文本模型；已试跑运行时问答，质量弱于 Qwen | 否 |
| Edge TTS | `edge-tts 7.3.1`；中文 `zh-CN-XiaoyiNeural`，英文 `en-US-AriaNeural`；调用微软在线语音服务 | MIT（客户端）/ 微软服务条款 | 旁白生成；运行时答案音频（`answer.audio_path`） | **是**：只发送待朗读文本，不发送页图；离线模式关闭 |
| 火山方舟 I2V（可选） | `ARK_API_KEY` + `ARK_MODEL_ID`；字节/火山方舟视频生成模型（具体模型 ID 以控制台为准） | 火山引擎服务条款，闭源 | 重点页图生视频 | **是**：会上传页图与提示词；未配置密钥或离线时自动降级为页动画 |
| 外部 I2V 成片（zh-01 / en-01） | 队友用外部 API 生成；供应商、模型、seed、调用参数仍在确认（疑似字节系，待书面确认） | 以最终供应商条款为准 | 两本 AI 动画版成片（作为视频变体，不替换 canonical） | **是**：生成时已上传页图与提示词；来源、许可与调用范围需在提交材料中补全 |
| PyMuPDF | `pymupdf 1.28.2`，<https://pymupdf.readthedocs.io/> | **AGPL-3.0** | PDF 渲染与文本层抽取 | 否；如对外分发需评估 AGPL 义务 |
| OpenCV | `opencv-python-headless >=4.9,<5` | Apache-2.0 | 页动画视频合成、缩略图 | 否 |
| imageio-ffmpeg | `imageio-ffmpeg >=0.5,<1`（附带 ffmpeg 二进制） | BSD / FFmpeg LGPL（以实际构建为准） | 配音重定时与终版合成 | 否 |
| Pillow | `Pillow >=10` | MIT-CMU | 审核图、字幕渲染 | 否 |
| FastAPI / uvicorn | `fastapi` / `uvicorn` | MIT / BSD | 运行时 API 与联调服务 | 否 |
| pydantic | `pydantic >=2.7` | MIT | 数据契约模型与校验 | 否 |
| PyYAML / requests / numpy | `PyYAML >=6.0`、`requests >=2.31`、`numpy >=1.24` | MIT / Apache-2.0 / BSD | 配置、HTTP、数组处理 | 否 |

除 Edge TTS、火山方舟 I2V 和队友的外部 I2V 成片外，全部在本机运行；本地模型不把原书素材发到外网。

## 二点五、运行时出网矩阵

| 场景 | 实际提供方 | 出网数据 | 失败 / 离线降级 |
| --- | --- | --- | --- |
| 阅读、页动画播放、点击/检索/seek | 本机 | 无 | 不依赖网络 |
| 文字问答命中 QA 卡 | 本机 | 无 | 不依赖网络 |
| 无卡问题的 LLM 兜底 | LM Studio localhost（可改为远端 OpenAI 兼容服务） | 默认只有问题与检索到的书内片段，且在本机；改远端时才出网 | 模型不可用 → guide 引导 |
| 语音识别 | faster-whisper 本机 | 无 | 模型缺失 → 返回“语音识别不可用” |
| 答案 TTS | Edge TTS（微软） | 答案文本 | 失败 → 前端浏览器朗读；`DREAMYTALE_ANSWER_TTS=off` 完全关闭 |
| 旁白生成 | Edge TTS（微软） | 旁白文本 | 已有旁白音频可继续播放；重新生成时失败则该阶段降级 |
| 重点页 I2V 生成 | 火山方舟 | 页图、提示词 | 无密钥/超时/离线 → 页动画 |
| 外部 AI 动画成片 | 队友的外部 API（待确认） | 页图、提示词（生成时） | 只作为可选视频变体；不参与 canonical |

数据保留与密钥：
- Edge TTS 与火山方舟的数据保留、日志策略以各自服务条款为准；提交材料中只写调用范围，不写密钥。
- 密钥只通过环境变量（`ARK_API_KEY`、`ARK_MODEL_ID`）注入，不进入 Git、不写进前端。
- 离线演示使用已生成的旁白音频与本地模型；`start.ps1 -Offline` 会关闭答案 TTS 并设置 `HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE`，避免模型下载。

## 三、我们自己产生的内容

| 产物 | 生成方式 | 归属 | 是否入 Git |
| --- | --- | --- | --- |
| `book.json` / `query_sets/*.json` | 由 PDF 与脚本解析得到 | 团队 | 否（含原书正文与脚本） |
| `derived/understanding/*` | OCR + 本地 VLM | 团队 | 否（含原书文字） |
| `derived/story/story_plan.json` | 本地 LLM 依据书稿改写 | 团队 | 否 |
| `derived/scene/scene_plan.json`、`timeline.json` | 由 StoryPlan 确定性推导 | 团队 | 否 |
| `derived/knowledge/cards.jsonl` | 依据官方问题 + 书稿生成 | 团队 | 否 |
| `book.json` 内的 `hotspots` | 文字层 + 本地 VLM 定位；额外文字热点由页面 span 生成 | 团队 | 否（含原书文字） |
| `derived/audio/narration/*` | Edge TTS 依据旁白文本合成 | 团队 | 否 |
| `derived/audio/answer/*.mp3` | 运行时答案 TTS 缓存，按文本哈希命名 | 团队 | 否 |
| `derived/video/*.mp4`、`thumbs/*.jpg` | 页动画 / I2V | 团队 | 否 |
| `derived/manifest.json`、`generation_result.json` | 生成清单与哈希 | 团队 | 否 |
| `runs/*/results.jsonl` | 评测回放 | 团队 | 否 |
| `docs/`、`contracts/`、`pipeline/`、`backend/`、`frontend/` | 团队代码与文档 | 团队 | 是 |

## 四、第三方代码引用

| 组件 | 来源 | 许可 |
| --- | --- | --- |
| 契约与页面渲染 | 自研（`contracts/`、`pipeline/`） | 团队 |
| 阅读器前端 | 自研（`frontend/`，无 Node 构建依赖） | 团队 |

## 五、承诺

1. 不把命题组原始素材、原书正文、命题组脚本、测试音频提交到公开仓库；仓库只放代码、配置与文档。
2. 使用开源组件时遵守各自许可证；闭源服务（Edge TTS、火山方舟 I2V、队友外部 I2V）在提交材料中单独说明调用范围、数据保留与密钥管理方式。
3. 送评的演示视频、说明书与界面截图中涉及的书页内容，仅来自授权样本。
4. 团队共同产出的代码、提示词与文档由三位成员共有，署名在项目说明书中列明。
5. 不把任何 API 密钥、账号密码、供应商控制台截图写进仓库或演示材料；第三方素材/模型如有新的来源，在本文件追加一行再使用。

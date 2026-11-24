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

原始素材不进入本仓库（`data/books/`、素材目录已在 `.gitignore` 中），只在本机与网盘共享。

## 二、模型与工具

| 名称 | 版本 / 获取方式 | 许可 | 用在哪 | 是否出本机 |
| --- | --- | --- | --- | --- |
| RapidOCR | `pip install rapidocr-onnxruntime`，ONNX 权重随包分发 | Apache-2.0 | 页面 OCR 文本层与坐标 | 否，本机推理 |
| Qwen3.5-9B（多模态 GGUF + mmproj） | LM Studio 本地下载（`D:\LLM\models\lmstudio-community\Qwen3.5-9B-GGUF`） | Apache-2.0 | 视觉理解（页级叙述/实体/可见文字）、故事与分镜、运行时问答（`weak` 档） | 否，本机推理 |
| faster-whisper small（CTranslate2） | 本地模型目录 `D:\LLM\models\faster-whisper\small` | MIT（faster-whisper）/ MIT（OpenAI Whisper 权重） | 本地测试用语音识别；与 Qwen 共存 | 否，本机推理 |
| faster-whisper large-v3（CTranslate2） | 本地模型目录 `D:\LLM\models\faster-whisper\large-v3` | MIT | 单人跑 300 条官方音频评测时使用；与 Qwen 同跑会 OOM | 否，本机推理 |
| NVIDIA Nemotron-3-Nano-4B-GGUF | LM Studio 本地下载 | NVIDIA Open Model License | 备用文本模型；已试跑运行时问答，质量弱于 Qwen | 否 |
| 三方 API（演示计划） | 待定（LLM/VLM/ASR/TTS/I2V） | 以最终供应商条款为准 | 演示时替换本地模型；调用范围、费用与密钥管理需补进本节 | **是**：会把书页/问题/音频发给供应商，启用前需三人确认 |
| Edge TTS | `pip install edge-tts`，调用微软在线语音服务 | MIT（客户端）/ 微软服务条款 | 旁白配音 | **是**：只有旁白文本出网，不含原书正文以外的数据 |
| 火山方舟 I2V（可选） | `ARK_API_KEY` + `ARK_MODEL_ID` | 火山引擎服务条款，闭源 | 重点页图生视频 | **是**：会上传页图与提示词；未配置密钥时自动降级为页动画 |
| PyMuPDF | `pip install pymupdf` | AGPL-3.0 | PDF 渲染与文本层抽取 | 否 |
| OpenCV | `pip install opencv-python-headless` | Apache-2.0 | 页动画视频合成、缩略图 | 否 |
| imageio-ffmpeg | `pip install imageio-ffmpeg`（附带 ffmpeg 二进制） | BSD / FFmpeg LGPL | 配音重定时与终版合成 | 否 |
| Pillow | `pip install pillow` | MIT-CMU | 审核图、字幕渲染 | 否 |
| FastAPI / uvicorn | `pip install fastapi uvicorn` | MIT / BSD | 运行时 API 与联调服务 | 否 |
| pydantic | `pip install pydantic` | MIT | 数据契约模型与校验 | 否 |

除 Edge TTS 与（可选的）火山方舟外，全部在本机运行，原始素材不出本机。

## 三、我们自己产生的内容

| 产物 | 生成方式 | 归属 | 是否入 Git |
| --- | --- | --- | --- |
| `book.json` / `query_sets/*.json` | 由 PDF 与脚本解析得到 | 团队 | 否（含原书正文与脚本） |
| `derived/understanding/*` | OCR + 本地 VLM | 团队 | 否（含原书文字） |
| `derived/story/story_plan.json` | 本地 LLM 依据书稿改写 | 团队 | 否 |
| `derived/scene/scene_plan.json`、`timeline.json` | 由 StoryPlan 确定性推导 | 团队 | 否 |
| `derived/knowledge/cards.jsonl` | 依据官方问题 + 书稿生成 | 团队 | 否 |
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
2. 使用开源组件时遵守各自许可证；闭源服务（火山方舟 I2V）如启用，在提交材料中单独说明调用范围与密钥管理方式。
3. 送评的演示视频、说明书与界面截图中涉及的书页内容，仅来自授权样本。
4. 团队共同产出的代码、提示词与文档由三位成员共有，署名在项目说明书中列明。

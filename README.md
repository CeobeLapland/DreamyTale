# DreamyTale / 纸书智伴

把纸质绘本变成可播放、可检索、可问答、可人工修正的互动读物。
目标不是只回答六本书的 300 条问题，而是任意 PDF/照片都能走同一条链路。

进度与中心检查：[`docs/STATUS.md`](docs/STATUS.md)。

## 现在有什么

- `docs/ARCHITECTURE.md`：产品边界、离线/在线两条链、多 Agent 编排、模型适配层、通用性、人工修正、视频策略、延迟预算、分工建议。
- `docs/DATA_CONTRACT.md`：v2.0.0 契约。书与题目分离、页级 block、知识层/人工修正、生成产物、统一交互协议、能力报告、评测契约。
- `pipeline/`：内容工厂参考实现。PDF 入库（页图 + block/span + `book.json`）、OCR 理解、VLM 叙事、覆盖率检查。
- `pipeline/query_sets.py`：命题组 txt → `QuerySet`，归一化音频；六本各 50 条。
- `pipeline/coverage.py`：用现有页面文字做覆盖检查，列出还需要 OCR/VLM、场景、QA 卡、热区的目标。
- `pipeline/models/`：OCR/VLM 提供方适配层；`config/models.yaml` 决定用谁，换模型不改业务代码。
- `contracts/`：`book.json` / `QuerySet` 的 Pydantic 模型与校验 CLI。
- `docs/MODEL_SOURCES.md`：数据、模型、工具、音频的来源 / 许可 / 是否出本机清单，含运行时出网矩阵与知识产权承诺。

## 当前状态

- 六本 PDF 共 120 页已入库；六份脚本解析成 300 个 QueryItem / 328 个动作。
- 文本层：RapidOCR（免费本地）+ 本地视觉模型（LM Studio 的 `qwen3.5-9b`）出页级叙述、实体、可见文字。
- 生成链路：`StoryPlan` → `ScenePlan` → 检索索引 → 页动画视频 → edge-tts 旁白 → retime → 字幕烧录 + AAC 混音；终版为 H.264 + faststart。
- 编排：`pipeline/orchestrator.py` 14 阶段（含 Critic），带依赖、缓存、manifest、trace；`python -m pipeline run --book zh-01` 一条命令出片。
- 知识层：按官方脚本的每条 qa 问题生成 `QaCard`（三档答案 + 证据 + 视频锚点），运行时直接消费。
- 交互：`POST /api/interact` 六类动作返回真实结果与证据；`/api/interact/audio` 本地 faster-whisper 转写；无卡问题走运行时 LLM（Qwen）或 guide。
- 在线编排：`backend/app/conductor.py` 工具注册表 + 规则多意图；每轮写 `data/turns/` 与 `data/traces/`。
- 阅读器：书架/上传/生成/播放、对话、审核修正、生成链路、评测合并为单页（`/reader/`）；播放时可打开“视频物体”，在视频上点当前页热点。
- 评测：`python -m pipeline eval --all` 回放 328 个动作，按 kind 分桶给出正确率、证据率、分 kind p50/p95、意图分类准确率与较上次运行的差值。
- 还没做完：I2V 真跑（火山方舟适配器已接，缺 key/模型 ID）、视频内真逐帧物体跟踪（当前用热点叠加 + 镜头近似）、六本重跑一致性校验、5 分钟演示视频与说明书。

## 一键启动

Windows 下双击 `start.bat`，或在 PowerShell 里：

```powershell
.\start.ps1                 # 起服务并自动打开 http://127.0.0.1:8000/reader/
.\start.ps1 -Port 8011      # 换端口
.\start.ps1 -NoBrowser      # 只起服务，不开浏览器
.\start.ps1 -Offline        # 离线演示，见下一节
```

脚本依次检查 Python（优先 `.venv\Scripts\python.exe`）、`fastapi/uvicorn`、端口，然后起 uvicorn；服务就绪后打开阅读器，按 `Ctrl+C` 停止。端口上已有本服务时直接打开页面，不会重复启动。

## 快速开始

```bash
# 六本 PDF -> 页图 + book.json + QuerySet + coverage + 校验
python -m pipeline all

# OCR 理解（免费本地默认；没装 OCR 会安全跳过）
python -m pipeline understand --all

# VLM 页叙事（需要先在 config/models.yaml 配一个 VLM；默认 null 跳过）
python -m pipeline narrative --all

# 故事与分镜（需要文本模型）
python -m pipeline story --all
python -m pipeline scene --all

# 一条命令跑完整生成链（缓存命中会跳过已完成的阶段）
python -m pipeline run --book zh-01
python -m pipeline run --book zh-01 --from index --to critic

# 检索索引 + 知识层（QA 卡）+ 视频
python -m pipeline index --all
python -m pipeline knowledge --all --use-llm
python -m pipeline video --all
python -m pipeline final --all

# 看当前 OCR/VLM/LLM/I2V 用的是谁
python -m pipeline models

# 生成一页可视化审核图（PDF block / OCR / 目标短语）
python -m pipeline review --book zh-01 --page 6 --target "我又不是故意的"

# 回放评测（需要先起服务）
python -m uvicorn backend.app.c_demo:app --port 8000
python -m pipeline eval --all

# 答案 TTS：默认只给语音输入合成；设为 always 让文字回答也带音频
# $env:DREAMYTALE_ANSWER_TTS = "always"   # PowerShell

# 只跑某一步
python -m pipeline ingest --all
python -m pipeline parse-scripts --all
python -m pipeline coverage --all
python -m contracts.validate --all

# 任意 PDF
python -m pipeline ingest --pdf path/to/book.pdf --book-id my-book --language zh-CN
```

依赖：Python 3.11+、`pymupdf`、`pydantic`、`PyYAML`、`opencv-python-headless`、`imageio-ffmpeg`。
旁白和答案音频需要 `edge-tts`（会调用微软在线语音服务）；OCR 可选：

```bash
pip install -r requirements.txt
pip install -r requirements-ocr.txt   # 可选，免费本地 OCR
# 国内网络慢可加：-i https://pypi.tuna.tsinghua.edu.cn/simple
```

模型提供方在 `config/models.yaml` 里切换；业务代码不直接调 SDK。

## 离线说明

`.\start.ps1 -Offline` 会设置 `DREAMYTALE_ANSWER_TTS=off`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，避免运行时调用在线语音服务和下载模型。

离线仍可演示：

- 阅读、翻页、页动画视频、字幕、视频物体点击、检索、seek、QA 卡问答、审核修正、评测回放：全部在本机。
- 语音识别：faster-whisper 本机模型；模型缺失时接口明确返回“语音识别不可用”，不会假装听懂。
- 已生成的旁白音频照常播放（`data/books/<book_id>/derived/audio/narration/`）。

离线会自动降级或不可用：

- 运行时答案 TTS：关闭后改为前端浏览器朗读，不再向微软发请求；已缓存的 `derived/audio/answer/*.mp3` 仍保留，有网时可继续用。
- 无 QA 卡问题的 LLM 兜底：需要 LM Studio 在本机 `localhost:1234` 已加载模型；没开则返回 guide 引导。
- 重新生成旁白（edge-tts）、火山方舟 I2V、首次下载模型：需要网络，离线时跳过或降级为页动画。

首次准备（有网时做一次，之后可断网演示）：

```powershell
pip install -r requirements.txt
pip install -r requirements-ocr.txt        # 可选，本地 OCR

python -m pipeline all                     # 六本 PDF -> 数据包
python -m pipeline run --book zh-01        # 或 --all，生成视频/旁白/字幕
```

## 数据约定

`data/books/<book_id>/` 是本地数据包，**不入 Git**：里面有原书正文、命题组脚本、页图和音视频。
公开仓库只放代码、配置、文档和脱敏后的示例数据。答辩材料单独打包。

目录结构与字段定义见 [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md)。

## 目录

```text
backend/       运行时、API、任务、媒体、适配器、交互协议
pipeline/      内容工厂、阶段编排、生成、评测回放
config/        models.yaml：OCR/VLM/LLM/I2V 等提供方配置
prompts/       版本化提示词（待做）
contracts/     数据契约模型与校验
frontend/      阅读器（C 主责，初版已可运行）
evaluation/    评测面板、演示素材（C 主责）
data/books/    本地单书数据包（不入 Git）
runs/          评测回放结果（不入 Git）
docs/          架构与契约
```

## 下一步

1. 重点页 I2V 真跑（缺 `ARK_API_KEY` / `ARK_MODEL_ID`）；视频内物体目前是热点叠加 + 镜头近似，真逐帧跟踪未做。
2. 多轮指代（`last_scene_id/last_entities`），让“它 / 这里”接住上一轮。
3. 六本全链重跑一致性校验；评测页已合并进 `/reader/`。
4. 5 分钟演示视频与项目说明书。

## 赛题

赛题原文见 [`纸书智伴.md`](纸书智伴.md)。

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

## 当前状态

- 六本 PDF 共 120 页已入库；六份脚本解析成 300 个 QueryItem / 328 个动作。
- 文本层：RapidOCR（免费本地）+ 本地视觉模型（LM Studio 的 `qwen3.5-9b`）出页级叙述、实体、可见文字。
- 生成链路：`StoryPlan` → `ScenePlan` → 检索索引 → 页动画视频 → edge-tts 旁白 → retime → 字幕烧录 + AAC 混音；终版为 H.264 + faststart。
- 编排：`pipeline/orchestrator.py` 14 阶段（含 Critic），带依赖、缓存、manifest、trace；`python -m pipeline run --book zh-01` 一条命令出片。
- 知识层：按官方脚本的每条 qa 问题生成 `QaCard`（三档答案 + 证据 + 视频锚点），运行时直接消费。
- 交互：`POST /api/interact` 六类动作返回真实结果与证据；`/api/interact/audio` 本地 faster-whisper 转写；无卡问题走运行时 LLM（Qwen）或 guide。
- 在线编排：`backend/app/conductor.py` 工具注册表 + 规则多意图；每轮写 `data/turns/` 与 `data/traces/`。
- 阅读器：书架/上传/生成/播放、对话、审核修正、生成链路、评测合并为单页（`/reader/`）。
- 评测：`python -m pipeline eval --all` 回放 328 个动作，按 kind 分桶给出正确率、证据率与 p50/p95。
- 还没做完：I2V 真跑（代码与字节/火山方舟适配器已接，缺 key/模型 ID）、纯视觉物体定位、低置信 ASR 复述确认、六本重跑一致性校验、5 分钟演示视频与说明书。

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

# 只跑某一步
python -m pipeline ingest --all
python -m pipeline parse-scripts --all
python -m pipeline coverage --all
python -m contracts.validate --all

# 任意 PDF
python -m pipeline ingest --pdf path/to/book.pdf --book-id my-book --language zh-CN
```

依赖：Python 3.11+、`pymupdf`、`pydantic`、`PyYAML`、`opencv-python-headless`、`imageio-ffmpeg`。
旁白需要 `edge-tts`（会调用微软在线语音服务）；OCR 可选：

```bash
pip install -r requirements.txt
pip install -r requirements-ocr.txt   # 可选，免费本地 OCR
# 国内网络慢可加：-i https://pypi.tuna.tsinghua.edu.cn/simple
```

模型提供方在 `config/models.yaml` 里切换；业务代码不直接调 SDK。

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

1. 重点页 I2V 与视频内动态物体点击：Scene `objects` 为空，需要 VLM 定位物体 bbox。
2. 低置信 ASR 复述确认与多轮指代（`last_scene_id/last_entities`）。
3. 六本全链重跑一致性校验与评测报告页。
4. 5 分钟演示视频与项目说明书。

## 赛题

赛题原文见 [`纸书智伴.md`](纸书智伴.md)。

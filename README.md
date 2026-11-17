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
- RapidOCR（免费本地）已跑通：搜索/高亮目标只剩 `zh-02` 的“小刺猬”未命中（插画文字，需 VLM/人工补）。
- OCR 会去掉与 PDF 文本重叠的结果，并按 `config/models.yaml` 的 `watermark_phrases` 过滤水印碎片；重跑是幂等的。
- VLM 页叙事适配已接好，默认 `null`；配好本地/远程视觉模型后运行 `python -m pipeline narrative --all`。
- 场景、QA 卡、点击热区还没生成；`derived/coverage_report.json` 里是待办清单。

## 快速开始

```bash
# 六本 PDF -> 页图 + book.json + QuerySet + coverage + 校验
python -m pipeline all

# OCR 理解（免费本地默认；没装 OCR 会安全跳过）
python -m pipeline understand --all

# VLM 页叙事（需要先在 config/models.yaml 配一个 VLM；默认 null 跳过）
python -m pipeline narrative --all

# 看当前 OCR/VLM 用的是谁
python -m pipeline models

# 生成一页可视化审核图（PDF block / OCR / 目标短语）
python -m pipeline review --book zh-01 --page 6 --target "我又不是故意的"

# 只跑某一步
python -m pipeline ingest --all
python -m pipeline parse-scripts --all
python -m pipeline coverage --all
python -m contracts.validate --all

# 任意 PDF
python -m pipeline ingest --pdf path/to/book.pdf --book-id my-book --language zh-CN
```

依赖：Python 3.11+、`pymupdf`、`pydantic`、`PyYAML`。OCR 可选：

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
backend/       运行时、API、任务、媒体、适配器（待做）
pipeline/      内容工厂、阶段编排、生成
config/        models.yaml：OCR/VLM/LLM 等提供方配置
prompts/       版本化提示词（待做）
contracts/     数据契约模型与校验
frontend/      阅读器、审核页、评测面板（待做）
evaluation/    评测脚本、结果、演示素材（待做）
data/books/    本地单书数据包（不入 Git）
docs/          架构与契约
```

## 下一步

1. VLM 叙事：本机跑一个 Ollama/LM Studio 的视觉模型，或用免费 API；改 `config/models.yaml` 即可，不改代码。
2. StoryPlan / ScenePlan：角色、逐页旁白、scene 时间轴、字幕、aliases、物体框。
3. 视频/配音/合成：页动画 + 重点页 I2V + TTS。
4. 知识层：PageFact / QaCard / Alias，人工审核与覆盖。
5. 在线交互：`/api/interact`、播放器、评测回放。

## 赛题

赛题原文见 [`纸书智伴.md`](纸书智伴.md)。

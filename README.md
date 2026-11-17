# DreamyTale / 纸书智伴

把纸质绘本变成可播放、可检索、可问答、可人工修正的互动读物。
目标不是只回答六本书的 300 条问题，而是任意 PDF/照片都能走同一条链路。

## 现在有什么

- `docs/ARCHITECTURE.md`：产品边界、离线/在线两条链、多 Agent 编排、模型适配层、通用性、人工修正、视频策略、延迟预算、分工建议。
- `docs/DATA_CONTRACT.md`：v2.0.0 契约。书与题目分离、页级 block、知识层/人工修正、生成产物、统一交互协议、能力报告、评测契约。
- `pipeline/`：PDF 入库参考实现。渲染页图、抽取文本层 block/span、过滤水印/页脚/教学文字、写 `book.json`。
- `pipeline/query_sets.py`：命题组 txt → `QuerySet`，归一化音频；六本各 50 条。
- `pipeline/coverage.py`：用现有页面文字做覆盖检查，列出还需要 OCR/VLM、场景、QA 卡、热区的目标。
- `contracts/`：`book.json` / `QuerySet` 的 Pydantic 模型与校验 CLI。

## 快速开始

```bash
# 六本 PDF -> 页图 + book.json + QuerySet + coverage + 校验
python -m pipeline all

# 只跑某一步
python -m pipeline ingest --all
python -m pipeline parse-scripts --all
python -m pipeline coverage --all
python -m contracts.validate --all

# 任意 PDF
python -m pipeline ingest --pdf path/to/book.pdf --book-id my-book --language zh-CN
```

依赖：Python 3.11+、`pymupdf`、`pydantic`。不需要 GPU。

## 数据约定

`data/books/<book_id>/` 是本地数据包，**不入 Git**：里面有原书正文、命题组脚本、页图和音视频。
公开仓库只放代码、配置、文档和脱敏后的示例数据。答辩材料单独打包。

目录结构与字段定义见 [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md)。

## 目录

```text
backend/       运行时、API、任务、媒体、适配器（待做）
pipeline/      内容工厂、阶段编排、生成
prompts/       版本化提示词（待做）
contracts/     数据契约模型与校验
frontend/      阅读器、审核页、评测面板（待做）
evaluation/    评测脚本、结果、演示素材（待做）
data/books/    本地单书数据包（不入 Git）
docs/          架构与契约
```

## 下一步

1. OCR/VLM 理解阶段：补栅格化对白（例如 `zh-01` 的“我又不是故意的”）。
2. StoryPlan / ScenePlan：角色、逐页旁白、scene 时间轴、字幕、aliases、物体框。
3. 视频/配音/合成：页动画 + 重点页 I2V + TTS。
4. 知识层：PageFact / QaCard / Alias，人工审核与覆盖。
5. 在线交互：`/api/interact`、播放器、评测回放。

## 赛题

赛题原文见 [`纸书智伴.md`](纸书智伴.md)。

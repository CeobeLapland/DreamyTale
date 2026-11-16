# 纸书智伴 / DreamyTale

> 翻到哪一页，屏幕就演到哪一页；指什么，它就讲什么；问什么，它就答什么。

面向 3–8 岁儿童的纸质绘本智能伴读系统。PDF/纸书 → 图文理解 → 风格一致的分页动画 → 语音与触摸交互（播放控制 / 找画面 / 查台词 / 点物体 / 问答）。

参赛：第二届北京市大学生「人工智能+」创新大赛 · 纸书智伴赛题

---

## 现在在哪

M0 地基完成。文档、素材解析、数据契约、冷启动入库、意图路由都已就位。播放器未开工。

已完成：
- 六本绘本 **120 页**已拆图入库（`data/books/*/`），每页带文本块与 bbox
- 命题组脚本解析成 328 条结构化交互（`data/queries/`）
- 数据契约 + 校验器：`python tasks.py lint`，零依赖，448 条记录零错误
- 六类意图路由：`python tasks.py route`，脚本基准 328/328
- 能力盘点：`python tasks.py audit`，任何书进来都能说清它会什么、不会什么
- **本地演示可跑**：`python tasks.py serve` → 浏览器里翻页、播放、找画面、查台词、点物体
- 六类路由执行器 + 会话状态 + 评测：`control` 65/65，中文书找画面 86%（见 04 基线）

另有一本 **130 页扫描版化学教材**（`data/books/chem01/`）作为反向样本：没有文本层，用来验证系统在"读不进文字"时是否老实报缺，而不是假装能答。

## 五分钟上手

1. 读 [`docs/README.md`](docs/README.md)（文档索引 + 三条铁律）
2. 读 [`docs/00-产品定义.md`](docs/00-产品定义.md)（我们到底做什么、不做什么）
3. 读 [`docs/01-架构设计.md`](docs/01-架构设计.md)（五层结构、六类路由）

这三篇读完，就能开始干活。其余按需查。

## 常用命令

```
python tasks.py parse    # 命题组 txt -> data/queries/*.jsonl
python tasks.py lint     # 校验一切 jsonl 是否符合 docs/02 契约
python tasks.py route    # 六类意图路由的两套基准
python tasks.py ingest   # 任意 PDF -> 页图 + PageDocument（需 pypdfium2）
python tasks.py audit    # 盘点每本书支持哪些交互、缺什么
python tasks.py timeline # 由页数据生成占位时间轴
python tasks.py eval     # 按脚本回放，出准确率和延迟
python tasks.py serve    # 本地演示 http://127.0.0.1:8765
python tasks.py check    # 提交前跑这个
```

`lint` 和 `route` 零依赖，clone 即跑。只有 `ingest` 和图像相关的要先 `pip install -r requirements.txt`。

Windows 没装 make 也没关系，`tasks.py` 是跨平台入口。

## 接入模型

所有模型调用走 `tools/llm.py`，OpenAI 兼容协议——LM Studio、Ollama、vLLM、通义、智谱、Kimi、DeepSeek、OpenAI 同一套。

```
LLM_BASE_URL=http://127.0.0.1:1234/v1     # LM Studio 默认
LLM_API_KEY=lm-studio                     # 本地随便填
LLM_MODEL=                                # 留空则自动探测
LLM_VL_MODEL=                             # 视觉模型，留空自动探测
LLM_EMBED_MODEL=                          # 向量模型，留空自动探测
```

配好后：

```
python tasks.py llm           # 看状态
python tasks.py llm --ping    # 真发一次请求验证链路
python tasks.py index         # 建向量索引（知识层的前提）
python tasks.py narrative --all   # VLM 把书页读成文字（英文三本的前提）
```

**没有配置也能跑**：`lint` / `route` / `timeline` / `eval` / `audit` / `serve` 全部零依赖，只是问答会退化成"引用原句"。

## 328 条交互的构成

- control 播放/暂停/继续/结束 **65**
- seek 找画面 **79**
- search 查文字 **20**
- highlight 高亮 **19**
- touch 点击物体 **28**
- qa 问答 **117**

**64% 的交互不需要生成能力**，只需要检索与执行。排期优先级就按这个来。

但这 328 条**是样本，不是规格**。检验通用性的唯一方法是拿一本没见过的书跑一遍、代码一行不改。见 [`docs/decisions/0003`](docs/decisions/0003-328条是样本不是规格.md)。

## 目录约定

- `docs/` — 全部文档。编号即阅读顺序
- `docs/decisions/` — 架构决策记录（轻量 ADR），改主意时写一篇
- `tasks.py` — 统一入口
- `data/queries/` — 解析产物，进 git
- `data/books/` — 书籍资产与标注产物（生成缓存不入库）
- `tools/` — 命令行工具（零依赖优先）
- `web/` — 演示前端
- `企业预选赛绘本素材/` — 命题组原始素材，只读
- `abandoned/` — 历史遗留，已 gitignore，不再维护

## 赛题原文

[`纸书智伴.md`](纸书智伴.md)

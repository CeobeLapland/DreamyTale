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
python tasks.py ingest   # 任意 PDF -> 页图 + PageDocument（需 PyMuPDF）
python tasks.py check    # 提交前跑这个
```

`lint` 和 `route` 零依赖，clone 即跑。只有 `ingest` 和图像相关的要先 `pip install -r requirements.txt`。

Windows 没装 make 也没关系，`tasks.py` 是跨平台入口。

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
- `tools/` — 纯标准库脚本，clone 即跑
- `tasks.py` — 统一入口
- `data/queries/` — 解析产物，进 git
- `data/books/` — 书籍资产与标注产物（生成缓存不入库）
- `src/` — 待建
- `企业预选赛绘本素材/` — 命题组原始素材，只读
- `abandoned/` — 历史遗留，已 gitignore，不再维护

## 赛题原文

[`纸书智伴.md`](纸书智伴.md)

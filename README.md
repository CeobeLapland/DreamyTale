# 纸书智伴 / DreamyTale

把纸质绘本变成"会开演"的互动剧场。参赛项目：第二届北京市大学生"人工智能+"创新大赛。

## 现在到哪了

概念已定，未开始写代码。当前产出：产品定义、功能清单、架构方案、演示脚本骨架。

## 文件索引

```
DreamyTale/
├─ README.md                        ← 你在这里
├─ 纸书智伴.md                       赛题原文（只读）
├─ docs/
│  ├─ PRODUCT.md                    产品定义、本版范围、不做什么
│  ├─ 纸书智伴_功能清单.md            做什么、优先级 P0–P3
│  ├─ ARCH.md                       架构、技术栈、延迟预算、降级链
│  ├─ ROADMAP.md                    分几个阶段、每阶段交付什么
│  ├─ PLAN.md                       当前任务看板（每天更新）
│  ├─ DEMO.md                       5 分钟脚本、兜底、上场检查清单
│  ├─ EVAL.md                       指标定义与跑分记录（只追加）
│  └─ SOURCES.md                    素材 / 模型 / 许可证、预生成披露
├─ contracts/
│  ├─ book_asset.schema.json        书资产契约：A 产出、B 填充、C 只读
│  └─ events.ts                     前后端 WebSocket 事件类型
└─ temp/
   ├─ 一页剧团_GDD.md                早期参考稿，已冻结
   └─ 纸书智伴.md                    赛题副本，可删
```

## 按场景找文件

| 我想… | 看这个 |
|---|---|
| 知道这项目是什么 | [PRODUCT.md](docs/PRODUCT.md) |
| 知道要做哪些功能 | [功能清单](docs/纸书智伴_功能清单.md) |
| 知道怎么接、用什么 | [ARCH.md](docs/ARCH.md) + [contracts/](contracts/) |
| 知道现在该做什么 | [ROADMAP.md](docs/ROADMAP.md) → [PLAN.md](docs/PLAN.md) |
| 知道怎么演 | [DEMO.md](docs/DEMO.md) |
| 知道跑分多少 | [EVAL.md](docs/EVAL.md) |
| 知道素材哪来的 | [SOURCES.md](docs/SOURCES.md) |
| 想翻早期想法 | [一页剧团_GDD.md](temp/一页剧团_GDD.md) |

## 30 分钟上手

1. 读 `PRODUCT.md`（3 分钟）
2. 扫功能清单里的 P0（5 分钟）
3. 读 `ARCH.md` 的总图和七条链路（10 分钟）
4. 看 `PLAN.md` 里自己的名字（2 分钟）

## 三条铁律

1. **一个事实只写一处。** 功能清单管"做什么"，ARCH 管"怎么接"，PLAN 管"谁在做"，DEMO 管"怎么演"。别互相抄。
2. **只维护会被读第二次的东西。** 聊天里定下的结论，当天要么进文档，要么作废。
3. **文档跟着代码走。** 改接口、改字段、改脚本时顺手改对应文档，不单独开文档评审。

## 跑起来

（环境搭好后把启动命令填在这里，三行以内。）

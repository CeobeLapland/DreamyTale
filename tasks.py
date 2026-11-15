#!/usr/bin/env python3
"""项目统一入口。跨平台，Windows 没有 make 也能跑。

    python tasks.py lint      校验数据是否符合 docs/02 契约
    python tasks.py parse     把命题组 txt 脚本解析成 data/queries/
    python tasks.py check     提交前跑这个
    python tasks.py eval      评测（待实现）
    python tasks.py clean     清临时产物

Windows 上如果装了 make，`make lint-data` 等价于 `python tasks.py lint`。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

TASKS = {}


def task(name, help_text):
    def deco(fn):
        TASKS[name] = (fn, help_text)
        return fn
    return deco


def run(*args):
    cmd = [PY, *args]
    print(f"$ {' '.join(str(a) for a in args)}")
    return subprocess.call(cmd, cwd=ROOT)


@task("parse", "把命题组 txt 脚本解析成 data/queries/*.jsonl")
def parse():
    return run("tools/parse_scripts.py")


@task("lint", "校验所有 jsonl 是否符合 docs/02 契约")
def lint():
    return run("tools/lint_data.py")


@task("check", "提交前跑这个（lint + 后续要加的测试）")
def check():
    code = lint()
    if code:
        print("\ncheck 未通过，先修错误再提交")
        return code
    print("\ncheck 通过")
    return 0


@task("ingest", "任意 PDF 入库：拆页图 + PageDocument（需 PyMuPDF）")
def ingest():
    return run("tools/ingest_book.py", *sys.argv[2:])


@task("route", "跑六类意图路由：脚本基准 + 口语基准")
def route():
    return run("tools/classify.py", "--bench")


@task("eval", "全量评测 328 条（待实现）")
def evaluate():
    print("TODO: 评测 harness，见 docs/04-评测方案.md")
    print("     先用 python tasks.py lint 保证数据是干净的")
    return 0


@task("clean", "清临时产物（不碰标注文件和素材）")
def clean():
    import shutil
    for rel in ("data/cache", "data/traces", "tools/__pycache__", "__pycache__"):
        shutil.rmtree(ROOT / rel, ignore_errors=True)
    print("已清理")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        print("可用命令：")
        for name, (_, help_text) in TASKS.items():
            print(f"  {name:<8} {help_text}")
        return 0
    name = argv[0]
    if name not in TASKS:
        print(f"未知命令：{name}\n", file=sys.stderr)
        return 2
    return TASKS[name][0]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

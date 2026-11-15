# Windows 没装 make 的话，直接 `python tasks.py <命令>`，等价。
# 只是给习惯 make 的人一层薄封装，逻辑全在 tasks.py 里。

PY ?= python
VENV ?= .venv
BIN := $(VENV)/Scripts

.DEFAULT_GOAL := help
.PHONY: help env parse lint-data check eval eval-fast clean

help:  ## 列出所有命令
	@echo "  parse       解析命题组 txt 脚本 -> data/queries/"
	@echo "  lint-data   校验 jsonl 是否符合 docs/02 契约"
	@echo "  check       提交前跑这个"
	@echo "  eval        评测（待实现）"
	@echo "  env         建虚拟环境并装依赖"
	@echo "  clean       清临时产物"
	@echo ""
	@echo "  等价用法：python tasks.py lint"

env:  ## 建虚拟环境并装依赖
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install -U pip
	$(BIN)/pip install -r requirements.txt

parse:  ## 解析命题组脚本
	@$(PY) tasks.py parse

lint-data:  ## 校验数据契约
	@$(PY) tasks.py lint

check:  ## 提交前检查
	@$(PY) tasks.py check

eval:  ## 全量评测
	@$(PY) tasks.py eval

eval-fast:  ## 抽 50 条快速回归
	@$(PY) tasks.py eval --fast

clean:  ## 清临时产物
	@$(PY) tasks.py clean

.PHONY: help install dev test lint fmt demo serve viz doctor clean build check

PY ?= python3

help:
	@echo "neural-kb"
	@echo "  make install   安装（可编辑模式）"
	@echo "  make dev       安装 + 开发依赖（ruff / mypy / build）"
	@echo "  make test      跑单元测试"
	@echo "  make check     test + doctor（提交前跑这个）"
	@echo "  make demo      建示例库并起可视化 http://127.0.0.1:8765"
	@echo "  make viz       导出单文件可视化 brain.html"
	@echo "  make lint      ruff + mypy"
	@echo "  make fmt       ruff format"
	@echo "  make build     打 wheel / sdist"
	@echo "  make clean     清缓存与临时产物"

install:
	$(PY) -m pip install -e .

dev:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m unittest discover -s tests -v

doctor:
	$(PY) -m nkb doctor

check: test doctor

demo:
	$(PY) -m nkb init --demo --force
	$(PY) -m nkb serve

viz:
	$(PY) -m nkb viz --out brain.html

lint:
	ruff check .
	mypy nkb

fmt:
	ruff format .

build:
	$(PY) -m build

clean:
	rm -rf build dist *.egg-info .mypy_cache .ruff_cache .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -f brain.html demo-quickstart.json docs-demo.json docs-demo.html

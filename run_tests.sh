#!/bin/bash

uv run python -m pytest -v --cov=gitzconsul tests/
uv run ruff check gitzconsul tests
uv run ruff format --check gitzconsul tests

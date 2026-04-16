# AGENTS.md

## Before every commit

Always run these commands and fix any issues before committing:

```bash
uv run ruff check gitzconsul tests
uv run ruff format gitzconsul tests
uv run python -m pytest -v --cov=gitzconsul tests/
```

## Project conventions

- Package manager: uv (not poetry)
- Linting/formatting: ruff (not flake8/pylint)
- Testing: pytest with pytest-cov
- Build backend: hatchling
- Python: >= 3.10
- Line length: 120
- Use trailing commas in multi-symbol imports to force one-per-line wrapping

# Contributing to InvestPilot

Thank you for your interest! This guide covers setup, testing, linting, and the PR process.

## Development Setup

### Prerequisites

- Python 3.9+ (3.12 recommended)
- Node.js 18+ (for the web dashboard)
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Install

```bash
# Clone and enter the repo
git clone https://github.com/shendifei87/investpilot.git
cd investpilot

# Python backend
uv sync --dev

# Web dashboard
cd web && npm install
```

### Environment

```bash
cp .env.example .env
# Edit .env and add your TUSHARE_TOKEN
```

## Running Tests

```bash
# Python tests
uv run pytest tests/ -v

# Python tests with coverage
uv run pytest tests/ -v --cov --cov-report=term-missing

# Web tests
cd web && npm test
```

## Linting & Formatting

```bash
# Ruff (lint)
uv run ruff check .

# Ruff (format check)
uv run ruff format --check .

# MyPy (type checking)
uv run mypy src/ config/

# TypeScript
cd web && npx tsc --noEmit
```

## Pull Request Process

1. Fork the repository.
2. Create a feature branch from `main`.
3. Make your changes with tests.
4. Ensure `ruff check`, `mypy`, and `pytest` all pass.
5. Open a PR against `main` with a clear description of the change.

## Code Style

- Python: Ruff defaults (line-length 100, target py39).
- TypeScript: Strict mode, no `any` types in new code.
- Commit messages: imperative mood, lowercase.

## Reporting Issues

Use the GitHub issue templates (bug report or feature request).

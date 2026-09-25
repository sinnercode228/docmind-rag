.PHONY: setup api web test lint demo-kb up

setup:            ## install backend (.venv) and frontend deps
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install

api:              ## run the API on :8000 (SQLite + in-memory vectors + Fake LLM)
	cd backend && DOCMIND_BOOTSTRAP_API_KEY=dm_local_dev_key .venv/bin/uvicorn docmind.main:create_app --factory --reload

web:              ## run the UI on :5173 against the local API
	cd frontend && VITE_DOCMIND_MODE=api VITE_DOCMIND_API_KEY=dm_local_dev_key npm run dev

test:             ## all tests
	cd backend && .venv/bin/pytest
	cd frontend && npm test

lint:             ## linters + type checkers
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src
	cd frontend && npm run lint && npm run typecheck

demo-kb:          ## re-export sample-kb/*.md into the web demo bundle
	backend/.venv/bin/docmind export-demo-kb sample-kb frontend/src/demo/kb.json

up:               ## full stack in Docker (pgvector, API, UI)
	docker compose up --build

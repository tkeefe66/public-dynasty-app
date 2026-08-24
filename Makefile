.PHONY: dev-api dev-web test test-api test-web build clean

# PYTHONPATH is forced ahead of `cd`+bare `uvicorn` resolution: `uvicorn` on a
# dev machine's PATH is typically a global/homebrew install, not this repo's
# venv, and it can carry its own stale editable `sleeper-dynasty` install
# pointing at a DIFFERENT checkout's src (e.g. the main repo's, from inside a
# worktree) — this silently served worktree-going-in-biggest-needs's Task 7
# real-browser check under the main checkout's older code until caught. This
# mirrors the fix api/pyproject.toml's `[tool.pytest.ini_options]` already
# applies for `pytest`, extended to the dev server, which has no such hook.
dev-api:
	PYTHONPATH="$(CURDIR)/src:$$PYTHONPATH" uvicorn app.main:app --reload --port 8000 --app-dir api

dev-web:
	cd web && npm run dev

test: test-api test-web

test-api:
	cd api && pytest -v

test-web:
	cd web && npm run test -- --run

build:
	docker build -f api/Dockerfile -t trade-grader-api:local .
	docker build -f web/Dockerfile -t trade-grader-web:local .

clean:
	rm -rf api/.pytest_cache web/.next web/node_modules

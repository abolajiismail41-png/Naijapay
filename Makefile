.PHONY: setup up down logs test lint typecheck arch migrate revision check-migrations seed web-test web-typecheck
setup: ; test -f .env || cp .env.example .env
up: setup ; docker compose up --build -d
down: ; docker compose down
logs: ; docker compose logs -f api worker
test: ; docker compose run --rm --no-deps api pytest -q
lint: ; docker compose run --rm --no-deps api ruff check .
typecheck: ; docker compose run --rm --no-deps api mypy app
check-migrations: ; docker compose run --rm api alembic check
arch: ; docker compose run --rm --no-deps api lint-imports
migrate: ; docker compose run --rm api alembic upgrade head
revision: ; docker compose run --rm api alembic revision --autogenerate -m "$(m)"
seed: ; docker compose run --rm api python -m app.cli seed-dev
web-typecheck: ; docker compose run --rm --no-deps frontend npm run typecheck
web-test: ; docker compose run --rm --no-deps frontend npm test

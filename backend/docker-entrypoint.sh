#!/bin/sh
# Container start: migrate, optionally seed, then serve.
#   RUN_MIGRATIONS=0       skip `alembic upgrade head` (when several replicas share one database)
#   SEED_ON_START=reference  add reference data (courses, authorities, syllabus, info pages) if missing
#   SEED_ON_START=demo       reference data + the clearly-labelled DEMO colleges, questions and accounts
#                            (either value also imports data/question_bank.json, skipping questions already present)
#   PORT                   port to listen on (free hosts such as Render set this)
set -e

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  alembic upgrade head
fi

case "${SEED_ON_START:-}" in
  reference) python -m app.seed --no-demo --if-empty ;;
  demo) python -m app.seed --if-empty ;;
  "") ;;
  *) echo "Unknown SEED_ON_START=${SEED_ON_START} (use reference or demo)" >&2; exit 1 ;;
esac

# Ship-with question bank (AI-written, independently checked). Already-present questions are skipped.
if [ -n "${SEED_ON_START:-}" ] && [ -f data/question_bank.json ]; then
  python -m app.maintenance import-questions --file data/question_bank.json
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${WEB_CONCURRENCY:-1}" \
  --proxy-headers --forwarded-allow-ips='*'

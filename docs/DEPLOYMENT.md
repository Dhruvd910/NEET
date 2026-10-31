# Deployment

A single-host Docker deployment: **Caddy** (automatic HTTPS) → **Next.js** web app → **FastAPI** API →
**PostgreSQL** and **Redis**. Files are in `deploy/`. Only Caddy is exposed to the internet. The web app
proxies `/api` to the API, so the session cookie stays first-party.

> These files have not been run against a live server yet. Docker was not available on the build
> machine. The API and web app themselves are tested (`pytest`, Playwright, `next build`).

## 1. Prepare the host

- A Linux VM with Docker Engine and the Compose plugin, ports 80/443 open, and a DNS `A` record for your domain.
- Prefer a region in India (data residency is not mandatory under the DPDP Act, but it simplifies the
  privacy notice and expectations of families).

## 2. Configure

```bash
cp deploy/.env.example deploy/.env                      # DOMAIN, POSTGRES_PASSWORD
cp backend/.env.example backend/.env.production         # then edit:
```

Required in `backend/.env.production`. The API **refuses to start** with `ENV=production` if any are missing:

| Variable | Value |
|---|---|
| `ENV` | `production` |
| `JWT_SECRET` | 48+ random characters (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) |
| `COOKIE_SECURE` | `true` |
| `EMAIL_BACKEND` | `smtp`, plus `SMTP_*` and `EMAIL_FROM` (guardian-consent emails) |
| `PUBLIC_APP_URL` | `https://<your domain>` |
| `CORS_ORIGINS` | `["https://<your domain>"]` |

`DATABASE_URL`, `REDIS_URL` and `TRUST_PROXY_HEADERS` are set by the compose file. Optional:
`ANTHROPIC_API_KEY` (assistant), `VOYAGE_API_KEY` (semantic search), `PLACES_PROVIDER=overpass` with a
real contact in `PLACES_USER_AGENT`, and `LOG_JSON=true`.

## 3. Start

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env exec api python -m app.seed --no-demo
```

`--no-demo` loads reference data only (courses, counselling authorities, data sources, info pages
pending review). **Never seed demo data in production.** Create the first admin account:

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env exec api python -c "
from app.db import SessionLocal; from app.models import User, Role; from app.security import hash_password
import getpass; e=input('admin email: '); p=getpass.getpass()
with SessionLocal() as db: db.add(User(email=e, password_hash=hash_password(p), role=Role.admin)); db.commit()"
```

Then sign in, open **/admin → Overview** and work through the go-live readiness list.
[DATA_LOADING.md](DATA_LOADING.md) covers loading real data.

## 4. Scheduled jobs (cron on the host)

```cron
# Delete minors' accounts without guardian consent after the retention window (DPDP)
30 1 * * * cd /srv/neet && docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env exec -T api python -m app.maintenance purge-unconsented
# Keep a buffer of fresh practice questions (students also trigger top-ups automatically; this smooths peaks)
0 3 * * * cd /srv/neet && docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env exec -T api python -m app.maintenance grow-question-bank --per-section 50
# Nightly backup
15 2 * * * cd /srv/neet && sh deploy/backup.sh >> /var/log/neet-backup.log 2>&1
```

## 5. Backups and restore

`deploy/backup.sh` writes a `pg_dump` (custom format) and a tarball of stored source files to `BACKUP_DIR`,
keeping 14 days. Copy that folder off the host to encrypted object storage.

Restore drill (do it monthly, on a scratch host):

```bash
docker compose ... exec -T db pg_restore -U neet -d neet --clean --if-exists < db-<stamp>.dump
docker compose ... exec -T api tar -C /data -xzf - < storage-<stamp>.tar.gz
```

Deleted accounts remain in backups until those backups age out (14 days by default). Say so in the privacy notice.

## 6. Monitoring

- **Health:** `GET /api/health` (process up) and `GET /api/ready` (database reachable; 503 otherwise).
  The compose health check uses `/api/ready`. Point an external uptime monitor at `https://<domain>/api/ready`.
- **Logs:** with `LOG_JSON=true` every request is one JSON line with `request_id`, method, path, status and
  duration. Request bodies and query strings are never logged, because they can contain personal data.
  Ship the logs with your host's log driver and alert on 5xx rate and on `rate limiter: Redis unavailable`.
- **Data freshness:** `/admin → Overview` shows unverified or conflicting records and documents waiting for OCR.

## 7. Scaling notes

- Rate limits are shared through Redis, so you can run several API containers. Set `RUN_MIGRATIONS=0` on all
  but one, or run `alembic upgrade head` as a release step.
- Semantic search keeps vectors in a JSON column and ranks in Python. That is fine up to tens of thousands of
  passages. Beyond that, move them to a `pgvector` column with an HNSW index; only
  `backend/app/services/retrieval.py` changes.
- The web image bakes in the API address at build time (`API_ORIGIN` build arg).
- Maps load tiles from `tile.openstreetmap.org` by default. That server is for light use only. For production
  traffic, set `NEXT_PUBLIC_MAP_TILE_URL` and `NEXT_PUBLIC_MAP_ATTRIBUTION` (build-time) to a tile provider you
  have a plan with.

## Security checklist

- [ ] HTTPS only (Caddy), HSTS header on, `COOKIE_SECURE=true`
- [ ] Session cookie is httpOnly + SameSite=Lax; unsafe requests need the `X-CSRF-Token` header (signed double-submit)
- [ ] Admin accounts use long unique passwords; keep the number of admins small (every action is in the audit log)
- [ ] Postgres is not exposed outside the Docker network
- [ ] Secrets only in `deploy/.env` and `backend/.env.production` (both git-ignored), readable by root only
- [ ] Backups encrypted and restore-tested
- [ ] `DPDP_REVIEW_REFERENCE` set after the legal review ([DPDP_READINESS.md](DPDP_READINESS.md))

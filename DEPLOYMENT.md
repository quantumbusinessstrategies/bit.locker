# quantumgains Deployment Notes

Goal: run the dashboard on a domain while keeping it owner-only.

## Fastest Safe Hosting Shape

1. Push this project to a private GitHub repository.
2. Deploy the Dockerfile to a Python-capable host such as Render, Railway, Fly.io, a VPS, or another container host.
3. Set a persistent disk/volume for `data/` so the queue database survives deploys.
4. Set `QUANTUMGAINS_USERS_JSON` in the host environment for username/password access.
5. Point your domain or subdomain to the host.

For the strongest always-on local/VPS setup, use `docker-compose.yml` because the web app and worker share one persistent `quantumgains_data` volume.

## Required Environment

```text
DATABASE_PATH=data/gain_entity.sqlite3
PYTHONPATH=src
QUANTUMGAINS_USERS_JSON={"owner":{"password_hash":"pbkdf2_sha256$...","role":"owner"}}
OPENAI_API_KEY=optional-for-LLM-scoring
OPENAI_MODEL=gpt-4o-mini
```

Generate hashed users locally:

```bash
python scripts/create_access_user.py owner
python scripts/create_access_user.py family
```

Merge the generated JSON objects into one `QUANTUMGAINS_USERS_JSON` value. Passwords are not stored in plaintext. The older
`QUANTUMGAINS_ACCESS_PIN` gate still works as a local fallback, but username/password hashes are the better online setup.

## Background Autonomy Worker

Run this as a separate worker/cron job when the host supports background processes:

```bash
python scripts/safe_autonomy_loop.py --log data/safe_autonomy_loop.log --duration-seconds 1800 --limit 320 --inspect-limit 30
```

The loop performs discovery, queue prep, safe packet preparation, low-risk final-submit consent staging, and guarded browser execution. It does not perform payment, purchase, legal, tax, identity, login bypass, wallet signing, or sensitive final actions.

On a VPS:

```bash
docker compose up -d --build
```

For Render, `render.yaml` starts the web dashboard with a persistent disk. Use a separate worker only if it can access the same database path or you move the queue database to a shared managed database layer later.

## Safety Boundary

Owner-only access does not remove approval gates. The app may auto-run low-risk work, but it must pause on:

- platform login / captcha / human verification
- legal terms or attestations
- tax, EIN, SSN, W-9, 1099
- identity/KYC
- payment authorization or purchase
- wallet signing or seed/private key use

## Domain Pattern

Use a private subdomain such as:

```text
vault.yourdomain.com
gains.yourdomain.com
```

Keep the dashboard behind the owner access PIN or an external gate such as Cloudflare Access.

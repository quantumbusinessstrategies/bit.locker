# quantumgains Deployment Notes

Goal: run the dashboard on a domain while keeping it owner-only.

## Azure VM + Porkbun Quick Start (current plan)

This repo already has everything needed: `Dockerfile`, `docker-compose.yml` (web + background
worker + Caddy for automatic HTTPS), and `Caddyfile` pointed at `qubit.locker`. You need to do the
parts that require your own accounts — nobody else can click through your Azure/Porkbun dashboards
for you. Everything below is copy-paste once you're SSH'd into the VM.

**1. Claim the Azure credit and create a VM (you do this in the browser)**
- Go to https://education.github.com/pack, find Microsoft Azure, click "Get access."
- In the Azure portal: Create a resource → Ubuntu Server 24.04 LTS → size `B2s` (2 vCPU/4GB — plenty
  for this app) → create an SSH key pair when prompted (download the `.pem`/download the key) →
  open ports 22, 80, 443 in the Networking step → Create.
- Once it's running, copy the VM's **public IP address** — you'll need it for steps 2 and 4.

**2. Point Porkbun at the VM (you do this in the browser)**
- Porkbun → qubit.locker → DNS records → add an **A record**: host `@`, answer = the VM's public IP.
- Add a second A record: host `www`, same IP (Caddyfile already covers `www.qubit.locker` too).
- DNS can take a few minutes to a few hours to propagate — this can happen while you do step 3.

**3. SSH in and install Docker**

```bash
ssh -i /path/to/your-key.pem azureuser@<VM_PUBLIC_IP>
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
```

**4. Pull the repo and set real secrets**

```bash
git clone https://github.com/quantumbusinessstrategies/bit.locker.git
cd bit.locker
cp .env.example .env
nano .env   # fill in OPENAI_API_KEY, QUANTUMGAINS_ACCESS_PIN_HASH, BRAVE_SEARCH_API_KEY
```

Never put real secrets in `.env.example` or commit `.env` — it's already gitignored.

**5. Launch it**

```bash
docker compose up -d --build
docker compose logs -f caddy   # watch for "certificate obtained successfully"
```

Once Caddy reports the certificate is issued and DNS has propagated, `https://qubit.locker` serves
the live dashboard. `docker compose ps` shows all three services (`web`, `safe-worker`, `caddy`)
running with `restart: unless-stopped`, so a VM reboot brings everything back on its own.

**6. Updating later**

```bash
cd bit.locker && git pull && docker compose up -d --build
```

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

## Multiple People, Short Personal Codes (testers/family)

For a few trusted people who just need a short code (not a full username+password), set
`QUANTUMGAINS_ACCESS_PINS_JSON` instead. Each person gets their own code, their own identity, and
their own isolated vault/settings/notes/reminders/scan queries - nobody sees or overwrites anyone
else's personal info. Generate it with:

```bash
python scripts/create_access_pins.py --person owner:3846:owner --person tester1:0420 --person tester2:6969 --person tester3:6666
```

The first `:role` segment matters for exactly one person: only `role: owner` can change paid-mode /
spend-cap settings, so make sure exactly one entry uses `owner` and the rest are left as `member`.

Discovered opportunities and the claim queue are still shared across everyone (one scan feeds
everyone, so the app doesn't burn 4x the API budget) - but personal data isn't. Whoever clicks
"Approve" on an item claims it: that item's forms get filled using *their* vault, not anyone else's.

**Important safety boundary:** the always-on background loop (`safe_autonomy_loop.py`, e.g. on Fly)
only ever auto-submits claims for the primary `owner` identity. Once a teammate approves an item, it's
stamped as theirs and the unattended loop leaves it alone - it will only advance/submit once that
person manually approves it themselves, in-app, while they're actually present. This is deliberate:
nobody's personal/payment info gets used by an automated process without them personally clicking
through it first.

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

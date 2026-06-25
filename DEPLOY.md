# Production Deployment

Deploy the Book Store bot to a Linux VPS with Docker. The bot uses **long
polling**, so you need **no domain, no open inbound ports, no TLS** — only
outbound HTTPS to Telegram.

## 1. Server

- Ubuntu 22.04 / 24.04 LTS, **2 GB RAM**, 1–2 vCPU, 25 GB SSD
- A non-root sudo user

Install Docker Engine + Compose plugin:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # then log out/in
```

Firewall — allow only SSH:

```bash
sudo ufw allow OpenSSH
sudo ufw enable
```

## 2. Get the code

```bash
sudo mkdir -p /opt/books_store_bot && sudo chown "$USER" /opt/books_store_bot
# copy the project here (git clone, scp, or rsync)
cd /opt/books_store_bot
```

## 3. Configure secrets

```bash
cp .env.example .env
nano .env
```

Set, at minimum:
- `BOT_TOKEN` — from @BotFather
- `DB_PASSWORD` — a strong random value (`openssl rand -hex 24`)
- `ADMIN_IDS` — your Telegram chat id(s), comma-separated

```bash
chmod 600 .env          # protect the token
```

## 4. Launch

```bash
docker compose up -d --build         # builds image, starts db + bot
docker compose ps                    # both should be healthy/up
docker compose logs -f bot           # expect "Run polling for bot @..."
```

## 5. Load store data

```bash
# real data from the Google Sheet:
docker compose run --rm seed python -m scripts.import_sheet --reset
# or random test data:
docker compose run --rm seed python -m scripts.seed 20 --reset
```

## 6. Backups (daily)

```bash
crontab -e
# add:
0 3 * * * cd /opt/books_store_bot && ./scripts/backup.sh >> backups/backup.log 2>&1
```

Restore from a dump:

```bash
gunzip -c backups/books_store_YYYYMMDD_HHMMSS.sql.gz \
  | docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME"
```

## Operations

| Task | Command |
|---|---|
| Status / health | `docker compose ps` |
| Live logs | `docker compose logs -f bot` |
| Restart bot | `docker compose restart bot` |
| Update after code change | `docker compose up -d --build bot` |
| Stop everything | `docker compose down` |
| DB shell | `docker compose exec db psql -U "$DB_USER" -d "$DB_NAME"` |

## What's already production-hardened

- **Auto-restart** (`restart: unless-stopped`) — survives crashes and reboots
- **Health check** — container is marked unhealthy if the bot's event loop stalls (heartbeat), so Docker restarts it
- **Graceful shutdown** — closes the bot session and DB pool on SIGTERM
- **DB startup retry** — bot waits for Postgres on a cold boot
- **Postgres not internet-exposed** — port bound to `127.0.0.1` only
- **Non-root container** + `tini` init for correct signal handling
- **Log rotation** — 10 MB × 3 files per service (no disk-fill)
- **Memory limits** — db 512 MB, bot 384 MB
- **Self-cleaning broadcasts** — users who block the bot are auto-deactivated

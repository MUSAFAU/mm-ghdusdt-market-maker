# MM Trading Volume Market Maker (GHDUSDT)

This repository contains a market-making bot, OpenAPI spec with HMAC auth, a mock exchange, Swagger UI, and deployment CI.

## What's included
- `openapi/openapi_with_signing.yaml` — OpenAPI spec with HMAC signing docs
- `bot/mm_bot.py` — Python asyncio market-making bot (example)
- `bot/.env.example` — Example environment variables
- `mock-exchange/mock_server.py` — Lightweight aiohttp mock exchange with HMAC validation
- `swagger-ui/index.html` — Swagger UI page (uses CDN assets)
- `.github/workflows/deploy-swagger.yml` — GitHub Actions workflow to deploy Swagger UI to Pages
- `docker-compose.yml` and simple Dockerfiles to run locally (bot + mock + swagger static server)

## Quick start (local)
1. Unzip the project.
2. Start the mock exchange:
   ```bash
   cd mock-exchange
   python3 mock_server.py
   ```
3. Configure `bot/.env` from `.env.example`.
4. Run the bot:
   ```bash
   cd bot
   pip install -r requirements.txt
   python mm_bot.py
   ```
5. View Swagger UI:
   ```bash
   cd swagger-ui
   python3 -m http.server 8080
   ```
   Open http://localhost:8080

## GitHub Pages
Push to GitHub and the included workflow will deploy `swagger-ui/` to GitHub Pages on `main` branch pushes.


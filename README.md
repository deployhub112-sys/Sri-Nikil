# Sri Nikil Trading Dashboard

Inventory, billing, pricing, customer, sales, report, settings, and login activity dashboard for Sri Nikil Trading.

## Setup

```bash
npm install
pip install -r server/requirements.txt
```

Copy `server/.env.example` to `server/.env.development` and fill the Supabase
PostgreSQL connection string (`SUPABASE_DB_URL`) and SMTP values - see
`SUPABASE_SETUP.md`. Existing MongoDB Atlas data can be migrated with
`server/migrate_mongo_to_postgres.py` (read-only on MongoDB).

## Run

```bash
npm run dev
```

Client runs with Vite and the FastAPI Supabase (PostgreSQL) API runs on `PORT` from the server env file (`python server/run.py`).

## Build

```bash
npm run build
```

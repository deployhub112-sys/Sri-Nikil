# Supabase (PostgreSQL) Setup

The backend talks directly to PostgreSQL using asyncpg. The frontend never
touches the database - it only calls `/api/*`, so no client changes are needed.

## 1. Create the Supabase project

1. Create a project at https://supabase.com.
2. Open **Dashboard -> Connect -> Connection string -> URI**.
3. From a local/dev machine use the **Session pooler** URL (port `6543`).
   The direct URL (port `5432`) uses IPv6 and usually fails outside
   Supabase's network. From a server with IPv6 support either URL works.

## 2. Fill in the environment

Paste it in `server/.env.development`:

```env
SUPABASE_DB_URL=postgresql://postgres.YOUR-REF:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres

# Optional / reserved (placeholders, not required to run the API)
SUPABASE_URL=https://YOUR-REF.supabase.co
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=

DEFAULT_ADMIN_PASSWORD=admin12345
PORT=5000
```

`DATABASE_URL`, `POSTGRES_URL`, and `SUPABASE_POSTGRES_URL` are accepted as
fallback names for `SUPABASE_DB_URL`.

Any other PostgreSQL connection string works the same way (useful for local
testing), e.g. `postgresql://postgres:postgres@127.0.0.1:5433/sri_nikil_test`.

## 3. Start

```bash
npm run dev
```

On startup the backend automatically:

- creates every table/index from `server/app/schema.sql` (idempotent)
- seeds default shop settings and the default `admin` account (with
  `DEFAULT_ADMIN_NAME` / `DEFAULT_ADMIN_EMAIL` from the env file)
- mirrors the admin into **Supabase Authentication** (Dashboard ->
  Authentication -> Users, email confirmed) and into the `profiles` table,
  linked by the same UUID - both are upserted, so restarts never create
  duplicates
- syncs id counters, backfills bill expiry dates, purges expired bills

The admin is visible in three places, all kept in sync:

| Where | Table / section | Contents |
|---|---|---|
| Table Editor | `accounts` | `username=admin`, `name`, `email`, `role=Admin`, scrypt `pass` |
| Table Editor | `profiles` | same name/email/role + `id` = Supabase Auth UUID |
| Authentication | Users | `surendharkavin01@gmail.com` (confirmed), metadata `{username, name, role}` |

App logins still authenticate against the `accounts` table (unchanged
frontend). The Supabase Auth user mirrors the same password
(`DEFAULT_ADMIN_PASSWORD`) for dashboard access; changing it in Supabase
Auth does not change the app password.

Change the admin password from the Settings page after first login.

## 4. Migrate existing MongoDB Atlas data

The migration script is **read-only on MongoDB** - it never writes to or
deletes anything in Atlas.

```bash
pip install -r server/requirements-migration.txt
python server/migrate_mongo_to_postgres.py --verify-only   # compare row counts
python server/migrate_mongo_to_postgres.py                 # migrate + verify
```

- The Atlas connection string lives in `server/.env.migration` (gitignored).
- Re-runs are safe: rows are upserted by `id`.
- Use `--replace` to truncate the target tables first (fresh database).
- Use `--collections products,bills` to migrate a subset.

Only delete/retire the Atlas database **after** `--verify-only` shows matching
row counts for every collection.

## API health check

```bash
curl http://localhost:5000/            # {"ok":true,"service":"Sri Nikil FastAPI Supabase API",...}
curl http://localhost:5000/api-docs    # Swagger UI (29 paths)
```

## Automatic 4-year bill retention

Every bill is deleted **exactly 4 calendar years after its `created_at`**
(Oct 19 2026 -> Oct 19 2030; Feb 29 rolls to Feb 28). How it works:

- `expires_at = created_at + 4 years` is set when the bill is created and
  recomputed for all bills on every backend startup (legacy rows included).
- A backend scheduler deletes expired bills every
  `BILL_PURGE_INTERVAL_HOURS` (default 6h), and also on startup and before
  the bills list is served - no manual action or Supabase Cron needed.
- Before a row is deleted, any bill attachments in Supabase Storage
  (`BILL_STORAGE_BUCKET`, default `bills`) are removed via the service role
  key. Bills currently have no stored files, so this is a no-op until files
  are added.
- Each purge is audited in the `deletion_log` table (bill id, bill number,
  created/expiry timestamps, deletion time, reason `expired_retention`).
- Only `bills` rows are removed; products, customers, refills, accounts,
  settings, and shift reports are never touched by retention.
  Note: confirm the 4-year window satisfies your local legal/financial
  record-keeping rules before relying on it.

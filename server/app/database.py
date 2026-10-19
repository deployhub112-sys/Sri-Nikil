import asyncio
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

from . import config
from .constants import BILL_RETENTION_YEARS, DEFAULT_ACCOUNTS, DEFAULT_SETTINGS
from .security import hash_password

pool: asyncpg.Pool | None = None

COUNTERS = 'counters'

SCHEMA_SQL = (Path(__file__).resolve().parent / 'schema.sql').read_text(encoding='utf-8')

COUNTER_TABLES = (
    ('products', 'products'),
    ('bills', 'bills'),
    ('sales', 'sales'),
    ('customers', 'customers'),
    ('refills', 'refills'),
    ('price_history', 'price_history'),
    ('login_logs', 'login_logs'),
    ('shifts', 'shifts'),
    ('shift_reports', 'shift_reports'),
)


def _require_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError('PostgreSQL (Supabase) is not connected yet.')
    return pool


async def fetch_all(query: str, *args):
    return await _require_pool().fetch(query, *args)


async def fetch_one(query: str, *args):
    return await _require_pool().fetchrow(query, *args)


async def fetchval(query: str, *args):
    return await _require_pool().fetchval(query, *args)


async def execute(query: str, *args) -> str:
    return await _require_pool().execute(query, *args)


# ---------------------------------------------------------------------------
# value helpers (mirror the JavaScript coercion rules)
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return f"{value.strftime('%Y-%m-%dT%H:%M:%S')}.{value.microsecond // 1000:03d}Z"


def serialize(doc: Any):
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize(item) for item in doc]
    if isinstance(doc, tuple):
        return [serialize(item) for item in doc]
    if isinstance(doc, dict):
        return {key: serialize(value) for key, value in doc.items() if key not in ('_id', 'extra')}
    if isinstance(doc, datetime):
        return to_iso(doc)
    return doc


def serialize_account(account: dict):
    rest = serialize(account)
    if rest is None:
        return None
    rest.pop('pass', None)
    rest['pass'] = ''
    return rest


def serialize_many(rows):
    return [serialize(row) for row in rows or []]


def to_number(value, fallback: float = 0):
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return fallback
    else:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return fallback

    if math.isnan(number) or math.isinf(number):
        return fallback
    return int(number) if number.is_integer() else number


def non_negative_number(value, fallback: float = 0):
    return max(0, to_number(value, fallback))


def as_valid_date(value, fallback: datetime | None = None) -> datetime:
    fallback = fallback or utcnow()
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        try:
            return _aware(datetime.fromisoformat(text))
        except ValueError:
            return fallback
    try:
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        return _aware(parsed)
    except (TypeError, ValueError, OverflowError, OSError):
        return fallback


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def add_years(value: datetime, years: int) -> datetime:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, month=2, day=28)


def get_bill_expiry_date(bill_date) -> datetime:
    return add_years(as_valid_date(bill_date), BILL_RETENTION_YEARS)


def normalize_bill_items(raw_items):
    if isinstance(raw_items, list):
        return raw_items
    if isinstance(raw_items, str):
        try:
            parsed = json.loads(raw_items)
            return parsed if isinstance(parsed, list) else []
        except ValueError:
            return []
    return []


def normalize_product(product: dict):
    if not product:
        return product

    stock = non_negative_number(product.get('stock'))
    sold = non_negative_number(product.get('sold'))
    opening_stock = max(non_negative_number(product.get('opening_stock')), stock)

    updated = dict(product)
    updated['price'] = non_negative_number(product.get('price'))
    updated['stock'] = stock
    updated['sold'] = sold
    updated['opening_stock'] = opening_stock
    return updated


def serialize_product(product: dict):
    return serialize(normalize_product(product))


def serialize_products(products):
    return [serialize_product(product) for product in products or []]


def get_next_bill_no(bills) -> str:
    max_seq = 999
    for bill in bills or []:
        match = re.search(r'SNT-(\d+)', str(bill.get('billNo') or bill.get('bill_no') or ''), re.IGNORECASE)
        if match:
            max_seq = max(max_seq, int(match.group(1)))
    return f'SNT-{max_seq + 1:04d}'


# ---------------------------------------------------------------------------
# row -> API document mappers (spread stored extra columns first, like
# the old Node/Express payloads did with `...req.body`)
# ---------------------------------------------------------------------------

def map_product(row) -> dict:
    if row is None:
        return None
    doc = dict(row['extra'] or {})
    doc.update({
        'id': row['id'],
        'code': row['code'],
        'name': row['name'],
        'cat': row['cat'],
        'unit': row['unit'],
        'price': row['price'],
        'stock': row['stock'],
        'opening_stock': row['opening_stock'],
        'sold': row['sold'],
        'image': row['image'],
        'created_at': row['created_at'],
    })
    return doc


def map_bill(row) -> dict:
    if row is None:
        return None
    doc = dict(row['extra'] or {})
    doc.update({
        'id': row['id'],
        'billNo': row['bill_no'],
        'bill_no': row['bill_no'],
        'customer': row['customer'],
        'phone': row['phone'],
        'payment': row['payment'],
        'items': row['items'],
        'subtotal': row['subtotal'],
        'cgst': row['cgst'],
        'sgst': row['sgst'],
        'grand': row['grand'],
        'by': row['by'],
        'by_user': row['by_user'],
        'date': row['date'],
        'expires_at': row['expires_at'],
        'created_at': row['created_at'],
    })
    return doc


def map_customer(row) -> dict:
    if row is None:
        return None
    doc = dict(row['extra'] or {})
    doc.update({
        'id': row['id'],
        'name': row['name'],
        'phone': row['phone'],
        'firstVisit': row['first_visit'],
        'first_visit': row['first_visit'],
        'lastVisit': row['last_visit'],
        'last_visit': row['last_visit'],
        'visits': row['visits'],
        'total': row['total'],
    })
    return doc


def map_refill(row) -> dict:
    if row is None:
        return None
    doc = dict(row['extra'] or {})
    doc.update({
        'id': row['id'],
        'date': row['date'],
        'productId': row['product_id'],
        'product_id': row['product_id'],
        'product': row['product'],
        'qty': row['qty'],
        'by': row['by'],
        'by_user': row['by'],
        'created_at': row['created_at'],
    })
    return doc


def map_price_history(row) -> dict:
    if row is None:
        return None
    doc = dict(row['extra'] or {})
    doc.update({
        'id': row['id'],
        'date': row['date'],
        'productId': row['product_id'],
        'product_id': row['product_id'],
        'product': row['product'],
        'old': row['old_price'],
        'old_price': row['old_price'],
        'new': row['new_price'],
        'new_price': row['new_price'],
        'by': row['by'],
        'by_user': row['by'],
        'created_at': row['created_at'],
    })
    return doc


def map_account(row) -> dict:
    if row is None:
        return None
    return {
        'user': row['username'],
        'username': row['username'],
        'name': row['name'],
        'email': row['email'],
        'role': row['role'],
        'created_at': row['created_at'],
        'pass': '',
    }


def map_login_log(row) -> dict:
    if row is None:
        return None
    doc = dict(row['extra'] or {})
    doc.update({
        'id': row['id'],
        'user': row['username'],
        'user_name': row['user_name'],
        'role': row['role'],
        'loginTime': row['login_time'],
        'login_time': row['login_time'],
        'logoutTime': row['logout_time'],
        'logout_time': row['logout_time'],
        'shiftSessionId': row['shift_session_id'],
        'shift_session_id': row['shift_session_id'],
        'status': row['status'],
        'created_at': row['created_at'],
    })
    return doc


def map_shift(row) -> dict:
    if row is None:
        return None
    doc = dict(row['extra'] or {})
    doc.update({
        'id': row['id'],
        'user': row['username'],
        'username': row['username'],
        'role': row['role'],
        'shiftStart': row['shift_start'],
        'shift_start': row['shift_start'],
        'shiftEnd': row['shift_end'],
        'shift_end': row['shift_end'],
        'active': bool(row['active']),
        'recipientEmail': row['recipient_email'],
        'loginLogCleared': bool(row['login_log_cleared']),
        'created_at': row['created_at'],
    })
    return doc


def map_settings(row) -> dict:
    if row is None:
        return None
    return {
        'key': row['key'],
        'gst': row['gst'],
        'shop': row['shop'],
        'addr': row['addr'],
        'gstin': row['gstin'],
        'fssai': row['fssai'],
        'phone': row['phone'],
    }


# ---------------------------------------------------------------------------
# counters
# ---------------------------------------------------------------------------

async def next_id(name: str) -> int:
    seq = await fetchval(
        """
        INSERT INTO counters (name, seq) VALUES ($1, 1)
        ON CONFLICT (name) DO UPDATE SET seq = counters.seq + 1
        RETURNING seq
        """,
        name,
    )
    return int(seq or 0)


async def sync_counter(name: str, table_name: str):
    top = await fetchval(f'SELECT COALESCE(MAX(id), 0) FROM {table_name}')
    await execute(
        """
        INSERT INTO counters (name, seq) VALUES ($1, $2)
        ON CONFLICT (name) DO UPDATE SET seq = GREATEST(counters.seq, EXCLUDED.seq)
        """,
        name,
        to_number(top, 0),
    )
    seq = await fetchval('SELECT seq FROM counters WHERE name = $1', name)
    await _set_sequence(table_name, seq)


async def _set_sequence(table_name: str, seq):
    if int(seq or 0) <= 0:
        await execute("SELECT setval(pg_get_serial_sequence($1, 'id'), 1, false)", table_name)
    else:
        await execute("SELECT setval(pg_get_serial_sequence($1, 'id'), $2)", table_name, int(seq))


async def sync_sequence(table_name: str):
    """Advance the table's id sequence past any existing row after bulk deletes."""
    seq_name = await fetchval("SELECT pg_get_serial_sequence($1, 'id')", table_name)
    if not seq_name:
        return
    max_id = await fetchval(f'SELECT COALESCE(MAX(id), 0) FROM {table_name}')
    last = await fetchrow(f'SELECT last_value, is_called FROM {seq_name}')
    current = int(last['last_value'] or 0) if last and last['is_called'] else 0
    target = max(int(max_id or 0), current)
    if target > 0:
        await execute('SELECT setval($1::regclass, $2)', seq_name, target)
    else:
        await execute("SELECT setval($1::regclass, 1, false)", seq_name)


# ---------------------------------------------------------------------------
# maintenance helpers
# ---------------------------------------------------------------------------

async def clamp_product_inventory():
    await execute(
        """
        UPDATE products SET
            stock = GREATEST(COALESCE(stock, 0), 0),
            sold = GREATEST(COALESCE(sold, 0), 0),
            opening_stock = GREATEST(COALESCE(opening_stock, 0), GREATEST(COALESCE(stock, 0), 0), 0)
        """
    )


async def delete_expired_bills() -> int:
    """Delete bills whose 4-year retention has ended, with storage cleanup + audit log."""
    rows = await fetch_all(
        'SELECT * FROM bills WHERE expires_at IS NOT NULL AND expires_at <= $1',
        utcnow(),
    )
    if not rows:
        return 0

    deleted = 0
    for row in rows:
        bill = map_bill(row)

        storage_refs = bill_storage_refs(bill)
        if storage_refs:
            errors = await asyncio.to_thread(delete_storage_objects, storage_refs)
            for error in errors:
                print(f'Bill storage cleanup warning ({bill.get("billNo")}): {error}')

        await execute('DELETE FROM bills WHERE id = $1', bill['id'])
        await execute(
            """
            INSERT INTO deletion_log (entity, entity_id, bill_no, created_at, expires_at, deleted_at, reason, details)
            VALUES ('bill', $1, $2, $3, $4, $5, 'expired_retention', $6)
            """,
            bill['id'],
            bill.get('billNo'),
            bill.get('created_at'),
            bill.get('expires_at'),
            utcnow(),
            {'retention_years': BILL_RETENTION_YEARS, 'storage_objects': len(storage_refs)},
        )
        deleted += 1
        print(
            f'Purged expired bill {bill.get("billNo")} '
            f'(id={bill["id"]}, created={bill.get("created_at")}, expired={bill.get("expires_at")})'
        )

    if deleted:
        print(f'Bill retention purge: {deleted} expired bill(s) deleted and logged.')
    return deleted


def bill_storage_refs(bill: dict) -> list[tuple[str, str]]:
    """Collect Supabase Storage objects attached to a bill (bucket, path)."""
    extra = bill.get('extra') or {}
    default_bucket = os.environ.get('BILL_STORAGE_BUCKET') or 'bills'
    refs: list[tuple[str, str]] = []

    for key in ('file_path', 'attachment_path', 'storage_path', 'file', 'attachment'):
        value = extra.get(key)
        if isinstance(value, str) and value and not value.startswith(('http://', 'https://')):
            bucket, _, path = value.partition('/')
            refs.append((bucket or default_bucket, path or value))

    file_url = extra.get('file_url')
    if isinstance(file_url, str) and '/storage/v1/object/' in file_url:
        try:
            tail = file_url.split('/storage/v1/object/', 1)[1]
            bucket, _, path = tail.partition('/')
            refs.append((bucket, urllib.parse.unquote(path)))
        except (IndexError, ValueError):
            pass

    return refs


def delete_storage_objects(refs: list[tuple[str, str]]) -> list[str]:
    """Delete objects from Supabase Storage via the service role key. Returns warnings."""
    base = (config.supabase_url() or '').rstrip('/')
    service_key = config.supabase_service_role_key()
    if not refs:
        return []
    if not base or not service_key:
        return ['Supabase Storage credentials missing (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)']

    warnings: list[str] = []
    for bucket, path in refs:
        url = (
            f'{base}/storage/v1/object/'
            f'{urllib.parse.quote(bucket, safe="")}/{urllib.parse.quote(path, safe="/")}'
        )
        request = urllib.request.Request(
            url,
            method='DELETE',
            headers={'apikey': service_key, 'Authorization': f'Bearer {service_key}'},
        )
        try:
            with urllib.request.urlopen(request, timeout=15):
                pass
            print(f'Deleted bill attachment from storage: {bucket}/{path}')
        except urllib.error.HTTPError as error:
            if error.code != 404:  # already gone is fine
                warnings.append(f'{bucket}/{path}: HTTP {error.code}')
        except Exception as error:
            warnings.append(f'{bucket}/{path}: {error}')
    return warnings


async def ensure_bill_expiry_dates():
    """Every bill expires exactly BILL_RETENTION_YEARS calendar years after creation.

    Recomputes on startup so legacy rows (and any drift) always match the
    policy. PostgreSQL `+ interval '4 years'` rolls Feb 29 -> Feb 28 correctly.
    """
    await execute(
        """
        UPDATE bills
        SET expires_at = COALESCE(created_at, date) + make_interval(years => $1)
        WHERE COALESCE(created_at, date) IS NOT NULL
          AND expires_at IS DISTINCT FROM COALESCE(created_at, date) + make_interval(years => $1)
        """,
        BILL_RETENTION_YEARS,
    )


def admin_defaults() -> tuple[str, str, str | None]:
    """(username, name, email) for the default admin from env."""
    username = 'admin'
    name = (os.environ.get('DEFAULT_ADMIN_NAME') or 'Admin').strip() or 'Admin'
    email = (os.environ.get('DEFAULT_ADMIN_EMAIL') or '').strip() or None
    return username, name, email


def admin_password() -> str:
    admin_account = next((a for a in DEFAULT_ACCOUNTS if a['role'].lower() == 'admin'), None)
    if admin_account is None:
        return os.environ.get('DEFAULT_ADMIN_PASSWORD') or ''
    return os.environ.get(admin_account['password_env']) or admin_account['fallback_password']


async def ensure_default_accounts():
    admin_username, admin_name, admin_email = admin_defaults()

    for account in DEFAULT_ACCOUNTS:
        password = hash_password(
            os.environ.get(account['password_env']) or account['fallback_password']
        )
        is_admin = account['role'].lower() == 'admin'
        name = admin_name if is_admin else None
        email = admin_email if is_admin else None

        existing = await fetch_one(
            'SELECT * FROM accounts WHERE lower(username) = lower($1)',
            account['user'],
        )
        if existing:
            if is_admin and (not existing['name'] or not existing['email']):
                await execute(
                    'UPDATE accounts SET name = COALESCE(name, $2), email = COALESCE(email, $3) WHERE id = $1',
                    existing['id'],
                    name,
                    email,
                )
            continue

        await execute(
            "INSERT INTO accounts (username, pass, role, created_at, name, email) VALUES ($1, $2, $3, $4, $5, $6)",
            account['user'],
            password,
            account['role'],
            utcnow(),
            name,
            email,
        )


async def ensure_admin_profile():
    """Mirror the default admin into Supabase Auth and public.profiles."""
    admin_username, admin_name, _ = admin_defaults()
    row = await fetch_one('SELECT * FROM accounts WHERE lower(username) = lower($1)', admin_username)
    if not row:
        return

    name = row['name'] or admin_name
    email = row['email']
    role = row['role'] or 'Admin'

    try:
        from .supabase_auth import ensure_admin_auth_user

        auth_id = await asyncio.to_thread(
            ensure_admin_auth_user, row['username'], name, email, admin_password()
        )
    except Exception as error:
        print(f'Supabase Auth admin sync skipped: {error}')
        return

    if not auth_id:
        return

    await execute(
        """
        INSERT INTO profiles (id, username, name, email, role, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $6)
        ON CONFLICT (username) DO UPDATE SET
            id = EXCLUDED.id,
            name = EXCLUDED.name,
            email = EXCLUDED.email,
            role = EXCLUDED.role,
            updated_at = EXCLUDED.updated_at
        """,
        auth_id,
        row['username'],
        name,
        email,
        role,
        utcnow(),
    )


async def sync_shift_login_logs():
    shifts = await fetch_all(
        "SELECT * FROM shifts WHERE COALESCE(login_log_cleared, false) = false ORDER BY shift_start"
    )

    for shift_row in shifts:
        shift = map_shift(shift_row)
        if not shift.get('id'):
            continue

        logout_time = shift.get('shiftEnd') or None
        status = 'Completed' if (logout_time or shift.get('active') is False) else 'Active'
        existing_log = await fetch_one(
            'SELECT id FROM login_logs WHERE shift_session_id = $1 LIMIT 1',
            shift.get('id'),
        )

        if existing_log:
            await execute(
                """
                UPDATE login_logs SET
                    username = $2, user_name = $3, role = $4,
                    login_time = $5, logout_time = $6, status = $7
                WHERE id = $1
                """,
                existing_log['id'],
                shift.get('user'),
                shift.get('user'),
                shift.get('role') or 'Staff',
                shift.get('shiftStart'),
                logout_time,
                status,
            )
            continue

        await execute(
            """
            INSERT INTO login_logs
                (id, username, user_name, role, login_time, logout_time, shift_session_id, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            await next_id('login_logs'),
            shift.get('user'),
            shift.get('user'),
            shift.get('role') or 'Staff',
            shift.get('shiftStart'),
            logout_time,
            shift.get('id'),
            status,
            shift.get('created_at') or utcnow(),
        )

    await sync_counter('login_logs', 'login_logs')


async def find_product_by_id(product_id):
    return map_product(await fetch_one('SELECT * FROM products WHERE id = $1', to_number(product_id)))


async def restore_stock_for_items(items):
    for item in normalize_bill_items(items):
        qty = non_negative_number(item.get('qty'))
        await execute(
            """
            UPDATE products SET
                stock = GREATEST(COALESCE(stock, 0), 0) + $2,
                sold = GREATEST(GREATEST(COALESCE(sold, 0), 0) - $2, 0)
            WHERE id = $1
            """,
            to_number(item.get('id')),
            qty,
        )


# ---------------------------------------------------------------------------
# startup
# ---------------------------------------------------------------------------

async def initialize():
    for counter_name, table_name in COUNTER_TABLES:
        await sync_counter(counter_name, table_name)

    await execute(
        """
        INSERT INTO settings (key, gst, shop, addr, gstin, fssai, phone)
        VALUES ('main', $1, $2, $3, $4, $5, $6)
        ON CONFLICT (key) DO NOTHING
        """,
        DEFAULT_SETTINGS['gst'],
        DEFAULT_SETTINGS['shop'],
        DEFAULT_SETTINGS['addr'],
        DEFAULT_SETTINGS['gstin'],
        DEFAULT_SETTINGS['fssai'],
        DEFAULT_SETTINGS['phone'],
    )

    await ensure_default_accounts()
    await ensure_admin_profile()
    await ensure_bill_expiry_dates()
    await delete_expired_bills()
    await sync_shift_login_logs()


async def init_connection(conn: asyncpg.Connection):
    await conn.set_type_codec('json', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')
    await conn.set_type_codec('jsonb', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')


async def connect() -> dict:
    global pool

    dsn = config.database_url()
    if not dsn:
        print('Missing SUPABASE_DB_URL. Add your Supabase PostgreSQL connection string to server/.env.development.')
        raise SystemExit(1)

    try:
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10, command_timeout=60, init=init_connection)
        await pool.execute(SCHEMA_SQL)
        await initialize()
    except asyncpg.PostgresError as error:
        print(f'PostgreSQL connection failed: {error}')
        raise SystemExit(1)

    return {
        'database': config.database_name(),
        'port': config.port(),
    }


async def disconnect():
    if pool is not None:
        await pool.close()
        pool = None

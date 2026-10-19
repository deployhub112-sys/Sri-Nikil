"""
Read-only MongoDB -> Supabase (PostgreSQL) migration.

- Reads from MongoDB Atlas using server/.env.migration (never writes to Mongo).
- Writes to the Supabase PostgreSQL database configured via SUPABASE_DB_URL.
- Idempotent: rows are upserted by id, so re-running is safe.

Usage:
    python migrate_mongo_to_postgres.py                # migrate + verify
    python migrate_mongo_to_postgres.py --verify-only  # counts only, no writes
    python migrate_mongo_to_postgres.py --replace      # wipe target tables first
    python migrate_mongo_to_postgres.py --collections products,bills

Requires the migration extra:  pip install -r requirements-migration.txt
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import asyncpg
from dotenv import dotenv_values

from app import config
from app.database import SCHEMA_SQL, init_connection, to_iso

COLLECTIONS = (
    'products',
    'bills',
    'sales',
    'customers',
    'refills',
    'price_history',
    'login_logs',
    'shifts',
    'shift_reports',
    'accounts',
    'settings',
    'counters',
)


def mongo_env() -> tuple[str, str]:
    values = {}
    for candidate in (SERVER_DIR / '.env.migration', SERVER_DIR / '.env.development', SERVER_DIR / '.env'):
        if candidate.is_file():
            values.update({k: v for k, v in dotenv_values(candidate).items() if v})
    uri = values.get('MONGODB_URI') or values.get('MONGO_URI')
    db_name = values.get('MONGODB_DB') or values.get('MONGO_DB') or 'sri_nikil_erp'
    if not uri:
        print('Missing MONGODB_URI. Put your Atlas connection string in server/.env.migration.')
        raise SystemExit(1)
    return uri, db_name


def _dt(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _num(value, fallback=0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number.is_integer():
        return int(number)
    return number


def _text(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_iso(value)
    return str(value)


def _extra(doc: dict, known: set) -> dict:
    return {
        key: (json_safe(value))
        for key, value in doc.items()
        if key not in known and key != '_id' and value is not None
    }


def json_safe(value):
    if isinstance(value, datetime):
        return to_iso(value)
    return value


# ---------------------------------------------------------------------------
# collection -> row mappings
# ---------------------------------------------------------------------------

def map_products(doc):
    known = {'_id', 'id', 'code', 'name', 'cat', 'category', 'unit', 'price', 'stock',
             'opening_stock', 'openingStock', 'sold', 'image', 'created_at'}
    stock = _num(doc.get('stock'))
    return {
        'id': _num(doc.get('id'), 0),
        'code': doc.get('code'),
        'name': doc.get('name'),
        'cat': doc.get('cat') or doc.get('category'),
        'unit': doc.get('unit'),
        'price': _num(doc.get('price')),
        'stock': stock,
        'opening_stock': max(_num(doc.get('opening_stock', doc.get('openingStock'))), stock),
        'sold': _num(doc.get('sold')),
        'image': doc.get('image'),
        'created_at': _dt(doc.get('created_at')),
        'extra': _extra(doc, known),
    }


def map_bills(doc):
    known = {'_id', 'id', 'billNo', 'bill_no', 'customer', 'phone', 'payment', 'items',
             'subtotal', 'cgst', 'sgst', 'grand', 'by', 'by_user', 'date', 'expires_at', 'created_at'}
    bill_no = doc.get('billNo') or doc.get('bill_no')
    by_value = doc.get('by') or doc.get('by_user')
    items = doc.get('items')
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except ValueError:
            items = []
    return {
        'id': _num(doc.get('id'), 0),
        'bill_no': bill_no,
        'customer': doc.get('customer'),
        'phone': doc.get('phone'),
        'payment': doc.get('payment'),
        'items': items if isinstance(items, list) else [],
        'subtotal': _num(doc.get('subtotal')),
        'cgst': _num(doc.get('cgst')),
        'sgst': _num(doc.get('sgst')),
        'grand': _num(doc.get('grand')),
        'by': by_value,
        'by_user': by_value,
        'date': _dt(doc.get('date')),
        'expires_at': _dt(doc.get('expires_at')),
        'created_at': _dt(doc.get('created_at')),
        'extra': _extra(doc, known),
    }


def map_sales(doc):
    known = {'_id', 'id', 'date'}
    return {'id': _num(doc.get('id'), 0), 'date': _dt(doc.get('date')), 'extra': _extra(doc, known)}


def map_customers(doc):
    known = {'_id', 'id', 'name', 'phone', 'firstVisit', 'first_visit',
             'lastVisit', 'last_visit', 'visits', 'total'}
    return {
        'id': _num(doc.get('id'), 0),
        'name': doc.get('name'),
        'phone': doc.get('phone'),
        'first_visit': _dt(doc.get('firstVisit') or doc.get('first_visit')),
        'last_visit': _dt(doc.get('lastVisit') or doc.get('last_visit')),
        'visits': _num(doc.get('visits')),
        'total': _num(doc.get('total')),
        'extra': _extra(doc, known),
    }


def map_refills(doc):
    known = {'_id', 'id', 'date', 'product_id', 'productId', 'product', 'qty', 'by', 'by_user', 'created_at'}
    return {
        'id': _num(doc.get('id'), 0),
        'date': _dt(doc.get('date')),
        'product_id': _num(doc.get('product_id') or doc.get('productId'), None),
        'product': doc.get('product'),
        'qty': _num(doc.get('qty')),
        'by': doc.get('by') or doc.get('by_user'),
        'created_at': _dt(doc.get('created_at')),
        'extra': _extra(doc, known),
    }


def map_price_history(doc):
    known = {'_id', 'id', 'date', 'product_id', 'productId', 'product', 'old', 'new',
             'old_price', 'new_price', 'by', 'by_user', 'created_at'}
    return {
        'id': _num(doc.get('id'), 0),
        'date': _dt(doc.get('date')),
        'product_id': _num(doc.get('product_id') or doc.get('productId'), None),
        'product': doc.get('product'),
        'old_price': _num(doc.get('old', doc.get('old_price'))),
        'new_price': _num(doc.get('new', doc.get('new_price'))),
        'by': doc.get('by') or doc.get('by_user'),
        'created_at': _dt(doc.get('created_at')),
        'extra': _extra(doc, known),
    }


def map_login_logs(doc):
    known = {'_id', 'id', 'user', 'username', 'user_name', 'role', 'loginTime', 'login_time',
             'logoutTime', 'logout_time', 'shiftSessionId', 'shift_session_id', 'status', 'created_at'}
    username = doc.get('user') or doc.get('username') or doc.get('user_name')
    shift_session = doc.get('shiftSessionId')
    if shift_session is None:
        shift_session = doc.get('shift_session_id')
    return {
        'id': _num(doc.get('id'), 0),
        'username': username,
        'user_name': doc.get('user_name') or username,
        'role': doc.get('role'),
        'login_time': _text(doc.get('loginTime') or doc.get('login_time')),
        'logout_time': _text(doc.get('logoutTime') or doc.get('logout_time')),
        'shift_session_id': _num(shift_session, None),
        'status': doc.get('status'),
        'created_at': _dt(doc.get('created_at')),
        'extra': _extra(doc, known),
    }


def map_shifts(doc):
    known = {'_id', 'id', 'user', 'username', 'role', 'shiftStart', 'shift_start',
             'shiftEnd', 'shift_end', 'active', 'recipientEmail', 'recipient_email',
             'loginLogCleared', 'login_log_cleared', 'created_at'}
    return {
        'id': _num(doc.get('id'), 0),
        'username': doc.get('user') or doc.get('username'),
        'role': doc.get('role'),
        'shift_start': _text(doc.get('shiftStart') or doc.get('shift_start')),
        'shift_end': _text(doc.get('shiftEnd') or doc.get('shift_end')),
        'active': bool(doc.get('active')),
        'recipient_email': doc.get('recipientEmail') or doc.get('recipient_email'),
        'login_log_cleared': bool(doc.get('loginLogCleared') or doc.get('login_log_cleared')),
        'created_at': _dt(doc.get('created_at')),
        'extra': _extra(doc, known),
    }


def map_shift_reports(doc):
    known = {'_id', 'id', 'session_id', 'user', 'username', 'role', 'shift_start', 'shift_end',
             'total_bills', 'total_items_sold', 'total_sales_amount', 'payment_breakdown',
             'products_sold', 'remaining_stock_summary', 'report_email', 'report_subject',
             'email_status', 'email_error', 'email_sent_at', 'attachment_name',
             'attachment_count', 'status', 'created_at'}
    return {
        'id': _num(doc.get('id'), 0),
        'session_id': _num(doc.get('session_id'), None),
        'username': doc.get('user') or doc.get('username'),
        'role': doc.get('role'),
        'shift_start': _dt(doc.get('shift_start')),
        'shift_end': _dt(doc.get('shift_end')),
        'total_bills': _num(doc.get('total_bills')),
        'total_items_sold': _num(doc.get('total_items_sold')),
        'total_sales_amount': _num(doc.get('total_sales_amount')),
        'payment_breakdown': doc.get('payment_breakdown') or {},
        'products_sold': doc.get('products_sold') or [],
        'remaining_stock_summary': doc.get('remaining_stock_summary') or {},
        'report_email': doc.get('report_email'),
        'report_subject': doc.get('report_subject'),
        'email_status': doc.get('email_status'),
        'email_error': doc.get('email_error'),
        'email_sent_at': _dt(doc.get('email_sent_at')),
        'attachment_name': doc.get('attachment_name'),
        'attachment_count': _num(doc.get('attachment_count')),
        'status': doc.get('status'),
        'created_at': _dt(doc.get('created_at')),
        'extra': _extra(doc, known),
    }


def map_accounts(doc):
    return {
        'username': doc.get('user') or doc.get('username'),
        'pass': doc.get('pass'),
        'role': doc.get('role'),
        'created_at': _dt(doc.get('created_at')),
    }


def map_settings(doc):
    return {
        'key': doc.get('key') or 'main',
        'gst': _num(doc.get('gst')),
        'shop': doc.get('shop'),
        'addr': doc.get('addr'),
        'gstin': doc.get('gstin'),
        'fssai': doc.get('fssai'),
        'phone': doc.get('phone'),
    }


def map_counters(doc):
    return {'name': doc.get('_id') or doc.get('name'), 'seq': _num(doc.get('seq'))}


MAPPERS = {
    'products': map_products,
    'bills': map_bills,
    'sales': map_sales,
    'customers': map_customers,
    'refills': map_refills,
    'price_history': map_price_history,
    'login_logs': map_login_logs,
    'shifts': map_shifts,
    'shift_reports': map_shift_reports,
    'accounts': map_accounts,
    'settings': map_settings,
    'counters': map_counters,
}

# unique conflict targets that are not the id column
CONFLICT_TARGETS = {
    'accounts': 'username',
    'settings': 'key',
    'counters': 'name',
}


def build_upsert(table: str, row: dict) -> tuple[str, list]:
    columns = list(row.keys())
    column_sql = ', '.join(f'"{col}"' for col in columns)
    placeholders = ', '.join(f'${index}' for index in range(1, len(columns) + 1))
    target = CONFLICT_TARGETS.get(table, 'id')
    update_columns = [col for col in columns if col != target]
    if update_columns:
        set_sql = ', '.join(f'"{col}" = EXCLUDED."{col}"' for col in update_columns)
        sql = (
            f'INSERT INTO {table} ({column_sql}) VALUES ({placeholders}) '
            f'ON CONFLICT ({target}) DO UPDATE SET {set_sql}'
        )
    else:
        sql = f'INSERT INTO {table} ({column_sql}) VALUES ({placeholders}) ON CONFLICT ({target}) DO NOTHING'
    return sql, [row[col] for col in columns]


REPLACEABLE_TABLES = (
    'shift_reports', 'login_logs', 'shifts', 'price_history', 'refills',
    'bills', 'customers', 'sales', 'products', 'accounts', 'settings', 'counters',
)


async def migrate(replace: bool, verify_only: bool, only: list[str] | None):
    from pymongo import MongoClient

    uri, db_name = mongo_env()

    dsn = config.database_url()
    if not dsn:
        print('Missing SUPABASE_DB_URL. Add your Supabase connection string to server/.env.development.')
        raise SystemExit(1)

    tables = [name for name in COLLECTIONS if not only or name in only]

    print(f'Source:  MongoDB {db_name} (read-only)')
    print(f'Target:  Supabase PostgreSQL ({config.database_name()})')
    print(f"Tables:  {', '.join(tables)}")
    print('')

    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5, command_timeout=120, init=init_connection)
    mongo = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=15000)
    try:
        mongo.admin.command('ping')
    except Exception as error:
        print(f'Cannot reach MongoDB: {error}')
        await pool.close()
        return 1

    try:
        if not verify_only:
            await pool.execute(SCHEMA_SQL)
            if replace:
                for table in REPLACEABLE_TABLES:
                    if table in tables:
                        await pool.execute(f'TRUNCATE {table} RESTART IDENTITY CASCADE')

        database = mongo[db_name]
        failures = 0

        for table in tables:
            source = database[table]
            mapper = MAPPERS[table]
            total = source.count_documents({})
            migrated = 0

            if verify_only:
                target = await pool.fetchval(f'SELECT COUNT(*) FROM {table}')
                flag = 'OK ' if target == total else 'DIFF'
                print(f'  [{flag}] {table:<16} mongo={total:<7} postgres={target}')
                continue

            sql_holder = None
            for doc in source.find({}):
                row = mapper(doc)
                if row.get('id') in (None, 0) and table not in CONFLICT_TARGETS:
                    row.pop('id', None)
                sql, args = build_upsert(table, row)
                sql_holder = (sql, args)
                try:
                    await pool.execute(sql, *args)
                    migrated += 1
                except asyncpg.PostgresError as error:
                    failures += 1
                    print(f'    ! {table} doc {_id_of(doc)}: {error}')
            print(f'  [MIG] {table:<16} mongo={total:<7} migrated={migrated}')

        if not verify_only:
            for table in tables:
                if table in ('products', 'bills', 'sales', 'customers', 'refills',
                             'price_history', 'login_logs', 'shifts', 'shift_reports'):
                    await sync_counter(pool, table)
            print('Counters synced.')

        print('')
        print('Verification (row counts):')
        for table in tables:
            source_total = database[table].count_documents({})
            target_total = await pool.fetchval(f'SELECT COUNT(*) FROM {table}')
            flag = 'OK ' if source_total == target_total else 'DIFF'
            print(f'  [{flag}] {table:<16} mongo={source_total:<7} postgres={target_total}')

        if failures:
            print(f'\n{failures} document(s) failed to migrate.')
            return 1
        print('\nMigration complete. MongoDB data was left untouched.')
        return 0
    finally:
        await pool.close()
        mongo.close()


def _id_of(doc: dict):
    return doc.get('id') or doc.get('_id')


async def sync_counter(pool: asyncpg.Pool, table: str):
    top = await pool.fetchval(f'SELECT COALESCE(MAX(id), 0) FROM {table}')
    seq = await pool.fetchval(
        """
        INSERT INTO counters (name, seq) VALUES ($1, $2)
        ON CONFLICT (name) DO UPDATE SET seq = GREATEST(counters.seq, EXCLUDED.seq)
        RETURNING seq
        """,
        table,
        top or 0,
    )
    await _setval(pool, table, seq)


def _setval(pool: asyncpg.Pool, table: str, seq):
    return pool.execute(
        "SELECT setval(pg_get_serial_sequence($1, 'id'), $2, $3)",
        table,
        int(seq) if int(seq or 0) > 0 else 1,
        int(seq or 0) > 0,
    )


def main():
    parser = argparse.ArgumentParser(description='Migrate MongoDB data to Supabase PostgreSQL (read-only on Mongo).')
    parser.add_argument('--verify-only', action='store_true', help='only compare row counts, no writes')
    parser.add_argument('--replace', action='store_true', help='truncate target tables before migrating')
    parser.add_argument('--collections', default='', help='comma separated subset of collections')
    args = parser.parse_args()

    only = [name.strip() for name in args.collections.split(',') if name.strip()] or None
    if only:
        unknown = [name for name in only if name not in COLLECTIONS]
        if unknown:
            print(f'Unknown collections: {", ".join(unknown)}')
            print(f'Available: {", ".join(COLLECTIONS)}')
            raise SystemExit(1)

    raise SystemExit(asyncio.run(migrate(replace=args.replace, verify_only=args.verify_only, only=only)))


if __name__ == '__main__':
    main()

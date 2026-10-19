import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import asyncpg

from app import config
from app.database import SCHEMA_SQL

DEFAULT_PRODUCTS = [
    {'id': 1, 'code': 'GNR-15K', 'name': 'Groundnut Oil (Refined) 15kg Tin', 'cat': 'Groundnut', 'unit': 'tins', 'price': 2920, 'stock': 15, 'sold': 0, 'image': 'https://placehold.co/150x150?text=15kg+Tin'},
    {'id': 2, 'code': 'GNR-05C', 'name': 'Groundnut Oil (Refined) 5L Can', 'cat': 'Groundnut', 'unit': 'cans', 'price': 930, 'stock': 10, 'sold': 0, 'image': 'https://placehold.co/150x150?text=5L+Can'},
    {'id': 3, 'code': 'GNR-02C', 'name': 'Groundnut Oil (Refined) 2L Can', 'cat': 'Groundnut', 'unit': 'cans', 'price': 383, 'stock': 15, 'sold': 0, 'image': 'https://placehold.co/150x150?text=2L+Can'},
    {'id': 4, 'code': 'GNR-01B', 'name': 'Groundnut Oil (Refined) 1L Bottle', 'cat': 'Groundnut', 'unit': 'bottles', 'price': 188, 'stock': 30, 'sold': 0, 'image': 'https://placehold.co/150x150?text=1L+Bottle'},
    {'id': 5, 'code': 'GNR-01P', 'name': 'Groundnut Oil (Refined) 1L Packet', 'cat': 'Groundnut', 'unit': 'pkts', 'price': 184, 'stock': 50, 'sold': 0, 'image': 'https://placehold.co/150x150?text=1L+Packet'},
    {'id': 6, 'code': 'GNR-HFP', 'name': 'Groundnut Oil (Refined) 1/2L Packet', 'cat': 'Groundnut', 'unit': 'pkts', 'price': 92, 'stock': 0, 'sold': 0, 'image': 'https://placehold.co/150x150?text=Half+L+Pkt'},
    {'id': 7, 'code': 'GNP-15K', 'name': 'Groundnut Oil (Pure) 15kg Tin', 'cat': 'Groundnut', 'unit': 'tins', 'price': 3000, 'stock': 8, 'sold': 0, 'image': 'https://placehold.co/150x150?text=15kg+Tin'},
    {'id': 8, 'code': 'GNP-05C', 'name': 'Groundnut Oil (Pure) 5L Can', 'cat': 'Groundnut', 'unit': 'cans', 'price': 955, 'stock': 10, 'sold': 0, 'image': 'https://placehold.co/150x150?text=5L+Can'},
    {'id': 9, 'code': 'GNP-01P', 'name': 'Groundnut Oil (Pure) 1L Packet', 'cat': 'Groundnut', 'unit': 'pkts', 'price': 193, 'stock': 40, 'sold': 0, 'image': 'https://placehold.co/150x150?text=1L+Packet'},
    {'id': 10, 'code': 'SFR-15K', 'name': 'Sunflower Oil (Refined) 15kg Tin', 'cat': 'Sunflower', 'unit': 'tins', 'price': 2950, 'stock': 12, 'sold': 0, 'image': 'https://placehold.co/150x150?text=15kg+Tin'},
    {'id': 11, 'code': 'SFR-05C', 'name': 'Sunflower Oil (Refined) 5L Can', 'cat': 'Sunflower', 'unit': 'cans', 'price': 940, 'stock': 15, 'sold': 0, 'image': 'https://placehold.co/150x150?text=5L+Can'},
    {'id': 12, 'code': 'SFR-01P', 'name': 'Sunflower Oil (Refined) 1L Packet', 'cat': 'Sunflower', 'unit': 'pkts', 'price': 186, 'stock': 85, 'sold': 0, 'image': 'https://placehold.co/150x150?text=1L+Packet'},
    {'id': 13, 'code': 'PAL-15K', 'name': 'Palm Oil 15kg Tin', 'cat': 'Palm', 'unit': 'tins', 'price': 2445, 'stock': 24, 'sold': 0, 'image': 'https://placehold.co/150x150?text=15kg+Tin'},
    {'id': 14, 'code': 'PAL-05C', 'name': 'Palm Oil 5L Can', 'cat': 'Palm', 'unit': 'cans', 'price': 780, 'stock': 20, 'sold': 0, 'image': 'https://placehold.co/150x150?text=5L+Can'},
    {'id': 15, 'code': 'PAL-01P', 'name': 'Palm Oil 1L Packet', 'cat': 'Palm', 'unit': 'pkts', 'price': 154, 'stock': 60, 'sold': 0, 'image': 'https://placehold.co/150x150?text=1L+Packet'},
    {'id': 16, 'code': 'VAN-15K', 'name': 'Vanaspati 15kg Tin', 'cat': 'Vanaspati', 'unit': 'tins', 'price': 2700, 'stock': 5, 'sold': 0, 'image': 'https://placehold.co/150x150?text=15kg+Tin'},
    {'id': 17, 'code': 'SEM-01P', 'name': 'Sesame Oil (Mayil) 1L Packet', 'cat': 'Sesame', 'unit': 'pkts', 'price': 320, 'stock': 20, 'sold': 0, 'image': 'https://placehold.co/150x150?text=1L+Packet'},
    {'id': 18, 'code': 'SEM-HFP', 'name': 'Sesame Oil (Mayil) 1/2L Packet', 'cat': 'Sesame', 'unit': 'pkts', 'price': 160, 'stock': 25, 'sold': 0, 'image': 'https://placehold.co/150x150?text=Half+L+Pkt'},
    {'id': 19, 'code': 'SEU-15K', 'name': 'Sesame Oil (Mukil) 15kg Tin', 'cat': 'Sesame', 'unit': 'tins', 'price': 4050, 'stock': 4, 'sold': 0, 'image': 'https://placehold.co/150x150?text=15kg+Tin'},
    {'id': 20, 'code': 'SEK-15K', 'name': 'Sesame Oil (Karmegam Premium) 15kg Tin', 'cat': 'Sesame', 'unit': 'tins', 'price': 4560, 'stock': 5, 'sold': 0, 'image': 'https://placehold.co/150x150?text=15kg+Tin'},
    {'id': 21, 'code': 'SEK-05C', 'name': 'Sesame Oil (Karmegam) 5L Can', 'cat': 'Sesame', 'unit': 'cans', 'price': 1575, 'stock': 10, 'sold': 0, 'image': 'https://placehold.co/150x150?text=5L+Can'},
    {'id': 22, 'code': 'SEK-01B', 'name': 'Sesame Oil (Karmegam) 1L Bottle', 'cat': 'Sesame', 'unit': 'bottles', 'price': 340, 'stock': 15, 'sold': 0, 'image': 'https://placehold.co/150x150?text=1L+Bottle'},
    {'id': 23, 'code': 'SEK-01P', 'name': 'Sesame Oil (Karmegam) 1L Packet', 'cat': 'Sesame', 'unit': 'pkts', 'price': 330, 'stock': 30, 'sold': 0, 'image': 'https://placehold.co/150x150?text=1L+Packet'},
    {'id': 24, 'code': 'SEK-HFB', 'name': 'Sesame Oil (Karmegam) 1/2L Bottle', 'cat': 'Sesame', 'unit': 'bottles', 'price': 170, 'stock': 20, 'sold': 0, 'image': 'https://placehold.co/150x150?text=Half+L+Btl'},
    {'id': 25, 'code': 'SEK-HFP', 'name': 'Sesame Oil (Karmegam) 1/2L Packet', 'cat': 'Sesame', 'unit': 'pkts', 'price': 165, 'stock': 25, 'sold': 0, 'image': 'https://placehold.co/150x150?text=Half+L+Pkt'},
    {'id': 26, 'code': 'SEK-200B', 'name': 'Sesame Oil (Karmegam) 200ml Bottle', 'cat': 'Sesame', 'unit': 'bottles', 'price': 70, 'stock': 15, 'sold': 0, 'image': 'https://placehold.co/150x150?text=200ml+Bottle'},
    {'id': 27, 'code': 'CAS-01B', 'name': 'Castor Oil 1L Bottle', 'cat': 'Castor', 'unit': 'bottles', 'price': 220, 'stock': 10, 'sold': 0, 'image': 'https://placehold.co/150x150?text=1L+Bottle'},
    {'id': 28, 'code': 'CAS-HFB', 'name': 'Castor Oil 1/2L Bottle', 'cat': 'Castor', 'unit': 'bottles', 'price': 110, 'stock': 15, 'sold': 0, 'image': 'https://placehold.co/150x150?text=Half+L+Btl'},
    {'id': 29, 'code': 'CON-01P', 'name': 'Coconut Oil 1L Packet', 'cat': 'Coconut', 'unit': 'pkts', 'price': 370, 'stock': 30, 'sold': 0, 'image': 'https://placehold.co/150x150?text=1L+Packet'},
    {'id': 30, 'code': 'CON-01B', 'name': 'Coconut Oil 1L Bottle', 'cat': 'Coconut', 'unit': 'bottles', 'price': 370, 'stock': 20, 'sold': 0, 'image': 'https://placehold.co/150x150?text=1L+Bottle'},
    {'id': 31, 'code': 'CON-HFP', 'name': 'Coconut Oil 1/2L Packet', 'cat': 'Coconut', 'unit': 'pkts', 'price': 185, 'stock': 25, 'sold': 0, 'image': 'https://placehold.co/150x150?text=Half+L+Pkt'},
    {'id': 32, 'code': 'CON-HFB', 'name': 'Coconut Oil 1/2L Bottle', 'cat': 'Coconut', 'unit': 'bottles', 'price': 185, 'stock': 20, 'sold': 0, 'image': 'https://placehold.co/150x150?text=Half+L+Bottle'},
    {'id': 33, 'code': 'CON-200B', 'name': 'Coconut Oil 200g Bottle', 'cat': 'Coconut', 'unit': 'bottles', 'price': 100, 'stock': 15, 'sold': 0, 'image': 'https://placehold.co/150x150?text=200g+Bottle'},
    {'id': 34, 'code': 'CON-100B', 'name': 'Coconut Oil 100g Bottle', 'cat': 'Coconut', 'unit': 'bottles', 'price': 50, 'stock': 20, 'sold': 0, 'image': 'https://placehold.co/150x150?text=100g+Bottle'},
]


async def seed():
    dsn = config.database_url()
    if not dsn:
        print('Missing SUPABASE_DB_URL.')
        raise SystemExit(1)

    conn = await asyncpg.connect(dsn=dsn)
    try:
        await conn.execute(SCHEMA_SQL)
        print('Connected to PostgreSQL')

        await conn.execute('DELETE FROM products')
        print('Cleared existing products.')

        created_at = datetime.now(timezone.utc)
        for product in DEFAULT_PRODUCTS:
            await conn.execute(
                """
                INSERT INTO products (id, code, name, cat, unit, price, stock, opening_stock, sold, image, created_at, extra)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, '{}'::jsonb)
                """,
                product['id'],
                product['code'],
                product['name'],
                product['cat'],
                product['unit'],
                product['price'],
                product['stock'],
                max(0, product.get('stock') or 0),
                product.get('sold') or 0,
                product['image'],
                created_at,
            )
        print(f'Successfully seeded {len(DEFAULT_PRODUCTS)} products.')

        await conn.execute("INSERT INTO counters (name, seq) VALUES ('products', $1) "
                           "ON CONFLICT (name) DO UPDATE SET seq = GREATEST(counters.seq, EXCLUDED.seq)",
                           max(p['id'] for p in DEFAULT_PRODUCTS))
        await sync_counter_via(conn, 'products', 'products')
        print('Successfully synced product ID counter.')
    except Exception as error:
        print('Error seeding products:', error)
        raise
    finally:
        await conn.close()


async def sync_counter_via(conn, name: str, table_name: str):
    top = await conn.fetchval(f'SELECT COALESCE(MAX(id), 0) FROM {table_name}')
    seq = await conn.fetchval(
        """
        INSERT INTO counters (name, seq) VALUES ($1, $2)
        ON CONFLICT (name) DO UPDATE SET seq = GREATEST(counters.seq, EXCLUDED.seq)
        RETURNING seq
        """,
        name,
        top or 0,
    )
    if int(seq or 0) > 0:
        await conn.execute("SELECT setval(pg_get_serial_sequence($1, 'id'), $2)", table_name, int(seq))
    else:
        await conn.execute("SELECT setval(pg_get_serial_sequence($1, 'id'), 1, false)", table_name)


if __name__ == '__main__':
    asyncio.run(seed())

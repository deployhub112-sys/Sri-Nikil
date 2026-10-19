from fastapi import APIRouter, Body

from .. import config
from ..database import (
    clamp_product_inventory,
    delete_expired_bills,
    execute,
    fetch_all,
    fetch_one,
    map_account,
    map_bill,
    map_customer,
    map_login_log,
    map_price_history,
    map_product,
    map_refill,
    map_settings,
    serialize,
    serialize_account,
    serialize_many,
    serialize_products,
    sync_shift_login_logs,
)

router = APIRouter()


@router.get('/')
async def root():
    return {'ok': True, 'service': 'Sri Nikil FastAPI Supabase API', 'database': config.database_name()}


@router.get('/api/db')
async def database_snapshot():
    await sync_shift_login_logs()
    await clamp_product_inventory()
    await delete_expired_bills()

    products = [map_product(row) for row in await fetch_all('SELECT * FROM products ORDER BY id ASC')]
    bills = [map_bill(row) for row in await fetch_all('SELECT * FROM bills ORDER BY date DESC NULLS LAST, id DESC')]
    sales = [dict(row) for row in await fetch_all('SELECT * FROM sales ORDER BY date DESC NULLS LAST, id DESC')]
    customers = [
        map_customer(row) for row in await fetch_all('SELECT * FROM customers ORDER BY last_visit DESC NULLS LAST, id DESC')
    ]
    refills = [map_refill(row) for row in await fetch_all('SELECT * FROM refills ORDER BY date DESC NULLS LAST, id DESC')]
    price_history = [
        map_price_history(row) for row in await fetch_all('SELECT * FROM price_history ORDER BY date DESC NULLS LAST, id DESC')
    ]
    login_logs = [
        map_login_log(row)
        for row in await fetch_all(
            'SELECT * FROM login_logs ORDER BY login_time DESC NULLS LAST, logout_time DESC NULLS LAST, id DESC'
        )
    ]
    accounts = [map_account(row) for row in await fetch_all('SELECT * FROM accounts ORDER BY username ASC')]
    settings_row = await fetch_one("SELECT * FROM settings WHERE key = 'main'")

    return {
        'products': serialize_products(products),
        'bills': serialize_many(bills),
        'sales': serialize_many(sales),
        'customers': serialize_many(customers),
        'refills': serialize_many(refills),
        'priceHistory': serialize_many(price_history),
        'loginLogs': serialize_many(login_logs),
        'accounts': [serialize_account(account) for account in accounts],
        'settings': serialize(map_settings(settings_row)),
    }


@router.post('/api/reset-sales-data')
async def reset_sales_data():
    await execute('DELETE FROM bills')
    await execute('DELETE FROM customers')
    await execute('DELETE FROM refills')
    await execute('DELETE FROM price_history')
    await execute('DELETE FROM login_logs')
    await execute('DELETE FROM shifts')
    await execute(
        """
        UPDATE products SET
            opening_stock = GREATEST(COALESCE(opening_stock, 0), 0),
            stock = GREATEST(COALESCE(opening_stock, 0), 0),
            sold = 0
        """
    )
    return {'success': True}


@router.post('/api/purchases', status_code=201)
async def create_purchase(payload: dict = Body(default_factory=dict)):
    return {'success': True}

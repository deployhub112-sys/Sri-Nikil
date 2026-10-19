from fastapi import APIRouter, Body, HTTPException

from ..database import (
    as_valid_date,
    delete_expired_bills,
    execute,
    fetch_all,
    fetch_one,
    get_bill_expiry_date,
    get_next_bill_no,
    map_bill,
    map_product,
    next_id,
    normalize_bill_items,
    non_negative_number,
    restore_stock_for_items,
    serialize,
    serialize_many,
    to_number,
    utcnow,
)

router = APIRouter()

BILL_PAYLOAD_KEYS = {
    'id', 'billNo', 'bill_no', 'customer', 'phone', 'payment', 'items',
    'subtotal', 'cgst', 'sgst', 'grand', 'by', 'by_user', 'date',
    'expires_at', 'created_at',
}


def _bill_extra(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in BILL_PAYLOAD_KEYS and value is not None}


@router.get('/api/bills')
async def list_bills():
    await delete_expired_bills()
    rows = await fetch_all('SELECT * FROM bills ORDER BY date DESC NULLS LAST, id DESC')
    return serialize_many([map_bill(row) for row in rows])


@router.post('/api/bills', status_code=201)
async def create_bill(payload: dict = Body(default_factory=dict)):
    items = normalize_bill_items(payload.get('items'))

    product_ids = [pid for pid in (to_number(item.get('id')) for item in items) if pid]

    rows = await fetch_all('SELECT * FROM products WHERE id = ANY($1::bigint[])', product_ids)
    product_by_id = {row['id']: map_product(row) for row in rows}

    for item in items:
        product_id = to_number(item.get('id'))
        qty = non_negative_number(item.get('qty'))
        product = product_by_id.get(product_id)
        if not product or qty <= 0 or non_negative_number(product.get('stock')) < qty:
            raise HTTPException(status_code=400, detail=f'Insufficient stock for {item.get("name") or product_id}')

    for item in items:
        qty = non_negative_number(item.get('qty'))
        await execute(
            'UPDATE products SET stock = COALESCE(stock, 0) - $2, sold = COALESCE(sold, 0) + $2 WHERE id = $1',
            to_number(item.get('id')),
            qty,
        )

    existing_rows = await fetch_all('SELECT bill_no FROM bills')
    now = utcnow()
    bill_date = as_valid_date(payload.get('date')) if payload.get('date') else now
    bill_no = payload.get('billNo') or payload.get('bill_no') or get_next_bill_no(
        [{'bill_no': row['bill_no']} for row in existing_rows]
    )

    by_value = payload.get('by') or payload.get('by_user') or 'system'

    # Retention policy: every bill is deleted exactly 4 calendar years after
    # it was created (created_at), regardless of the bill's own date field.
    expires_at = get_bill_expiry_date(now)

    row = await fetch_one(
        """
        INSERT INTO bills (
            id, bill_no, customer, phone, payment, items, subtotal, cgst, sgst,
            grand, "by", by_user, date, expires_at, created_at, extra
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
        RETURNING *
        """,
        await next_id('bills'),
        bill_no,
        payload.get('customer') or '',
        payload.get('phone') or '',
        payload.get('payment') or '',
        items,
        to_number(payload.get('subtotal')),
        to_number(payload.get('cgst')),
        to_number(payload.get('sgst')),
        to_number(payload.get('grand')),
        by_value,
        by_value,
        bill_date,
        expires_at,
        now,
        _bill_extra(payload),
    )
    bill = map_bill(row)

    if bill.get('phone'):
        now = utcnow()
        customer_id = await next_id('customers')
        await execute(
            """
            INSERT INTO customers (id, name, phone, first_visit, last_visit, visits, total, extra)
            VALUES ($1, $2, $3, $4, $5, 1, $6, '{}'::jsonb)
            ON CONFLICT (phone) WHERE phone IS NOT NULL AND phone <> '' DO UPDATE SET
                name = EXCLUDED.name,
                last_visit = EXCLUDED.last_visit,
                visits = COALESCE(customers.visits, 0) + EXCLUDED.visits,
                total = COALESCE(customers.total, 0) + EXCLUDED.total
            """,
            customer_id,
            bill.get('customer') or '',
            bill.get('phone'),
            now,
            now,
            to_number(bill.get('grand')),
        )

    return serialize(bill)


@router.delete('/api/bills/{bill_id}')
async def delete_bill(bill_id: int):
    bill_row = await fetch_one('SELECT * FROM bills WHERE id = $1', bill_id)
    if bill_row:
        bill = map_bill(bill_row)
        await restore_stock_for_items(bill.get('items'))
        await execute('DELETE FROM bills WHERE id = $1', bill_id)
    return {'success': True}


@router.delete('/api/bills')
async def delete_all_bills():
    rows = await fetch_all('SELECT id FROM bills ORDER BY id')
    for row in rows:
        bill = map_bill(await fetch_one('SELECT * FROM bills WHERE id = $1', row['id']))
        await restore_stock_for_items(bill.get('items'))
    await execute('DELETE FROM bills')
    await execute('DELETE FROM customers')
    return {'success': True}

from fastapi import APIRouter, Body, HTTPException

from ..database import (
    as_valid_date,
    execute,
    fetch_all,
    fetch_one,
    find_product_by_id,
    map_refill,
    next_id,
    non_negative_number,
    serialize,
    serialize_many,
    to_number,
    utcnow,
)

router = APIRouter()

REFILL_PAYLOAD_KEYS = {'id', 'date', 'product_id', 'productId', 'product', 'qty', 'by', 'by_user', 'created_at'}


def _refill_extra(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in REFILL_PAYLOAD_KEYS and value is not None}


@router.get('/api/refills')
async def list_refills():
    rows = await fetch_all('SELECT * FROM refills ORDER BY date DESC NULLS LAST, id DESC')
    return serialize_many([map_refill(row) for row in rows])


@router.post('/api/refills', status_code=201)
async def create_refill(payload: dict = Body(default_factory=dict)):
    product_id = to_number(payload.get('product_id') or payload.get('productId') or payload.get('id'))
    qty = non_negative_number(payload.get('qty'))
    product = await find_product_by_id(product_id)

    if not product or qty <= 0:
        raise HTTPException(status_code=400, detail='Invalid product or quantity')

    await execute(
        'UPDATE products SET stock = COALESCE(stock, 0) + $2, opening_stock = COALESCE(opening_stock, 0) + $2 WHERE id = $1',
        product_id,
        qty,
    )

    row = await fetch_one(
        """
        INSERT INTO refills (id, date, product_id, product, qty, "by", created_at, extra)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        await next_id('refills'),
        as_valid_date(payload.get('date')) if payload.get('date') else utcnow(),
        product_id,
        payload.get('product') or product.get('name'),
        qty,
        payload.get('by_user') or payload.get('by') or 'system',
        utcnow(),
        _refill_extra(payload),
    )
    return serialize(map_refill(row))


async def _restore_refill_stock(refill: dict):
    qty = non_negative_number(refill.get('qty'))
    await execute(
        """
        UPDATE products SET
            stock = GREATEST(GREATEST(COALESCE(stock, 0), 0) - $2, 0),
            opening_stock = GREATEST(GREATEST(COALESCE(opening_stock, 0), 0) - $2, 0)
        WHERE id = $1
        """,
        to_number(refill.get('product_id')),
        qty,
    )


@router.delete('/api/refills/{refill_id}')
async def delete_refill(refill_id: int):
    refill_row = await fetch_one('SELECT * FROM refills WHERE id = $1', refill_id)
    if refill_row:
        await _restore_refill_stock(map_refill(refill_row))
        await execute('DELETE FROM refills WHERE id = $1', refill_id)
    return {'success': True}


@router.delete('/api/refills')
async def delete_all_refills():
    rows = await fetch_all('SELECT * FROM refills ORDER BY id')
    for row in rows:
        await _restore_refill_stock(map_refill(row))
    await execute('DELETE FROM refills')
    return {'success': True}

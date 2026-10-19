from fastapi import APIRouter, Body

from ..database import as_valid_date, execute, fetch_all, fetch_one, map_price_history, next_id, serialize, serialize_many, to_number, utcnow

router = APIRouter()


@router.get('/api/price-history')
async def list_price_history():
    rows = await fetch_all('SELECT * FROM price_history ORDER BY date DESC NULLS LAST, id DESC')
    return serialize_many([map_price_history(row) for row in rows])


@router.post('/api/price-history', status_code=201)
async def create_price_history(payload: dict = Body(default_factory=dict)):
    row = await fetch_one(
        """
        INSERT INTO price_history (id, date, product_id, product, old_price, new_price, "by", created_at, extra)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING *
        """,
        await next_id('price_history'),
        as_valid_date(payload.get('date')) if payload.get('date') else utcnow(),
        to_number(payload.get('product_id') or payload.get('productId')),
        payload.get('product') or '',
        to_number(payload.get('old')),
        to_number(payload.get('new')),
        payload.get('by') or payload.get('by_user') or 'system',
        utcnow(),
        {key: value for key, value in payload.items() if key not in {
            'id', 'date', 'product_id', 'productId', 'product', 'old', 'new', 'by', 'by_user', 'created_at',
        } and value is not None},
    )
    return serialize(map_price_history(row))


@router.delete('/api/price-history/{history_id}')
async def delete_price_history(history_id: int):
    await execute('DELETE FROM price_history WHERE id = $1', history_id)
    return {'success': True}


@router.delete('/api/price-history')
async def delete_all_price_history():
    await execute('DELETE FROM price_history')
    return {'success': True}

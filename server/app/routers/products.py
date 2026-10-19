from fastapi import APIRouter, Body, HTTPException

from ..database import (
    clamp_product_inventory,
    execute,
    fetch_all,
    fetch_one,
    find_product_by_id,
    map_product,
    next_id,
    non_negative_number,
    serialize_product,
    serialize_products,
    to_number,
    utcnow,
)

router = APIRouter()

PRODUCT_PAYLOAD_KEYS = {
    'id', 'code', 'name', 'cat', 'category', 'unit', 'price',
    'stock', 'opening_stock', 'openingStock', 'sold', 'image', 'created_at',
}


def _product_extra(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in PRODUCT_PAYLOAD_KEYS and value is not None}


@router.get('/api/products')
async def list_products():
    await clamp_product_inventory()
    rows = await fetch_all('SELECT * FROM products ORDER BY id ASC')
    return serialize_products([map_product(row) for row in rows])


@router.post('/api/products', status_code=201)
async def create_product(payload: dict = Body(default_factory=dict)):
    product_id = await next_id('products')
    stock = non_negative_number(payload.get('stock'))
    opening_stock = max(non_negative_number(payload.get('opening_stock', payload.get('openingStock')), stock), stock)

    row = await fetch_one(
        """
        INSERT INTO products (id, code, name, cat, unit, price, stock, opening_stock, sold, image, created_at, extra)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        RETURNING *
        """,
        product_id,
        payload.get('code') or f'P-{product_id}',
        payload.get('name') or '',
        payload.get('cat') or payload.get('category') or '',
        payload.get('unit') or '',
        non_negative_number(payload.get('price')),
        stock,
        opening_stock,
        non_negative_number(payload.get('sold')),
        payload.get('image') or '',
        utcnow(),
        _product_extra(payload),
    )
    return serialize_product(map_product(row))


@router.put('/api/products/opening-stock/sync')
async def sync_opening_stock():
    await execute(
        """
        UPDATE products SET
            stock = GREATEST(COALESCE(stock, 0), 0),
            opening_stock = GREATEST(COALESCE(stock, 0), 0),
            sold = 0
        """
    )
    return {'success': True}


@router.put('/api/products/{product_id}/price')
async def update_product_price(product_id: int, payload: dict = Body(default_factory=dict)):
    product = await find_product_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail='Product not found')

    old_price = to_number(product.get('price'))
    new_price = to_number(payload.get('new_price', payload.get('newPrice')))
    await execute('UPDATE products SET price = $2 WHERE id = $1', product_id, new_price)
    await execute(
        """
        INSERT INTO price_history (id, date, product_id, product, old_price, new_price, by, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        await next_id('price_history'),
        utcnow(),
        product_id,
        product.get('name'),
        old_price,
        new_price,
        payload.get('by_user') or payload.get('by') or 'system',
        utcnow(),
    )
    return {'success': True}


@router.delete('/api/products/{product_id}')
async def delete_product(product_id: int):
    await execute('DELETE FROM products WHERE id = $1', product_id)
    return {'success': True}

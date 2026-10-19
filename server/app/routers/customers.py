from fastapi import APIRouter

from ..database import execute, fetch_all, map_customer, serialize_many

router = APIRouter()


@router.get('/api/customers')
async def list_customers():
    rows = await fetch_all('SELECT * FROM customers ORDER BY last_visit DESC NULLS LAST, id DESC')
    return serialize_many([map_customer(row) for row in rows])


@router.delete('/api/customers')
async def delete_all_customers():
    await execute('DELETE FROM customers')
    return {'success': True}

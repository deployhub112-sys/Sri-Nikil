from fastapi import APIRouter, Body, HTTPException

from ..constants import USER_ROLES
from ..database import execute, fetch_all, fetch_one, map_account, serialize_account, utcnow
from ..security import hash_password

router = APIRouter()


@router.get('/api/accounts')
async def list_accounts():
    rows = await fetch_all('SELECT * FROM accounts ORDER BY username ASC')
    return [serialize_account(map_account(row)) for row in rows]


@router.post('/api/accounts', status_code=201)
async def create_account(payload: dict = Body(default_factory=dict)):
    user = str(payload.get('user') or '').strip()
    password = payload.get('password')

    if not user or not password:
        raise HTTPException(status_code=400, detail='User and password are required')

    account = {
        'user': user,
        'pass': hash_password(password),
        'role': payload.get('role') or USER_ROLES['STAFF'],
        'created_at': utcnow(),
    }
    await execute(
        'INSERT INTO accounts (username, pass, role, created_at) VALUES ($1, $2, $3, $4)',
        account['user'],
        account['pass'],
        account['role'],
        account['created_at'],
    )
    return {'user': account['user'], 'role': account['role'], 'pass': ''}


@router.put('/api/accounts/{user}/password')
async def reset_account_password(user: str, payload: dict = Body(default_factory=dict)):
    await execute('UPDATE accounts SET pass = $2 WHERE username = $1', user, hash_password(payload.get('password') or ''))
    return {'success': True}


@router.delete('/api/accounts/{user}')
async def delete_account(user: str):
    if user == 'admin':
        raise HTTPException(status_code=400, detail='Admin cannot be deleted')
    await execute('DELETE FROM accounts WHERE username = $1', user)
    return {'success': True}

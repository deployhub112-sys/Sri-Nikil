from fastapi import APIRouter, Body, HTTPException

from ..constants import USER_ROLES
from ..database import fetch_one, map_account
from ..security import verify_password

router = APIRouter()


@router.post('/api/auth/login')
async def login(payload: dict = Body(default_factory=dict)):
    username = str(payload.get('user') or '').strip()
    row = await fetch_one('SELECT * FROM accounts WHERE lower(username) = lower($1)', username)
    account = map_account(row) if row else None

    if not account or not verify_password(payload.get('password'), row['pass']):
        raise HTTPException(status_code=401, detail='Invalid username or password')

    return {'user': account.get('user'), 'role': account.get('role') or USER_ROLES['STAFF']}

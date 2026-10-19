from fastapi import APIRouter, Body, Query

from ..database import (
    execute,
    fetch_all,
    fetch_one,
    map_login_log,
    next_id,
    serialize,
    serialize_many,
    sync_shift_login_logs,
    to_iso,
    to_number,
    utcnow,
)

router = APIRouter()

LOG_PAYLOAD_KEYS = {'id', 'user', 'user_name', 'role', 'loginTime', 'login_time', 'logoutTime', 'logout_time', 'created_at'}


def _log_extra(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in LOG_PAYLOAD_KEYS and value is not None}


@router.get('/api/login-logs')
async def list_login_logs():
    await sync_shift_login_logs()
    rows = await fetch_all(
        'SELECT * FROM login_logs ORDER BY login_time DESC NULLS LAST, logout_time DESC NULLS LAST, id DESC'
    )
    return serialize_many([map_login_log(row) for row in rows])


@router.post('/api/login-logs', status_code=201)
async def create_login_log(payload: dict = Body(default_factory=dict)):
    login_time = payload.get('loginTime') or payload.get('login_time') or to_iso(utcnow())
    user = payload.get('user') or payload.get('user_name')

    row = await fetch_one(
        """
        INSERT INTO login_logs (id, username, user_name, role, login_time, logout_time, shift_session_id, status, created_at, extra)
        VALUES ($1, $2, $3, $4, $5, NULL, NULL, NULL, $6, $7)
        RETURNING *
        """,
        await next_id('login_logs'),
        user,
        user,
        payload.get('role') or 'Staff',
        login_time,
        utcnow(),
        _log_extra(payload),
    )
    return serialize(map_login_log(row))


@router.put('/api/login-logs/{log_id}/logout')
async def logout_login_log(log_id: int):
    logout = to_iso(utcnow())
    await execute('UPDATE login_logs SET logout_time = $2 WHERE id = $1', log_id, logout)
    return {'success': True}


@router.delete('/api/login-logs/{log_id}')
async def delete_login_log(log_id: int):
    existing_row = await fetch_one('SELECT * FROM login_logs WHERE id = $1', log_id)
    await execute('DELETE FROM login_logs WHERE id = $1', log_id)

    if existing_row and existing_row['shift_session_id']:
        await execute(
            'UPDATE shifts SET login_log_cleared = true WHERE id = $1',
            to_number(existing_row['shift_session_id']),
        )

    return {'success': True}


@router.delete('/api/login-logs')
async def delete_login_logs(roles: str = Query(default='')):
    role_list = [role.strip().lower() for role in roles.split(',') if role.strip()]

    shift_ids = []
    if role_list:
        shift_rows = await fetch_all(
            'SELECT shift_session_id FROM login_logs WHERE lower(role) = ANY($1::text[]) AND shift_session_id IS NOT NULL',
            role_list,
        )
    else:
        shift_rows = await fetch_all('SELECT shift_session_id FROM login_logs WHERE shift_session_id IS NOT NULL')
    shift_ids = [to_number(row['shift_session_id']) for row in shift_rows]

    if role_list:
        await execute('DELETE FROM login_logs WHERE lower(role) = ANY($1::text[])', role_list)
    else:
        await execute('DELETE FROM login_logs')

    if shift_ids:
        await execute('UPDATE shifts SET login_log_cleared = true WHERE id = ANY($1::bigint[])', shift_ids)

    return {'success': True}

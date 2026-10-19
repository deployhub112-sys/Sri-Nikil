"""Mirrors the default admin into Supabase Auth (Dashboard -> Authentication).

Uses the GoTrue admin API with the service role key. All calls are
idempotent: an existing admin auth user is reused, never duplicated.
"""

import json
import urllib.error
import urllib.request

from . import config

API_TIMEOUT = 20
PAGE_SIZE = 200


def _headers() -> dict | None:
    service_key = config.supabase_service_role_key()
    if not config.supabase_url() or not service_key:
        return None
    return {
        'apikey': service_key,
        'Authorization': f'Bearer {service_key}',
        'Content-Type': 'application/json',
    }


def _request(method: str, path: str, payload: dict | None = None):
    headers = _headers()
    if headers is None:
        print('Supabase Auth skipped: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured.')
        return None

    url = config.supabase_url().rstrip('/') + path
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode()
        print(f'Supabase Auth {method} {path} failed ({error.code}): {detail[:300]}')
        return None
    except Exception as error:
        print(f'Supabase Auth {method} {path} failed: {error}')
        return None


def list_users() -> list | None:
    users: list = []
    page = 1
    while True:
        data = _request('GET', f'/auth/v1/admin/users?page={page}&per_page={PAGE_SIZE}')
        if data is None:
            return None
        batch = data.get('users') or []
        users.extend(batch)
        if len(batch) < PAGE_SIZE:
            return users
        page += 1


def ensure_admin_auth_user(username: str, name: str, email: str | None, password: str) -> str | None:
    """Return the Supabase Auth user id for the admin, creating it if missing."""
    users = list_users()
    if users is None:
        return None

    username_lower = (username or '').lower()
    email_lower = (email or '').lower()
    for user in users:
        meta = user.get('user_metadata') or {}
        matches_email = bool(email_lower) and (user.get('email') or '').lower() == email_lower
        matches_username = (meta.get('username') or '').lower() == username_lower
        if matches_email or matches_username:
            return user.get('id')

    if not email:
        print('DEFAULT_ADMIN_EMAIL is not set; skipping Supabase Auth admin user.')
        return None

    created = _request('POST', '/auth/v1/admin/users', {
        'email': email,
        'password': password,
        'email_confirm': True,
        'user_metadata': {'username': username, 'name': name, 'role': 'Admin'},
    })
    if not created or not created.get('id'):
        return None

    print(f'Supabase Auth admin user created: {email}')
    return created.get('id')

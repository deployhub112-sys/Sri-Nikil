import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

SERVER_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = SERVER_DIR.parent
CWD_DIR = Path.cwd()

ENV_CANDIDATES = [
    CWD_DIR / '.env.development',
    SERVER_DIR / '.env.development',
    ROOT_DIR / '.env.development',
    CWD_DIR / '.env',
    SERVER_DIR / '.env',
    ROOT_DIR / '.env',
]

ENV_PATH = next((candidate for candidate in ENV_CANDIDATES if candidate.is_file()), None)
if ENV_PATH is not None:
    load_dotenv(ENV_PATH, override=False)

MAIL_ENV_KEYS = (
    'SMTP_HOST',
    'SMTP_PORT',
    'SMTP_SECURE',
    'SMTP_USER',
    'SMTP_SENDER_EMAIL',
    'SMTP_FROM',
    'SMTP_PASS',
    'SMTP_PASSWORD',
    'MAIL_USER',
    'MAIL_FROM',
    'MAIL_APP_PASSWORD',
    'MAIL_PASSWORD',
    'SHIFT_REPORT_EMAIL',
)


def refresh_runtime_mail_env():
    if ENV_PATH is None or not ENV_PATH.is_file():
        return

    try:
        parsed_env = dotenv_values(ENV_PATH)
    except Exception as error:  # pragma: no cover - defensive
        print(f'Unable to refresh runtime mail environment: {error}')
        return

    for key in MAIL_ENV_KEYS:
        value = parsed_env.get(key)
        if value is not None:
            os.environ[key] = value


def port() -> int:
    try:
        return int(os.environ.get('PORT') or 5001)
    except ValueError:
        return 5001


def host() -> str:
    return os.environ.get('HOST', '0.0.0.0')


def database_url() -> str | None:
    return (
        os.environ.get('SUPABASE_DB_URL')
        or os.environ.get('DATABASE_URL')
        or os.environ.get('POSTGRES_URL')
        or os.environ.get('SUPABASE_POSTGRES_URL')
        or None
    )


def database_name() -> str:
    from urllib.parse import urlsplit

    url = urlsplit(database_url() or '')
    name = url.path.lstrip('/').split('?')[0] if url.path else ''
    return name or 'postgres'


def supabase_url() -> str | None:
    return os.environ.get('SUPABASE_URL') or os.environ.get('NEXT_PUBLIC_SUPABASE_URL') or None


def supabase_anon_key() -> str | None:
    return os.environ.get('SUPABASE_ANON_KEY') or os.environ.get('NEXT_PUBLIC_SUPABASE_ANON_KEY') or None


def supabase_service_role_key() -> str | None:
    return os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or None

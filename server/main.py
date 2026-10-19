import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
import asyncpg

from app import config
from app.constants import BILL_RETENTION_YEARS
from app.database import connect, delete_expired_bills, disconnect
from app.routers import (
    accounts,
    auth,
    bills,
    customers,
    login_logs,
    meta,
    price_history,
    products,
    refills,
    settings,
    shifts,
)

MAX_BODY_BYTES = 10 * 1024 * 1024


def _purge_interval_seconds() -> float:
    try:
        hours = float(os.environ.get('BILL_PURGE_INTERVAL_HOURS') or 6)
    except ValueError:
        hours = 6.0
    return max(300.0, hours * 3600)


async def bill_purge_loop():
    """Background retention task: deletes bills exactly 4 years after created_at."""
    interval = _purge_interval_seconds()
    print(
        f'Bill retention scheduler active: checks every {interval / 3600:g}h, '
        f'bills auto-deleted {BILL_RETENTION_YEARS} years after created_at.'
    )
    while True:
        try:
            deleted = await delete_expired_bills()
            if deleted:
                print(f'Retention scheduler deleted {deleted} expired bill(s).')
        except Exception as error:
            print(f'Bill retention scheduler error: {error}')
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    info = await connect()
    print(f"FastAPI Supabase API running on http://localhost:{info['port']}")
    print(f"PostgreSQL database: {info['database']}")
    print(f"Swagger docs: http://localhost:{info['port']}/api-docs")
    purge_task = asyncio.create_task(bill_purge_loop())
    yield
    purge_task.cancel()
    with suppress(asyncio.CancelledError):
        await purge_task
    await disconnect()


app = FastAPI(
    title='Sri Nikil Supabase API',
    version='1.0.0',
    description='FastAPI + Supabase (PostgreSQL) backend API',
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.middleware('http')
async def limit_body_size(request: Request, call_next):
    content_length = request.headers.get('content-length')
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return JSONResponse({'error': 'Request body too large'}, status_code=413)
        except ValueError:
            pass
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse({'error': 'Invalid request body'}, status_code=400)


@app.exception_handler(asyncpg.exceptions.UniqueViolationError)
async def duplicate_key_handler(request: Request, exc: asyncpg.exceptions.UniqueViolationError):
    return JSONResponse({'error': 'Duplicate value already exists'}, status_code=409)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    body = detail if isinstance(detail, dict) else {'error': detail}
    return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse({'error': str(exc) or 'Server error'}, status_code=500)


@app.get('/api-docs.json')
async def api_docs_json():
    return app.openapi()


@app.get('/api-docs')
async def api_docs():
    return RedirectResponse(url='/docs')


for router in (
    meta.router,
    products.router,
    bills.router,
    customers.router,
    refills.router,
    price_history.router,
    accounts.router,
    auth.router,
    settings.router,
    login_logs.router,
    shifts.router,
):
    app.include_router(router)


@app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
async def unknown_api_path(path: str):
    raise HTTPException(status_code=404, detail='Not found')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run('main:app', host=config.host(), port=config.port(), log_level='info')

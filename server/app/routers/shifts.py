import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from ..database import (
    as_valid_date,
    execute,
    fetch_all,
    fetch_one,
    map_bill,
    map_product,
    map_refill,
    map_shift,
    next_id,
    normalize_bill_items,
    serialize,
    to_iso,
    to_number,
    utcnow,
)
from ..excel_report import generate_shift_excel_report
from ..mail import (
    build_shift_report_email,
    friendly_date,
    get_payment_breakdown,
    get_remaining_stock_summary,
    get_shift_items_summary,
    send_shift_report_email,
    shift_display,
)

router = APIRouter()


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _start_of_local_day(moment: datetime) -> datetime:
    local = moment.astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get('/api/shifts/active')
async def active_shift(user: str = Query(default='')):
    row = await fetch_one(
        'SELECT * FROM shifts WHERE username = $1 AND active = true ORDER BY shift_start DESC NULLS LAST LIMIT 1',
        user.strip(),
    )
    if row:
        return {'active': True, **serialize(map_shift(row))}
    return {'active': False}


@router.post('/api/shifts/start', status_code=201)
async def start_shift(payload: dict = Body(default_factory=dict)):
    user = str(payload.get('user') or '').strip()
    auto_shift_end = to_iso(utcnow())

    active_rows = await fetch_all("SELECT * FROM shifts WHERE username = $1 AND active = true", user)
    await execute(
        "UPDATE shifts SET active = false, shift_end = $2 WHERE username = $1 AND active = true",
        user,
        auto_shift_end,
    )
    active_ids = [row['id'] for row in active_rows]
    if active_ids:
        await execute(
            """
            UPDATE login_logs SET logout_time = $1, status = 'Completed'
            WHERE shift_session_id = ANY($2::bigint[]) AND logout_time IS NULL
            """,
            auto_shift_end,
            active_ids,
        )

    shift_row = await fetch_one(
        """
        INSERT INTO shifts (id, username, role, shift_start, shift_end, active, recipient_email, login_log_cleared, created_at, extra)
        VALUES ($1, $2, $3, $4, NULL, true, NULL, false, $5, '{}'::jsonb)
        RETURNING *
        """,
        await next_id('shifts'),
        user,
        payload.get('role') or 'Staff',
        payload.get('shiftStart') or to_iso(utcnow()),
        utcnow(),
    )
    shift = map_shift(shift_row)

    await execute(
        """
        INSERT INTO login_logs (id, username, user_name, role, login_time, logout_time, shift_session_id, status, created_at, extra)
        VALUES ($1, $2, $3, $4, $5, NULL, $6, 'Active', $7, '{}'::jsonb)
        """,
        await next_id('login_logs'),
        user,
        user,
        shift['role'],
        shift['shiftStart'],
        shift['id'],
        utcnow(),
    )

    return {'success': True, 'active': True, 'sessionId': shift['id'], **serialize(shift)}


@router.post('/api/shifts/end')
async def end_shift(payload: dict = Body(default_factory=dict)):
    user = str(payload.get('user') or '').strip()
    role = str(payload.get('role') or 'Staff').strip()
    recipient_email = str(
        payload.get('recipientEmail')
        or os.environ.get('SHIFT_REPORT_EMAIL')
        or os.environ.get('MAIL_USER')
        or os.environ.get('SMTP_FROM')
        or os.environ.get('SMTP_USER')
        or ''
    ).strip()

    if not user:
        raise HTTPException(status_code=400, detail='Shift user is required')

    if payload.get('shiftStart'):
        parsed_start = _parse_datetime(payload.get('shiftStart'))
        if parsed_start is None:
            raise HTTPException(status_code=400, detail='Valid shift start time is required')
        shift_start = parsed_start
    else:
        shift_start = utcnow()

    shift_end = utcnow()
    session_id = payload.get('sessionId')

    if session_id:
        await execute(
            'UPDATE shifts SET active = false, shift_end = $2, recipient_email = $3 WHERE id = $1',
            to_number(session_id),
            to_iso(shift_end),
            recipient_email,
        )
        await execute(
            "UPDATE login_logs SET logout_time = $2, status = 'Completed' WHERE shift_session_id = $1",
            to_number(session_id),
            to_iso(shift_end),
        )
    else:
        await execute(
            'UPDATE shifts SET active = false, shift_end = $2, recipient_email = $3 WHERE username = $1 AND active = true',
            user,
            to_iso(shift_end),
            recipient_email,
        )
        await execute(
            "UPDATE login_logs SET logout_time = $2, status = 'Completed' WHERE username = $1 AND logout_time IS NULL",
            user,
            to_iso(shift_end),
        )

    settings_row = await fetch_one("SELECT * FROM settings WHERE key = 'main'")
    shop_name = (settings_row['shop'] if settings_row else None) or 'Sri Nikil Tradings'
    normalized_role = role.lower()

    effective_shift_start = shift_start
    if normalized_role == 'admin':
        start_of_day = _start_of_local_day(shift_end)
        last_report = await fetch_one(
            "SELECT * FROM shift_reports WHERE lower(role) = 'admin' ORDER BY shift_end DESC NULLS LAST LIMIT 1"
        )

        if last_report and last_report['shift_end']:
            effective_shift_start = as_valid_date(last_report['shift_end'])
            if effective_shift_start < start_of_day:
                effective_shift_start = start_of_day
        else:
            effective_shift_start = start_of_day

    if normalized_role == 'admin':
        bill_rows = await fetch_all(
            'SELECT * FROM bills WHERE date >= $1 AND date <= $2 ORDER BY date ASC NULLS FIRST',
            effective_shift_start,
            shift_end,
        )
        refill_start = effective_shift_start
    else:
        bill_rows = await fetch_all(
            'SELECT * FROM bills WHERE lower(by_user) = lower($1) AND date >= $2 AND date <= $3 ORDER BY date ASC NULLS FIRST',
            user,
            shift_start,
            shift_end,
        )
        refill_start = shift_start

    bills = [map_bill(row) for row in bill_rows]
    product_rows = [map_product(row) for row in await fetch_all('SELECT * FROM products ORDER BY name ASC NULLS LAST')]
    refill_rows = [
        map_refill(row)
        for row in await fetch_all(
            'SELECT * FROM refills WHERE date >= $1 AND date <= $2 ORDER BY date ASC NULLS FIRST',
            refill_start,
            shift_end,
        )
    ]

    payment_breakdown = get_payment_breakdown(bills)
    item_summary = get_shift_items_summary(bills)

    sold_by_product_id: dict = {}
    for bill in bills:
        for item in normalize_bill_items(bill.get('items')):
            product_id = to_number(item.get('id'))
            qty = to_number(item.get('qty'))
            if not product_id or qty <= 0:
                continue
            sold_by_product_id[product_id] = to_number(sold_by_product_id.get(product_id, 0)) + qty

    refill_by_product_name: dict = {}
    for refill in refill_rows:
        product_name = str(refill.get('product') or '').strip()
        qty = to_number(refill.get('qty'))
        if not product_name or qty <= 0:
            continue
        refill_by_product_name[product_name] = to_number(refill_by_product_name.get(product_name, 0)) + qty

    remaining_stock_summary = get_remaining_stock_summary(
        product_rows, sold_by_product_id, refill_by_product_name
    )
    total_shift_sales = sum(to_number(bill.get('grand')) for bill in bills)

    report = {
        'user': user,
        'role': role,
        'reportEmail': recipient_email or 'N/A',
        'shiftStart': to_iso(effective_shift_start),
        'shiftEnd': to_iso(shift_end),
        'shiftStartDisplay': shift_display(effective_shift_start),
        'shiftEndDisplay': shift_display(shift_end),
        'billsCount': len(bills),
        'totalItemsSold': item_summary['totalItemsSold'],
        'totalSalesAmount': total_shift_sales,
        'paymentBreakdown': payment_breakdown,
        'productsSold': item_summary['products'],
        'remainingStockSummary': remaining_stock_summary,
    }

    friendly = friendly_date(shift_end)
    subject = f'Shift Report - {shop_name} - {user} - {friendly}'

    email_status = 'skipped'
    email_error = None
    email_sent_at = None
    attachment_name = None
    attachment_count = 0

    if normalized_role == 'admin' and recipient_email:
        try:
            email_body = build_shift_report_email(
                report, shop_name, payment_breakdown, item_summary, remaining_stock_summary
            )
            excel_buffer = await run_in_threadpool(
                generate_shift_excel_report, report, bills, remaining_stock_summary
            )
            attachment_name = (
                f"Shift_Report_{re.sub(r'\s+', '_', shop_name)}_{friendly.replace('/', '-')}.xlsx"
            )
            attachment_count = 1
            await run_in_threadpool(
                send_shift_report_email,
                recipient_email,
                subject,
                email_body['text'],
                email_body['html'],
                [{'filename': attachment_name, 'content': excel_buffer}],
            )
            email_status = 'sent'
            email_sent_at = utcnow()
        except Exception as mail_error:
            email_status = 'failed'
            email_error = str(mail_error) or 'Email sending failed'
            print('Failed to send shift report mail:', mail_error)
    elif normalized_role != 'admin':
        email_status = 'skipped'
        email_error = 'Email not required for non-admin roles'
    else:
        email_error = 'Report recipient email is not configured'

    await execute(
        """
        INSERT INTO shift_reports (
            id, session_id, username, role, shift_start, shift_end, total_bills,
            total_items_sold, total_sales_amount, payment_breakdown, products_sold,
            remaining_stock_summary, report_email, report_subject, email_status,
            email_error, email_sent_at, attachment_name, attachment_count, status, created_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21)
        """,
        await next_id('shift_reports'),
        to_number(session_id) if session_id else None,
        user,
        role,
        effective_shift_start,
        shift_end,
        len(bills),
        item_summary['totalItemsSold'],
        total_shift_sales,
        payment_breakdown,
        item_summary['products'],
        remaining_stock_summary,
        recipient_email or None,
        subject,
        email_status,
        email_error,
        email_sent_at,
        attachment_name,
        attachment_count,
        'Completed',
        utcnow(),
    )

    await execute(
        """
        UPDATE products SET
            stock = GREATEST(COALESCE(stock, 0), 0),
            opening_stock = GREATEST(COALESCE(stock, 0), 0),
            sold = 0
        """
    )

    return {
        'success': True,
        'message': (
            'Shift closed and report sent successfully'
            if email_status == 'sent'
            else f'Shift closed but mail {email_status}'
        ),
        'emailedTo': recipient_email if email_status == 'sent' else None,
        'emailStatus': email_status,
        'emailError': email_error,
        'attachmentName': attachment_name,
        'attachmentCount': attachment_count,
        'shiftStart': to_iso(effective_shift_start),
        'shiftEnd': to_iso(shift_end),
        'billsCount': len(bills),
        'totalItemsSold': item_summary['totalItemsSold'],
        'totalSales': total_shift_sales,
        'paymentBreakdown': payment_breakdown,
        'remainingStockSummary': remaining_stock_summary['totals'],
        'promptNextShift': normalized_role != 'admin',
    }

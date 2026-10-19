import secrets
import smtplib
import time
from email.message import EmailMessage

from . import config
from .database import as_valid_date, normalize_bill_items, to_number


def escape_html(value) -> str:
    return (
        str(value if value is not None else '')
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#039;')
    )


def get_payment_breakdown(bills) -> dict:
    breakdown: dict = {}
    for bill in bills or []:
        method = bill.get('payment') or 'Unknown'
        breakdown[method] = breakdown.get(method, 0) + to_number(bill.get('grand'))
    return breakdown


def get_shift_items_summary(bills) -> dict:
    by_product: dict = {}
    total_items_sold = 0

    for bill in bills or []:
        for item in normalize_bill_items(bill.get('items')):
            key = item.get('id') or item.get('name')
            qty = to_number(item.get('qty'))
            if not key or qty <= 0:
                continue

            current = by_product.get(key) or {
                'id': item.get('id') or '',
                'name': item.get('name') or 'Product',
                'qty': 0,
                'amount': 0,
            }
            current['qty'] += qty
            current['amount'] += to_number(item.get('total'), to_number(item.get('price')) * qty)
            by_product[key] = current
            total_items_sold += qty

    products = sorted(by_product.values(), key=lambda item: -item['qty'])
    return {'totalItemsSold': total_items_sold, 'products': products}


def get_remaining_stock_summary(product_rows, sold_by_product_id: dict, refill_by_product_name: dict) -> dict:
    products = []
    for product in product_rows or []:
        product_name = str(product.get('name') or '').strip()
        sold_in_shift = to_number(sold_by_product_id.get(to_number(product.get('id')), 0))
        refilled_in_shift = to_number(refill_by_product_name.get(product_name, 0))
        current_stock = to_number(product.get('stock'))
        estimated_opening_stock = current_stock - refilled_in_shift + sold_in_shift

        if current_stock == 0:
            status = 'Out of Stock'
        elif current_stock <= 5:
            status = 'Low Stock'
        else:
            status = 'Healthy'

        products.append({
            'id': to_number(product.get('id')),
            'name': product.get('name'),
            'category': product.get('cat') or '',
            'unit': product.get('unit') or '',
            'price': to_number(product.get('price')),
            'estimatedOpeningStock': estimated_opening_stock,
            'soldInShift': sold_in_shift,
            'refilledInShift': refilled_in_shift,
            'currentStock': current_stock,
            'status': status,
        })

    return {
        'totals': {
            'totalProducts': len(products),
            'healthyCount': sum(1 for item in products if item['status'] == 'Healthy'),
            'lowStockCount': sum(1 for item in products if item['status'] == 'Low Stock'),
            'outOfStockCount': sum(1 for item in products if item['status'] == 'Out of Stock'),
        },
        'products': products,
    }


def build_shift_report_email(report, shop_name, payment_breakdown, item_summary, remaining_stock_summary):
    payment_rows = ''.join(
        f'<tr><td>{escape_html(method)}</td><td style="text-align:right">Rs. {to_number(amount):.2f}</td></tr>'
        for method, amount in (payment_breakdown or {}).items()
    )
    item_rows = ''.join(
        f'<tr><td>{escape_html(item.get("name"))}</td>'
        f'<td style="text-align:right">{item.get("qty")}</td>'
        f'<td style="text-align:right">Rs. {to_number(item.get("amount")):.2f}</td></tr>'
        for item in (item_summary or {}).get('products', [])
    )

    stock_totals = (remaining_stock_summary or {}).get('totals') or {}
    stock_rows_parts = []
    for item in (remaining_stock_summary or {}).get('products', []):
        quantity_sold = to_number(item.get('soldInShift'))
        price = to_number(item.get('price'))
        stock_rows_parts.append(f'''
        <tr>
          <td>{escape_html(item.get('name'))}</td>
          <td style="text-align:right">{quantity_sold}</td>
          <td style="text-align:right">Rs. {price:.2f}</td>
          <td style="text-align:right">Rs. {quantity_sold * price:.2f}</td>
          <td style="text-align:right">{to_number(item.get('estimatedOpeningStock'))}</td>
          <td style="text-align:right">{to_number(item.get('refilledInShift'))}</td>
          <td style="text-align:right">{quantity_sold}</td>
          <td style="text-align:right">{to_number(item.get('currentStock'))}</td>
        </tr>
      ''')
    stock_rows = ''.join(stock_rows_parts)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body>
    <div style="font-family:Arial,sans-serif;color:#111827;line-height:1.45">
      <h2 style="margin:0 0 8px">{escape_html(shop_name)} - Shift Report</h2>
      <p style="margin:0 0 16px;color:#4b5563">Generated automatically when shift ended. Excel attachment includes the full 4 worksheet report.</p>
      <table cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;max-width:720px">
        <tr><td><b>User</b></td><td>{escape_html(report.get('user'))} ({escape_html(report.get('role'))})</td></tr>
        <tr><td><b>Shift Start</b></td><td>{escape_html(report.get('shiftStartDisplay'))}</td></tr>
        <tr><td><b>Shift End</b></td><td>{escape_html(report.get('shiftEndDisplay'))}</td></tr>
        <tr><td><b>Total Bills</b></td><td>{report.get('billsCount')}</td></tr>
        <tr><td><b>Total Items Sold</b></td><td>{report.get('totalItemsSold')}</td></tr>
        <tr><td><b>Total Sales</b></td><td>Rs. {to_number(report.get('totalSalesAmount')):.2f}</td></tr>
        <tr><td><b>Healthy Products</b></td><td>{to_number(stock_totals.get('healthyCount'))}</td></tr>
        <tr><td><b>Low Stock Products</b></td><td>{to_number(stock_totals.get('lowStockCount'))}</td></tr>
        <tr><td><b>Out of Stock Products</b></td><td>{to_number(stock_totals.get('outOfStockCount'))}</td></tr>
      </table>
      <h3>Payment Summary</h3>
      <table cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;max-width:720px;border:1px solid #e5e7eb">
        <thead><tr style="background:#f3f4f6"><th align="left">Method</th><th align="right">Amount</th></tr></thead>
        <tbody>{payment_rows or '<tr><td colspan="2">No payments in this shift</td></tr>'}</tbody>
      </table>
      <h3>Products Sold</h3>
      <table cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;max-width:720px;border:1px solid #e5e7eb">
        <thead><tr style="background:#f3f4f6"><th align="left">Product</th><th align="right">Qty</th><th align="right">Amount</th></tr></thead>
        <tbody>{item_rows or '<tr><td colspan="3">No products sold in this shift</td></tr>'}</tbody>
      </table>
      <h3>Remaining Stock</h3>
      <table cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;max-width:1120px;border:1px solid #e5e7eb">
        <thead>
          <tr style="background:#f3f4f6">
            <th align="left">Name of the Product</th>
            <th align="right">Quantity Sold</th>
            <th align="right">Price Per Product</th>
            <th align="right">Total Sale Value Per Product</th>
            <th align="right">Opening Stock</th>
            <th align="right">Receipts</th>
            <th align="right">Sales</th>
            <th align="right">Closing Stock</th>
          </tr>
        </thead>
        <tbody>{stock_rows or '<tr><td colspan="8">No stock details available</td></tr>'}</tbody>
      </table>
    </div>
</body>
</html>
  '''

    payment_lines = (
        [f'- {method}: Rs. {to_number(amount):.2f}' for method, amount in (payment_breakdown or {}).items()]
        if (payment_breakdown or {})
        else ['- No payments in this shift']
    )
    item_lines = (
        [
            f'- {item.get("name")}: {item.get("qty")} qty, Rs. {to_number(item.get("amount")):.2f}'
            for item in item_summary.get('products', [])
        ]
        if item_summary.get('products')
        else ['- No products sold in this shift']
    )

    stock_products = (remaining_stock_summary or {}).get('products') or []
    if stock_products:
        stock_lines = []
        for item in stock_products:
            quantity_sold = to_number(item.get('soldInShift'))
            price = to_number(item.get('price'))
            stock_lines.append(
                f'- {item.get("name")}: qty sold {quantity_sold}, price Rs. {price:.2f}, '
                f'total Rs. {quantity_sold * price:.2f}, opening {to_number(item.get("estimatedOpeningStock"))}, '
                f'receipts {to_number(item.get("refilledInShift"))}, sales {quantity_sold}, '
                f'closing {to_number(item.get("currentStock"))}'
            )
    else:
        stock_lines = ['- No stock details available']

    text = '\n'.join([
        f'{shop_name} - Shift Report',
        f'User: {report.get("user")} ({report.get("role")})',
        f'Shift Start: {report.get("shiftStartDisplay")}',
        f'Shift End: {report.get("shiftEndDisplay")}',
        f'Total Bills: {report.get("billsCount")}',
        f'Total Items Sold: {report.get("totalItemsSold")}',
        f'Total Sales: Rs. {to_number(report.get("totalSalesAmount")):.2f}',
        f'Healthy Products: {to_number(stock_totals.get("healthyCount"))}',
        f'Low Stock Products: {to_number(stock_totals.get("lowStockCount"))}',
        f'Out of Stock Products: {to_number(stock_totals.get("outOfStockCount"))}',
        '',
        'Payment Summary:',
        *payment_lines,
        '',
        'Products Sold:',
        *item_lines,
        '',
        'Remaining Stock:',
        *stock_lines,
        '',
        'Excel attachment includes: Shift Summary, Payment Breakdown, Remaining Stock, Sales Details.',
    ])

    return {'text': text, 'html': html}


def get_smtp_config() -> dict:
    config.refresh_runtime_mail_env()

    import os

    host = str(os.environ.get('SMTP_HOST') or '').strip()
    try:
        port = int(os.environ.get('SMTP_PORT') or 587)
    except ValueError:
        port = 587
    user = str(
        os.environ.get('SMTP_USER')
        or os.environ.get('SMTP_SENDER_EMAIL')
        or os.environ.get('MAIL_USER')
        or ''
    ).strip()
    password = str(
        os.environ.get('SMTP_PASS')
        or os.environ.get('SMTP_PASSWORD')
        or os.environ.get('MAIL_APP_PASSWORD')
        or os.environ.get('MAIL_PASSWORD')
        or ''
    ).strip()
    raw_from = str(os.environ.get('SMTP_FROM') or os.environ.get('MAIL_FROM') or user).strip()
    sender = raw_from if '<' in raw_from else f'"Sri Nikil ERP" <{raw_from}>'
    secure = str(os.environ.get('SMTP_SECURE') or '').strip().lower() == 'true' or port == 465

    if not host or not port or not user or not password or not sender:
        raise RuntimeError(
            'SMTP configuration is incomplete. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS and SMTP_FROM in .env.development.'
        )

    return {'host': host, 'port': port, 'secure': secure, 'from': sender, 'user': user, 'password': password}


def send_shift_report_email(recipient, subject, text, html, attachments):
    smtp = get_smtp_config()
    message = EmailMessage()
    message['From'] = smtp['from']
    message['Reply-To'] = smtp['from']
    message['To'] = recipient
    message['Subject'] = subject
    message_id_domain = smtp['host'][5:] if smtp['host'].startswith('smtp.') else smtp['host']
    message['Message-ID'] = f'<{int(time.time() * 1000)}-{secrets.token_hex(4)}@{message_id_domain}>'
    message.set_content(text)
    message.add_alternative(html, subtype='html')

    for attachment in attachments or []:
        message.add_attachment(
            attachment['content'],
            maintype='application',
            subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            filename=attachment['filename'],
        )

    if smtp['secure']:
        with smtplib.SMTP_SSL(smtp['host'], smtp['port'], timeout=60) as server:
            server.login(smtp['user'], smtp['password'])
            server.send_message(message)
    else:
        with smtplib.SMTP(smtp['host'], smtp['port'], timeout=60) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp['user'], smtp['password'])
            server.send_message(message)

    return True


def shift_display(value) -> str:
    return as_valid_date(value).astimezone().strftime('%d/%m/%Y, %H:%M:%S')


def friendly_date(value) -> str:
    return as_valid_date(value).astimezone().strftime('%d/%m/%Y')

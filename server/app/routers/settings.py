from fastapi import APIRouter, Body

from ..database import execute, fetch_one, map_settings, to_number

router = APIRouter()


@router.get('/api/settings')
async def get_settings():
    return map_settings(await fetch_one("SELECT * FROM settings WHERE key = 'main'"))


@router.put('/api/settings')
async def update_settings(payload: dict = Body(default_factory=dict)):
    settings = {
        'gst': to_number(payload.get('gst')),
        'shop': payload.get('shop') or '',
        'addr': payload.get('addr') or '',
        'gstin': payload.get('gstin') or '',
        'fssai': payload.get('fssai') or '',
        'phone': payload.get('phone') or '',
    }
    await execute(
        """
        INSERT INTO settings (key, gst, shop, addr, gstin, fssai, phone)
        VALUES ('main', $1, $2, $3, $4, $5, $6)
        ON CONFLICT (key) DO UPDATE SET
            gst = EXCLUDED.gst, shop = EXCLUDED.shop, addr = EXCLUDED.addr,
            gstin = EXCLUDED.gstin, fssai = EXCLUDED.fssai, phone = EXCLUDED.phone
        """,
        settings['gst'],
        settings['shop'],
        settings['addr'],
        settings['gstin'],
        settings['fssai'],
        settings['phone'],
    )
    return {'success': True, **settings}

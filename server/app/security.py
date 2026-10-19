import hashlib
import hmac
import secrets

SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SCRYPT_MAXMEM = 128 * 1024 * 1024


def hash_password(password) -> str:
    plain = str(password or '')
    salt = secrets.token_hex(16)
    derived = hashlib.scrypt(
        plain.encode('utf-8'),
        salt=salt.encode('utf-8'),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return f'scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt}${derived.hex()}'


def verify_password(password, stored_password) -> bool:
    plain = str(password or '')
    stored = str(stored_password or '')

    if not stored.startswith('scrypt$'):
        return hmac.compare_digest(plain, stored)

    parts = stored.split('$')
    if len(parts) != 6:
        return False
    prefix, n_str, r_str, p_str, salt, hash_hex = parts
    if prefix != 'scrypt' or not salt or not hash_hex:
        return False

    try:
        expected = bytes.fromhex(hash_hex)
        derived = hashlib.scrypt(
            plain.encode('utf-8'),
            salt=salt.encode('utf-8'),
            n=int(n_str or SCRYPT_N),
            r=int(r_str or SCRYPT_R),
            p=int(p_str or SCRYPT_P),
            dklen=len(expected),
            maxmem=SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(derived, expected)

DEFAULT_SETTINGS = {
    'gst': 5,
    'shop': 'Sri Nikil Tradings',
    'addr': '058/1, Bhavani Main Road, Opp. Central Warehouse, Erode - 638004',
    'gstin': '33AMCPD1118L1ZK',
    'fssai': '12424007000946',
    'phone': '94875 81302, 0424 2901803',
}

USER_ROLES = {
    'ADMIN': 'Admin',
    'MANAGER': 'Manager',
    'STAFF': 'Staff',
}

DEFAULT_ACCOUNTS = (
    {
        'user': 'admin',
        'password_env': 'DEFAULT_ADMIN_PASSWORD',
        'fallback_password': 'admin12345',
        'role': USER_ROLES['ADMIN'],
    },
    {
        'user': 'manager',
        'password_env': 'DEFAULT_MANAGER_PASSWORD',
        'fallback_password': 'manager12345',
        'role': USER_ROLES['MANAGER'],
    },
)

BILL_RETENTION_YEARS = 4

"""Credential field identity is authoritative even for short opaque values."""
SECRET_FIELDS = frozenset({
    'password', 'passwd', 'token', 'api_key', 'apikey', 'authorization',
    'proxy_authorization', 'access_token', 'refresh_token', 'client_secret',
    'secret', 'private_key',
})


def is_secret_field(key: str) -> bool:
    return str(key).strip().lower().replace('-', '_') in SECRET_FIELDS

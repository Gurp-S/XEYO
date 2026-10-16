"""One verified TLS context per HTTP client, shared by its proxy transports."""


def create_client(httpx, timeout):
    # Use HTTPX's public factory: SSL_CERT_FILE / SSL_CERT_DIR and certifi keep
    # exactly the library's normal precedence and certificate verification.
    context = httpx.create_ssl_context()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        verify=context,
    )

"""Transport categories across optional httpx/httpcore implementations.

Use the inheritance contract, not only the concrete leaf name. ReadError and
WriteError are NetworkError subclasses, including application-defined variants.
Local protocol/configuration errors are not transient network failures.
"""


def transport_failure_kind(exc: BaseException) -> str | None:
    bases = {base.__name__ for base in type(exc).__mro__
             if base.__module__.split('.')[0] in {'httpx', 'httpcore'}}
    if bases & {'TimeoutException', 'PoolTimeout', 'ConnectTimeout', 'ReadTimeout', 'WriteTimeout'}:
        return 'timeout'
    if bases & {'NetworkError', 'ConnectError', 'ReadError', 'WriteError', 'CloseError', 'RemoteProtocolError', 'ProxyError'}:
        return 'network'
    # Preserve the abstract request-error contract, but not configuration leaves
    # such as UnsupportedProtocol, LocalProtocolError or TooManyRedirects.
    if type(exc).__name__ == 'RequestError' and 'RequestError' in bases:
        return 'network'
    return None

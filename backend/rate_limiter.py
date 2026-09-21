import ipaddress

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _is_internal_hop(value: str) -> bool:
    """True for our own proxies (private/loopback) and for anything unparseable."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return True
    return ip.is_private or ip.is_loopback or ip.is_reserved


def client_ip(request: Request) -> str:
    # Behind nginx/ngrok, request.client.host is the proxy for every user, so all
    # clients would share one bucket. Every hop appends itself to X-Forwarded-For
    # (nginx does it with $proxy_add_x_forwarded_for, see frontend/nginx.conf), so
    # the entries our own proxies added are the last ones. Everything a client
    # sends itself is forgeable, so we walk the list from the right and take the
    # first address that is not one of our internal hops; entries before it are
    # client-controlled and ignored.
    forwarded_for = request.headers.get("x-forwarded-for", "")
    for entry in reversed(forwarded_for.split(",")):
        candidate = entry.strip()
        if candidate and not _is_internal_hop(candidate):
            return candidate
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip)

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeUrlError(ValueError):
    pass


def ensure_public_source_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError("Only http and https URLs are supported")

    hostname = parsed.hostname
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UnsafeUrlError("URL host could not be resolved") from exc
        addresses = [ipaddress.ip_address(result[4][0]) for result in results]

    for address in addresses:
        if not address.is_global:
            raise UnsafeUrlError("Internal or private network URLs are not allowed")

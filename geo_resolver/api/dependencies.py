import threading
from geo_resolver import GeoResolver

_resolver: GeoResolver | None = None
_lock = threading.Lock()


def get_resolver() -> GeoResolver:
    global _resolver
    if _resolver is None:
        with _lock:
            if _resolver is None:
                _resolver = GeoResolver()
    return _resolver


def close_resolver() -> None:
    """Close and discard the singleton GeoResolver, releasing DB connections."""
    global _resolver
    with _lock:
        if _resolver is not None:
            _resolver.close()
            _resolver = None

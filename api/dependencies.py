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

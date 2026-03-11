from geo_resolver import GeoResolver

_resolver: GeoResolver | None = None


def get_resolver() -> GeoResolver:
    global _resolver
    if _resolver is None:
        _resolver = GeoResolver()
    return _resolver

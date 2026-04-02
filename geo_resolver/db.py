import logging
import os
import duckdb
from shapely import wkb
from .models import Place, Feature

logger = logging.getLogger(__name__)

_VALID_FEATURE_TABLES = frozenset({"land_features", "water_features", "land_use_features"})
_VALID_COLUMNS = frozenset({"class", "subtype", "category"})


class PlaceDB:
    """Read-only interface to the Overture Maps DuckDB databases.

    Manages connections to three databases: divisions, features, and places.
    """

    def __init__(self, data_dir: str):
        """Open database connections from *data_dir*."""
        self.data_dir = data_dir

        db_path = os.path.join(data_dir, "divisions.duckdb")
        if not os.path.exists(db_path):
            raise FileNotFoundError(
                f"Database not found at {db_path}. "
                "Run: geo-resolve download-data && geo-resolve build-db\n"
                "Or set GEO_RESOLVER_DATA_DIR to the correct data directory."
            )
        self.con = duckdb.connect(db_path, read_only=True)
        self.con.execute("INSTALL spatial; LOAD spatial;")

        features_path = os.path.join(data_dir, "features.duckdb")
        self.features_con = None
        if os.path.exists(features_path):
            self.features_con = duckdb.connect(features_path, read_only=True)
            self.features_con.execute("INSTALL spatial; LOAD spatial;")
            logger.info("Loaded features database")

        places_path = os.path.join(data_dir, "places.duckdb")
        self.places_con = None
        if os.path.exists(places_path):
            self.places_con = duckdb.connect(places_path, read_only=True)
            self.places_con.execute("INSTALL spatial; LOAD spatial;")
            logger.info("Loaded places database")

    def _resolve_context(self, context: str) -> tuple[str | None, str | None]:
        row = self.con.execute("""
            SELECT subtype, country, region
            FROM divisions
            WHERE (name = $ctx OR name_en = $ctx)
            AND subtype IN ('country', 'region')
            ORDER BY CASE subtype WHEN 'region' THEN 0 ELSE 1 END
            LIMIT 1
        """, {"ctx": context}).fetchone()

        if row is None:
            return None, None

        subtype, country, region = row
        if subtype == "country":
            return country, None
        return country, region


    def _resolve_context_geom(self, context: str) -> bytes | None:
        """Resolve a context string to a WKB geometry for spatial filtering.

        Looks up the context in the divisions table, retrieves the
        corresponding area geometry, and returns its WKB bytes.
        Results are cached for the lifetime of this PlaceDB instance.
        """
        if not hasattr(self, "_context_geom_cache"):
            self._context_geom_cache: dict[str, bytes | None] = {}
        if context in self._context_geom_cache:
            return self._context_geom_cache[context]

        row = self.con.execute("""
            SELECT a.geom_wkb
            FROM divisions d
            JOIN division_areas a ON a.division_id = d.id
            WHERE (d.name = $ctx OR d.name_en = $ctx)
            ORDER BY CASE d.subtype
                WHEN 'locality' THEN 0 WHEN 'localadmin' THEN 1
                WHEN 'county' THEN 2 WHEN 'region' THEN 3
                WHEN 'country' THEN 4 ELSE 5 END,
                d.prominence DESC NULLS LAST
            LIMIT 1
        """, {"ctx": context}).fetchone()

        result = bytes(row[0]) if row and row[0] else None
        self._context_geom_cache[context] = result
        return result

    def _search_divisions(
        self,
        name: str,
        place_type: str | None,
        context: str | None,
        limit: int,
        use_ilike: bool,
    ) -> list[tuple]:
        """Run a division search query, either exact-match or ILIKE."""
        if use_ilike:
            name_cond = "(name ILIKE $name_pattern OR name_en ILIKE $name_pattern)"
        else:
            name_cond = "(name = $exact_name OR name_en = $exact_name)"

        conditions = [name_cond]
        params: dict[str, object] = {"exact_name": name, "limit": limit}
        if use_ilike:
            params["name_pattern"] = f"%{name}%"

        if place_type:
            conditions.append("subtype = $place_type")
            params["place_type"] = place_type

        if context:
            ctx_country, ctx_region = self._resolve_context(context)
            if ctx_country:
                conditions.append("country = $ctx_country")
                params["ctx_country"] = ctx_country
            if ctx_region:
                conditions.append("region = $ctx_region")
                params["ctx_region"] = ctx_region
            if not ctx_country and not ctx_region:
                conditions.append("(country ILIKE $ctx OR region ILIKE $ctx)")
                params["ctx"] = f"%{context}%"

        where = " AND ".join(conditions)

        query = f"""
            SELECT id, COALESCE(name_en, name) as display_name, subtype, country, region,
                   population, prominence
            FROM divisions
            WHERE {where}
            ORDER BY
                CASE WHEN name = $exact_name OR name_en = $exact_name THEN 0
                     WHEN name ILIKE $exact_name OR name_en ILIKE $exact_name THEN 1
                     ELSE 2 END,
                CASE subtype
                    WHEN 'country' THEN 0 WHEN 'region' THEN 1
                    WHEN 'county' THEN 2 WHEN 'localadmin' THEN 3
                    WHEN 'locality' THEN 4 WHEN 'borough' THEN 5
                    WHEN 'neighborhood' THEN 6 ELSE 7 END,
                prominence DESC NULLS LAST,
                population DESC NULLS LAST,
                LENGTH(COALESCE(name_en, name)) ASC
            LIMIT $limit
        """
        return self.con.execute(query, params).fetchall()

    def search_places(
        self,
        name: str,
        place_type: str | None = None,
        context: str | None = None,
        limit: int = 5,
    ) -> list[Place]:
        """Search administrative divisions by name, with optional type and context filters."""
        rows = self._search_divisions(name, place_type, context, limit, use_ilike=False)
        if not rows:
            rows = self._search_divisions(name, place_type, context, limit, use_ilike=True)
        if not rows:
            return []

        matched_ids = [r[0] for r in rows]
        geom_rows = self.con.execute("""
            SELECT division_id, geom_wkb
            FROM division_areas
            WHERE division_id = ANY($ids)
        """, {"ids": matched_ids}).fetchall()
        geom_map = {}
        for div_id, geom_wkb_data in geom_rows:
            if geom_wkb_data is not None:
                try:
                    geom_map[div_id] = wkb.loads(bytes(geom_wkb_data))
                except Exception:
                    logger.warning("Failed to parse WKB for division %s", div_id, exc_info=True)

        results = []
        for row in rows:
            geom = geom_map.get(row[0])
            centroid = None
            if geom is not None:
                c = geom.centroid
                centroid = (round(c.y, 4), round(c.x, 4))
            results.append(Place(
                id=row[0],
                name=row[1],
                subtype=row[2],
                country=row[3],
                region=row[4],
                geometry=geom,
                population=row[5],
                prominence=row[6],
                centroid=centroid,
            ))
        return results

    def _run_feature_query(
        self,
        table: str,
        class_column: str,
        name: str,
        class_value: str | None,
        limit: int,
        use_ilike: bool,
        context_geom_wkb: bytes | None = None,
    ) -> list[tuple]:
        """Run a feature search query, either exact-match or ILIKE."""
        if use_ilike:
            name_cond = "(name ILIKE $name_pattern OR name_en ILIKE $name_pattern)"
        else:
            name_cond = "(name = $exact_name OR name_en = $exact_name)"

        conditions = [name_cond]
        params: dict[str, object] = {"exact_name": name, "limit": limit}
        if use_ilike:
            params["name_pattern"] = f"%{name}%"

        if class_value:
            conditions.append(f"{class_column} = $class_value")
            params["class_value"] = class_value

        if context_geom_wkb:
            conditions.append(
                "ST_Intersects(ST_GeomFromWKB(geom_wkb), ST_GeomFromWKB($context_geom))"
            )
            params["context_geom"] = context_geom_wkb

        where = " AND ".join(conditions)

        # Add extra columns based on table
        if table == "land_features":
            extra_cols = ", wikidata, elevation"
        elif table in ("water_features", "land_use_features"):
            extra_cols = ", wikidata"
        else:
            extra_cols = ""

        query = f"""
            SELECT id, COALESCE(name_en, name) as display_name,
                   {class_column}, geom_wkb, geom_type{extra_cols}
            FROM {table}
            WHERE {where}
            ORDER BY
                CASE WHEN name = $exact_name OR name_en = $exact_name THEN 0
                     WHEN name ILIKE $exact_name OR name_en ILIKE $exact_name THEN 1
                     ELSE 2 END,
                CASE WHEN wikidata IS NOT NULL THEN 0 ELSE 1 END,
                LENGTH(COALESCE(name_en, name)) ASC
            LIMIT $limit
        """
        return self.features_con.execute(query, params).fetchall()

    def _search_feature_table(
        self,
        table: str,
        source: str,
        name: str,
        class_column: str = "class",
        class_value: str | None = None,
        context: str | None = None,
        limit: int = 5,
    ) -> list[Feature]:
        """Generic search across feature tables (land, water, land_use)."""
        if table not in _VALID_FEATURE_TABLES:
            raise ValueError(f"Invalid feature table: {table!r}")
        if class_column not in _VALID_COLUMNS:
            raise ValueError(f"Invalid column name: {class_column!r}")

        if self.features_con is None:
            return []

        context_geom = self._resolve_context_geom(context) if context else None

        rows = self._run_feature_query(table, class_column, name, class_value, limit, use_ilike=False, context_geom_wkb=context_geom)
        if not rows:
            rows = self._run_feature_query(table, class_column, name, class_value, limit, use_ilike=True, context_geom_wkb=context_geom)

        results = []
        for row in rows:
            geom = None
            if row[3] is not None:
                try:
                    geom = wkb.loads(bytes(row[3]))
                except Exception:
                    logger.warning("Failed to parse WKB for %s %s", source, row[0], exc_info=True)

            centroid = None
            if geom is not None:
                c = geom.centroid
                centroid = (round(c.y, 4), round(c.x, 4))

            # Extract extra columns based on table
            wikidata = None
            elevation = None
            if table == "land_features":
                wikidata = row[5] if len(row) > 5 else None
                elevation = row[6] if len(row) > 6 else None
            elif table in ("water_features", "land_use_features"):
                wikidata = row[5] if len(row) > 5 else None

            results.append(Feature(
                id=row[0],
                name=row[1],
                source=source,
                feature_class=row[2],
                geometry=geom,
                geom_type=row[4],
                wikidata=wikidata,
                elevation=elevation,
                centroid=centroid,
            ))
        return results

    def search_land_features(
        self, name: str, feature_class: str | None = None,
        context: str | None = None, limit: int = 5,
    ) -> list[Feature]:
        """Search natural land features (islands, mountains, peaks, etc.)."""
        return self._search_feature_table(
            "land_features", "land", name,
            class_column="class", class_value=feature_class,
            context=context, limit=limit,
        )

    def search_water_features(
        self, name: str, feature_class: str | None = None,
        context: str | None = None, limit: int = 5,
    ) -> list[Feature]:
        """Search water features (lakes, rivers, bays, etc.)."""
        return self._search_feature_table(
            "water_features", "water", name,
            class_column="class", class_value=feature_class,
            context=context, limit=limit,
        )

    def search_land_use(
        self, name: str, subtype: str | None = None,
        context: str | None = None, limit: int = 5,
    ) -> list[Feature]:
        """Search land-use areas (parks, protected areas, cemeteries, etc.)."""
        return self._search_feature_table(
            "land_use_features", "land_use", name,
            class_column="subtype", class_value=subtype,
            context=context, limit=limit,
        )

    def _run_pois_query(
        self,
        name: str,
        category: str | None,
        limit: int,
        use_ilike: bool,
        context: str | None = None,
    ) -> list[tuple]:
        """Run a POI search query, either exact-match or ILIKE."""
        if use_ilike:
            name_cond = "(name ILIKE $name_pattern OR name_en ILIKE $name_pattern)"
        else:
            name_cond = "(name = $exact_name OR name_en = $exact_name)"

        conditions = [name_cond]
        params: dict[str, object] = {"exact_name": name, "limit": limit}
        if use_ilike:
            params["name_pattern"] = f"%{name}%"

        if category:
            conditions.append("category = $category")
            params["category"] = category

        if context:
            conditions.append(
                "(country ILIKE $ctx OR region ILIKE $ctx OR locality ILIKE $ctx)"
            )
            params["ctx"] = f"%{context}%"

        where = " AND ".join(conditions)

        query = f"""
            SELECT id, COALESCE(name_en, name) as display_name,
                   category, geom_wkb, confidence, country, region, locality
            FROM places
            WHERE {where}
            ORDER BY
                CASE WHEN name = $exact_name OR name_en = $exact_name THEN 0
                     WHEN name ILIKE $exact_name OR name_en ILIKE $exact_name THEN 1
                     ELSE 2 END,
                confidence DESC NULLS LAST,
                LENGTH(COALESCE(name_en, name)) ASC
            LIMIT $limit
        """
        return self.places_con.execute(query, params).fetchall()

    def search_pois(
        self, name: str, category: str | None = None, limit: int = 5,
        context: str | None = None,
    ) -> list[Feature]:
        """Search POIs. Always returns is_point=True."""
        if self.places_con is None:
            return []

        rows = self._run_pois_query(name, category, limit, use_ilike=False, context=context)
        if not rows:
            rows = self._run_pois_query(name, category, limit, use_ilike=True, context=context)
        results = []
        for row in rows:
            geom = None
            if row[3] is not None:
                try:
                    geom = wkb.loads(bytes(row[3]))
                except Exception:
                    logger.warning("Failed to parse WKB for place %s", row[0], exc_info=True)

            centroid = None
            if geom is not None:
                c = geom.centroid
                centroid = (round(c.y, 4), round(c.x, 4))

            results.append(Feature(
                id=row[0],
                name=row[1],
                source="place",
                feature_class=row[2] or "unknown",
                geometry=geom,
                geom_type="Point",
                is_point=True,
                confidence=row[4],
                country=row[5],
                region=row[6],
                locality=row[7],
                centroid=centroid,
            ))
        return results

    def reverse_geocode(self, lat: float, lon: float) -> 'Place | None':
        """Return the smallest division containing the given point."""
        from shapely.geometry import Point as ShapelyPoint
        point_wkb = wkb.dumps(ShapelyPoint(lon, lat))
        row = self.con.execute("""
            SELECT d.id, COALESCE(d.name_en, d.name), d.subtype, d.country, d.region,
                   d.population, d.prominence
            FROM division_areas a
            JOIN divisions d ON d.id = a.division_id
            WHERE ST_Contains(ST_GeomFromWKB(a.geom_wkb), ST_GeomFromWKB($pt))
            ORDER BY CASE d.subtype
                WHEN 'neighborhood' THEN 0 WHEN 'borough' THEN 1
                WHEN 'locality' THEN 2 WHEN 'localadmin' THEN 3
                WHEN 'county' THEN 4 WHEN 'region' THEN 5
                WHEN 'country' THEN 6 ELSE 7 END
            LIMIT 1
        """, {"pt": point_wkb}).fetchone()
        if row is None:
            return None
        return Place(id=row[0], name=row[1], subtype=row[2], country=row[3],
                     region=row[4], geometry=None, population=row[5], prominence=row[6])

    def get_subtypes(self) -> list[str]:
        """Return all distinct division subtypes in the database."""
        rows = self.con.execute(
            "SELECT DISTINCT subtype FROM divisions ORDER BY subtype"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self):
        """Close all database connections."""
        self.con.close()
        if self.features_con:
            self.features_con.close()
        if self.places_con:
            self.places_con.close()

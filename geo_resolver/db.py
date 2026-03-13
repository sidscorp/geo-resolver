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
            SELECT id, COALESCE(name_en, name) as display_name, subtype, country, region
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
                    WHEN 'neighborhood' THEN 6 ELSE 7 END
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
            results.append(Place(
                id=row[0],
                name=row[1],
                subtype=row[2],
                country=row[3],
                region=row[4],
                geometry=geom_map.get(row[0]),
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

        where = " AND ".join(conditions)

        query = f"""
            SELECT id, COALESCE(name_en, name) as display_name,
                   {class_column}, geom_wkb, geom_type
            FROM {table}
            WHERE {where}
            ORDER BY
                CASE WHEN name = $exact_name OR name_en = $exact_name THEN 0
                     WHEN name ILIKE $exact_name OR name_en ILIKE $exact_name THEN 1
                     ELSE 2 END
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
        limit: int = 5,
    ) -> list[Feature]:
        """Generic search across feature tables (land, water, land_use)."""
        if table not in _VALID_FEATURE_TABLES:
            raise ValueError(f"Invalid feature table: {table!r}")
        if class_column not in _VALID_COLUMNS:
            raise ValueError(f"Invalid column name: {class_column!r}")

        if self.features_con is None:
            return []

        rows = self._run_feature_query(table, class_column, name, class_value, limit, use_ilike=False)
        if not rows:
            rows = self._run_feature_query(table, class_column, name, class_value, limit, use_ilike=True)

        results = []
        for row in rows:
            geom = None
            if row[3] is not None:
                try:
                    geom = wkb.loads(bytes(row[3]))
                except Exception:
                    logger.warning("Failed to parse WKB for %s %s", source, row[0], exc_info=True)

            results.append(Feature(
                id=row[0],
                name=row[1],
                source=source,
                feature_class=row[2],
                geometry=geom,
                geom_type=row[4],
            ))
        return results

    def search_land_features(
        self, name: str, feature_class: str | None = None, limit: int = 5
    ) -> list[Feature]:
        """Search natural land features (islands, mountains, peaks, etc.)."""
        return self._search_feature_table(
            "land_features", "land", name,
            class_column="class", class_value=feature_class, limit=limit,
        )

    def search_water_features(
        self, name: str, feature_class: str | None = None, limit: int = 5
    ) -> list[Feature]:
        """Search water features (lakes, rivers, bays, etc.)."""
        return self._search_feature_table(
            "water_features", "water", name,
            class_column="class", class_value=feature_class, limit=limit,
        )

    def search_land_use(
        self, name: str, subtype: str | None = None, limit: int = 5
    ) -> list[Feature]:
        """Search land-use areas (parks, protected areas, cemeteries, etc.)."""
        return self._search_feature_table(
            "land_use_features", "land_use", name,
            class_column="subtype", class_value=subtype, limit=limit,
        )

    def _run_pois_query(
        self,
        name: str,
        category: str | None,
        limit: int,
        use_ilike: bool,
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

        where = " AND ".join(conditions)

        query = f"""
            SELECT id, COALESCE(name_en, name) as display_name,
                   category, geom_wkb
            FROM places
            WHERE {where}
            ORDER BY
                CASE WHEN name = $exact_name OR name_en = $exact_name THEN 0
                     WHEN name ILIKE $exact_name OR name_en ILIKE $exact_name THEN 1
                     ELSE 2 END
            LIMIT $limit
        """
        return self.places_con.execute(query, params).fetchall()

    def search_pois(
        self, name: str, category: str | None = None, limit: int = 5
    ) -> list[Feature]:
        """Search POIs. Always returns is_point=True."""
        if self.places_con is None:
            return []

        rows = self._run_pois_query(name, category, limit, use_ilike=False)
        if not rows:
            rows = self._run_pois_query(name, category, limit, use_ilike=True)
        results = []
        for row in rows:
            geom = None
            if row[3] is not None:
                try:
                    geom = wkb.loads(bytes(row[3]))
                except Exception:
                    logger.warning("Failed to parse WKB for place %s", row[0], exc_info=True)

            results.append(Feature(
                id=row[0],
                name=row[1],
                source="place",
                feature_class=row[2] or "unknown",
                geometry=geom,
                geom_type="Point",
                is_point=True,
            ))
        return results

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

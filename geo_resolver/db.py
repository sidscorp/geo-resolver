import os
import duckdb
from shapely import wkb
from .models import Place

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


class PlaceDB:
    def __init__(self, data_dir: str = DEFAULT_DATA_DIR):
        self.data_dir = data_dir
        db_path = os.path.join(data_dir, "divisions.duckdb")
        if not os.path.exists(db_path):
            raise FileNotFoundError(
                f"Database not found at {db_path}. "
                "Run: python scripts/download_data.py && python scripts/build_db.py"
            )
        self.con = duckdb.connect(db_path, read_only=True)

    def _resolve_context(self, context: str) -> tuple[str | None, str | None]:
        row = self.con.execute("""
            SELECT subtype, country, region
            FROM divisions
            WHERE (name = $ctx OR name_en = $ctx)
            AND subtype IN ('country', 'region')
            ORDER BY CASE subtype WHEN 'country' THEN 0 ELSE 1 END
            LIMIT 1
        """, {"ctx": context}).fetchone()

        if row is None:
            return None, None

        subtype, country, region = row
        if subtype == "country":
            return country, None
        return country, region

    def search_places(
        self,
        name: str,
        place_type: str | None = None,
        context: str | None = None,
        limit: int = 5,
    ) -> list[Place]:
        # Step 1: find matching division IDs (fast, no geometry join)
        conditions = ["(name ILIKE $name_pattern OR name_en ILIKE $name_pattern)"]
        params = {"name_pattern": f"%{name}%"}

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
        params["exact_name"] = name

        id_query = f"""
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
        params["limit"] = limit

        rows = self.con.execute(id_query, params).fetchall()
        if not rows:
            return []

        # Step 2: fetch geometries only for matched IDs
        matched_ids = [r[0] for r in rows]
        placeholders = ", ".join(f"'{mid}'" for mid in matched_ids)
        geom_rows = self.con.execute(f"""
            SELECT division_id, geom_wkb
            FROM division_areas
            WHERE division_id IN ({placeholders})
        """).fetchall()
        geom_map = {}
        for div_id, geom_wkb_data in geom_rows:
            if geom_wkb_data is not None:
                try:
                    geom_map[div_id] = wkb.loads(bytes(geom_wkb_data))
                except Exception:
                    pass

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

    def get_subtypes(self) -> list[str]:
        rows = self.con.execute(
            "SELECT DISTINCT subtype FROM divisions ORDER BY subtype"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self):
        self.con.close()

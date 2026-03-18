"""Visual test harness — generates map PNGs for manual review.

Usage:
    .venv/bin/python tests/visual_test.py [--mode llm|direct|both] [--queries ...]
"""

import argparse
import json
import logging
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import contextily as cx
import geopandas as gpd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from geo_resolver import GeoResolver

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visual_results")

DEFAULT_QUERIES = [
    # Famous landmarks
    "Statue of Liberty",
    "Eiffel Tower",
    "Golden Gate Bridge",
    "White House",
    "Taj Mahal",
    "Colosseum",
    # Natural features
    "Rocky Mountains",
    "Lake Tahoe",
    "Grand Canyon",
    "Mount Everest",
    "Niagara Falls",
    # Cities/regions
    "San Francisco",
    "Manhattan",
    "Bavaria",
    "Tokyo",
    # Parks/land use
    "Central Park",
    "Yellowstone",
    "Arlington National Cemetery",
]

# Compound queries only work with LLM mode
COMPOUND_QUERIES = [
    "Northern California",
    "Manhattan excluding Central Park",
    "Within 50km of Paris",
]


def slugify(text):
    return text.lower().replace(" ", "_").replace(",", "")[:50]


def render_result(result, query, mode, output_dir):
    """Render a ResolverResult to a PNG with OSM basemap."""
    slug = slugify(query)
    os.makedirs(output_dir, exist_ok=True)

    gdf = gpd.GeoDataFrame(
        [{"geometry": result.geometry, "query": query}],
        crs="EPSG:4326",
    )
    gdf_web = gdf.to_crs(epsg=3857)

    fig, ax = plt.subplots(1, 1, figsize=(10, 8))
    gdf_web.plot(ax=ax, alpha=0.4, color="#3388ff", edgecolor="#3388ff", linewidth=2)

    try:
        cx.add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik)
    except Exception:
        logger.warning("Failed to fetch basemap tiles for %s", query)

    title = f"{query}\n{result.geometry.geom_type} | {result.area_km2:.1f} km²"
    ax.set_title(title, fontsize=12)
    ax.set_axis_off()

    png_path = os.path.join(output_dir, f"{slug}.png")
    fig.savefig(png_path, dpi=150, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)

    # Save metadata
    meta = {
        "query": query,
        "mode": mode,
        "geometry_type": result.geometry.geom_type,
        "area_km2": round(result.area_km2, 2),
        "bounds": list(result.bounds),
        "centroid": [round(result.geometry.centroid.y, 4), round(result.geometry.centroid.x, 4)],
        "steps": result.steps,
    }
    meta_path = os.path.join(output_dir, f"{slug}.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    return png_path


def run_tests(resolver, queries, mode):
    """Run all queries through a mode and generate PNGs."""
    output_dir = os.path.join(OUTPUT_DIR, mode)
    results = {}

    for query in queries:
        logger.info("\n=== [%s] %s ===", mode, query)
        try:
            result = resolver.resolve(query, mode=mode, verbose=True)
            png_path = render_result(result, query, mode, output_dir)
            logger.info("  OK: %s -> %s (%.1f km2)", query, result.geometry.geom_type, result.area_km2)
            results[query] = {"status": "ok", "png": png_path, "area_km2": result.area_km2}
        except Exception as e:
            logger.error("  FAIL: %s -> %s", query, e)
            results[query] = {"status": "error", "error": str(e)}

    # Summary
    summary_path = os.path.join(output_dir, "_summary.json")
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("\nSummary saved to %s", summary_path)

    ok = sum(1 for r in results.values() if r["status"] == "ok")
    fail = sum(1 for r in results.values() if r["status"] == "error")
    logger.info("Results: %d/%d passed, %d failed", ok, len(results), fail)


def main():
    parser = argparse.ArgumentParser(description="GeoResolver visual test harness")
    parser.add_argument("--mode", choices=["llm", "direct", "both"], default="both")
    parser.add_argument("--queries", nargs="+", help="Custom queries (overrides defaults)")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default=None)
    args = parser.parse_args()

    queries = args.queries or DEFAULT_QUERIES

    kwargs = {}
    if args.data_dir:
        kwargs["data_dir"] = args.data_dir
    model = args.model or os.environ.get("GEO_RESOLVER_MODEL")
    if model:
        kwargs["model"] = model
    if args.api_key:
        kwargs["api_key"] = args.api_key
    base_url = args.base_url or os.environ.get("GEO_RESOLVER_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url

    resolver = GeoResolver(**kwargs)

    if args.mode in ("direct", "both"):
        run_tests(resolver, queries, "direct")

    if args.mode in ("llm", "both"):
        llm_queries = queries + COMPOUND_QUERIES
        if not resolver.model:
            logger.warning("No model configured, skipping LLM mode")
        else:
            run_tests(resolver, llm_queries, "llm")

    resolver.close()


if __name__ == "__main__":
    main()

import json
import os
from openai import OpenAI
from dotenv import load_dotenv
from .db import PlaceDB
from .tools import ToolExecutor, TOOL_DEFINITIONS
from .models import ResolverResult

SYSTEM_PROMPT = """You are a geographic boundary resolver. Given a natural language description of a region, you decompose it into structured lookups and spatial operations to produce the precise boundary polygon.

RULES:
- NEVER generate or guess coordinates. All geometry comes from the search_places tool.
- Use search_places to find named places. Each result with a polygon returns a geometry_id.
- Use spatial operations (union, intersection, difference, buffer, directional_subset) to compose geometries.
- When a query refers to an informal region (e.g. "Bay Area", "SoCal"), decompose it into its constituent administrative units and union them.
- Use the context parameter for disambiguation (e.g. "Portland" with context "Oregon" vs "Maine").
- Use place_type to narrow searches: country, region, county, localadmin, locality, borough, neighborhood.
- When done, call finalize with the geometry_id of the final result.
- Be efficient: make parallel tool calls when possible, minimize unnecessary searches.
- If a search returns no results with geometry, try broader or alternative names, different place_type values, or omit filters.
- The database uses local/primary names (e.g. "Deutschland" not "Germany", "Bayern" not "Bavaria") but also has English names indexed. Both are searchable.
- You MUST always call finalize when you have found a suitable geometry. Even if the match isn't perfect, finalize with the best available result.
- If you truly cannot find any matching geometry after trying multiple search strategies, call finalize with whatever closest match you found.

EXAMPLES:
- "San Francisco Bay Area" → search 9 Bay Area counties individually, union them
- "Northern California" → search California (region), then directional_subset with "north"
- "Manhattan excluding Central Park" → search Manhattan, search Central Park, difference
- "Within 50km of Paris" → search Paris (locality), buffer 50km
- "Bavaria, Germany" → search Bavaria with context Germany
- "Greater London" → search London (locality or region), use the result with geometry"""

MAX_ITERATIONS = 20
DEFAULT_MODEL = "google/gemini-2.5-flash"


class GeoResolver:
    def __init__(self, data_dir: str = None, model: str = DEFAULT_MODEL):
        load_dotenv()
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        self.db = PlaceDB(data_dir)
        self.model = model
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def resolve(self, query: str, on_step=None) -> ResolverResult:
        executor = ToolExecutor(self.db)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        steps = []
        text_responses = 0

        for i in range(MAX_ITERATIONS):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            )
            choice = response.choices[0]

            if choice.message.tool_calls:
                text_responses = 0
                messages.append(choice.message)
                for tc in choice.message.tool_calls:
                    args = json.loads(tc.function.arguments)
                    step = {"tool": tc.function.name, "args": args}
                    steps.append(step)

                    result = executor.execute(tc.function.name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

                    if on_step is not None:
                        on_step(step)

                if executor.final_id:
                    break
            else:
                text_responses += 1
                if executor.final_id:
                    break
                if text_responses >= 2:
                    break
                messages.append(choice.message)
                messages.append({
                    "role": "user",
                    "content": (
                        "You must call finalize with a geometry_id. "
                        "If you found any place with geometry, finalize it. "
                        "If not, try searching with different terms or without filters."
                    ),
                })

        if executor.final_id is None:
            if executor.geometries:
                executor.final_id = list(executor.geometries.keys())[-1]
            else:
                raise RuntimeError(
                    f"Could not resolve '{query}' — no matching geometries found"
                )

        geometry = executor.geometries[executor.final_id]
        return ResolverResult(query=query, geometry=geometry, steps=steps)

    def close(self):
        self.db.close()

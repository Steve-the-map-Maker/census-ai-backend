"""Shared configuration for Gemini model and Census tools."""
from functools import lru_cache
from typing import Dict

from google.generativeai.types import FunctionDeclaration, Tool

from config import CENSUS_VARIABLE_MAP, DERIVED_METRICS_MAP, GEOGRAPHY_HIERARCHY

SYSTEM_INSTRUCTION = """You are a helpful assistant that provides US Census demographic data and visualizations. When users ask for maps, charts, time-series trends, or data visualization, call the appropriate Census tool to fetch the required data.

Use get_demographic_data for single-year views:
- For US-wide maps, use geography_level='state'.
- For state-specific maps, use geography_level='county' and include the state_name parameter.
- Comparative queries (e.g., \"Which states have more men than women?\", \"States with highest unemployment\") can rely on derived_metrics without listing raw variables.

Use get_demographic_time_series when users mention change over time, trends, history, or specific year ranges. Provide start_year and end_year (inclusive) and include the same geography parameters as single-year requests.

You can use EITHER variables OR derived_metrics (or both). geography_level is always required.

Available derived metrics: male_female_difference, unemployment_percentage, owner_occupied_percentage, poverty_percentage, bachelors_degree_percentage, housing_vacancy_rate.

When users ask comparative or time-series questions, determine the appropriate variable or derived metric and use it to create meaningful visualizations."""


def _build_get_demographic_data_tool() -> Tool:
    user_friendly_variable_names = list(CENSUS_VARIABLE_MAP.keys())
    geography_level_names = list(GEOGRAPHY_HIERARCHY.keys())
    derived_metric_names = list(DERIVED_METRICS_MAP.keys())

    get_demographic_data_declaration = FunctionDeclaration(
        name="get_demographic_data",
        description="""Fetch demographic data from the US Census Bureau to power maps and comparative snapshots.

Always select this tool when users request:
- Maps (e.g., \"map of population by state\", \"show me a map\")
- Single-year demographic views (population, income, age, housing, etc.)
- Comparative analyses (e.g., \"Which states have more men than women?\")

Guidance:
- Use geography_level='state' for US-wide maps.
- Use geography_level='county' with state_name for intra-state maps.
- Include derived_metrics for calculated comparisons.
- Always include state_name for county-level queries.
""",
        parameters={
            "type": "object",
            "properties": {
                "geography_level": {
                    "type": "string",
                    "description": "The target geographic level.",
                    "enum": geography_level_names,
                },
                "variables": {
                    "type": "array",
                    "description": "A list of user-friendly variable names to retrieve.",
                    "items": {
                        "type": "string",
                        "enum": user_friendly_variable_names,
                    },
                },
                "derived_metrics": {
                    "type": "array",
                    "description": "A list of derived/calculated metrics to compute for comparisons.",
                    "items": {
                        "type": "string",
                        "enum": derived_metric_names,
                    },
                },
                "state_name": {
                    "type": "string",
                    "description": "The name of the state (required for county-level queries).",
                },
                "county_name": {
                    "type": "string",
                    "description": "The name of the county.",
                },
                "place_name": {
                    "type": "string",
                    "description": "The name of the place (city, town, CDP).",
                },
                "tract_code": {
                    "type": "string",
                    "description": "The Census tract code.",
                },
                "block_group_code": {
                    "type": "string",
                    "description": "The block group code.",
                },
                "zip_code_tabulation_area": {
                    "type": "string",
                    "description": "The 5-digit ZCTA code.",
                },
            },
            "required": ["geography_level"],
        },
    )

    get_demographic_time_series_declaration = FunctionDeclaration(
        name="get_demographic_time_series",
        description="""Fetch demographic data across multiple ACS years to analyze changes over time for maps, charts, or narratives.

Use this tool whenever users mention trends, change over time, historical comparisons, or specific time windows.
Provide the same geography parameters as single-year requests plus start and end years.
""",
        parameters={
            "type": "object",
            "properties": {
                "geography_level": {
                    "type": "string",
                    "description": "The target geographic level (e.g., state, county).",
                    "enum": geography_level_names,
                },
                "variables": {
                    "type": "array",
                    "description": "User-friendly variable names to track over time (e.g., total_population).",
                    "items": {
                        "type": "string",
                        "enum": user_friendly_variable_names,
                    },
                },
                "derived_metrics": {
                    "type": "array",
                    "description": "Derived metrics to calculate for each year (e.g., unemployment_percentage).",
                    "items": {
                        "type": "string",
                        "enum": derived_metric_names,
                    },
                },
                "state_name": {
                    "type": "string",
                    "description": "State context. Required when geography_level needs a parent state (e.g., county).",
                },
                "county_name": {
                    "type": "string",
                    "description": "County name for nested geographies (e.g., tracts).",
                },
                "place_name": {
                    "type": "string",
                    "description": "Specific place name (city, town, CDP).",
                },
                "tract_code": {
                    "type": "string",
                    "description": "Census tract code, if applicable.",
                },
                "block_group_code": {
                    "type": "string",
                    "description": "Block group code, when necessary.",
                },
                "zip_code_tabulation_area": {
                    "type": "string",
                    "description": "ZCTA code, when requesting ZIP-level trends.",
                },
                "start_year": {
                    "type": "integer",
                    "description": "First ACS year to include (e.g., 2010).",
                },
                "end_year": {
                    "type": "integer",
                    "description": "Last ACS year to include (inclusive).",
                },
            },
            "required": ["geography_level", "start_year", "end_year"],
        },
    )

    return Tool(
        function_declarations=[
            get_demographic_data_declaration,
            get_demographic_time_series_declaration,
        ]
    )


CENSUS_TOOL = _build_get_demographic_data_tool()


@lru_cache(maxsize=1)
def get_variable_labels() -> Dict[str, str]:
    """Return a mapping of variable/metric identifiers to human-readable labels."""
    labels: Dict[str, str] = {}

    for key, census_code in CENSUS_VARIABLE_MAP.items():
        human_readable = key.replace("_", " ").title()
        labels[key] = human_readable
        labels[census_code] = human_readable

    for metric_key, metric_info in DERIVED_METRICS_MAP.items():
        labels[metric_key] = metric_info["name"]

    return labels.copy()


__all__ = ["SYSTEM_INSTRUCTION", "CENSUS_TOOL", "get_variable_labels"]

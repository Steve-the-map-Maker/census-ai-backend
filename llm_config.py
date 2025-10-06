"""Shared configuration for Gemini model and Census tools."""
from functools import lru_cache
from typing import Dict

from google.generativeai.types import FunctionDeclaration, Tool

from config import CENSUS_VARIABLE_MAP, DERIVED_METRICS_MAP, GEOGRAPHY_HIERARCHY

SYSTEM_INSTRUCTION = """You are a helpful assistant that provides US Census demographic data and visualizations. When users ask for maps, charts, or data visualization, always use the get_demographic_data tool to fetch the required data. 

For US-wide maps, use geography_level='state'. For state-specific maps, use geography_level='county' and include the state_name parameter.

For comparative queries (e.g., \"Which states have more men than women?\", \"States with highest unemployment\"), use derived_metrics without needing variables:
- male_female_difference: Calculates difference between male and female population
- unemployment_percentage: Calculates unemployment rate as a percentage  
- owner_occupied_percentage: Calculates owner-occupied housing percentage

You can use EITHER variables OR derived_metrics or both. The geography_level is the only required parameter.

Available derived metrics: male_female_difference, unemployment_percentage, owner_occupied_percentage

When users ask comparative questions, determine the appropriate derived metric and use it to create meaningful visualizations."""


def _build_get_demographic_data_tool() -> Tool:
    user_friendly_variable_names = list(CENSUS_VARIABLE_MAP.keys())
    geography_level_names = list(GEOGRAPHY_HIERARCHY.keys())
    derived_metric_names = list(DERIVED_METRICS_MAP.keys())

    get_demographic_data_declaration = FunctionDeclaration(
        name="get_demographic_data",
        description="""Fetches demographic data from the US Census Bureau for data visualization and interactive maps. 

ALWAYS use this tool when users ask for:
- Maps (e.g., \"map of population by state\", \"show me a map\", \"map median income\")
- Charts or visualizations of demographic data
- County-level data for any state
- State-level data across the US
- Any demographic statistics (population, income, age, housing, etc.)
- Comparative queries (e.g., \"Which states have more men than women?\", \"States with highest unemployment\")

For MAP REQUESTS:
- Use geography_level=\"state\" for US-wide state maps
- Use geography_level=\"county\" for county maps within a state (requires state_name)
- The system will automatically create interactive choropleth maps

For COMPARATIVE QUERIES:
- Use derived_metrics for calculated comparisons (e.g., male_female_difference, unemployment_percentage)
- Derived metrics automatically compute differences, ratios, and percentages

For COUNTY REQUESTS: Always include the state_name parameter (e.g., \"California\", \"Texas\", \"New York\")""",
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
                    "description": "A list of derived/calculated metrics to compute (e.g., for comparisons like 'more men than women').",
                    "items": {
                        "type": "string",
                        "enum": derived_metric_names,
                    },
                },
                "state_name": {
                    "type": "string",
                    "description": "The name of the state (not required for state-level queries when getting all states).",
                },
                "county_name": {
                    "type": "string",
                    "description": "The name of the county.",
                },
                "place_name": {
                    "type": "string",
                    "description": "The name of the place.",
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

    return Tool(function_declarations=[get_demographic_data_declaration])


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

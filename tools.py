from config import CENSUS_VARIABLE_MAP, STATE_FIPS_MAP, GEOGRAPHY_HIERARCHY, GEOGRAPHY_ALIASES, DERIVED_METRICS_MAP # TEMP: absolute import for testing
from census_api_client import CensusAPIClient # TEMP: absolute import for testing
from data_enricher import enrich_data
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")

async def get_demographic_data(
    geography_level: str,
    variables: list[str] | None = None,
    state_name: str | None = None,
    county_name: str | None = None,
    place_name: str | None = None,
    tract_code: str | None = None,
    block_group_code: str | None = None,
    zip_code_tabulation_area: str | None = None,
    derived_metrics: list[str] | None = None
) -> dict:
    """
    Fetches demographic data from the US Census Bureau ACS5 API.

    Args:
        geography_level (str): The target geographic level (e.g., "state", "county", "place", "tract", "block group", "zcta").
        variables (list[str]): A list of user-friendly variable names to retrieve (e.g., "total population", "median household income").
        state_name (str, optional): The name of the state. Required for county, place, tract, block group, and zcta levels.
        county_name (str, optional): The name of the county. Required for tract and block group levels.
        place_name (str, optional): The name of the place (city, town, CDP).
        tract_code (str, optional): The Census tract code.
        block_group_code (str, optional): The block group code.
        zip_code_tabulation_area (str, optional): The 5-digit ZCTA code.
        derived_metrics (list[str], optional): A list of derived metrics to calculate (e.g., "male_female_difference").

    Returns:
        dict: A dictionary containing the requested demographic data or an error message.
    """
    print(f"Attempting to get demographic data with params: {{'geography_level': '{geography_level}', 'variables': {variables}, 'state_name': '{state_name}', 'county_name': '{county_name}', 'place_name': '{place_name}', 'tract_code': '{tract_code}', 'block_group_code': '{block_group_code}', 'zip_code_tabulation_area': '{zip_code_tabulation_area}', 'derived_metrics': {derived_metrics}}}")

    # 0. Validate that either variables or derived_metrics is provided
    if not variables and not derived_metrics:
        return {"error": "Either 'variables' or 'derived_metrics' must be provided"}

    # 1. Normalize geography level
    normalized_geo_level = GEOGRAPHY_ALIASES.get(geography_level.lower(), geography_level.lower())
    if normalized_geo_level not in GEOGRAPHY_HIERARCHY:
        return {"error": f"Invalid geography level: {geography_level}. Supported levels are: {list(GEOGRAPHY_HIERARCHY.keys())}"}

    # 2. Determine all necessary raw variables (both directly requested and those needed for derived metrics)
    all_required_raw_vars = set(variables or [])
    if derived_metrics:
        for metric in derived_metrics:
            if metric in DERIVED_METRICS_MAP:
                all_required_raw_vars.update(DERIVED_METRICS_MAP[metric]["required_variables"])
            else:
                return {"error": f"Unknown derived metric: {metric}. Available metrics: {list(DERIVED_METRICS_MAP.keys())}"}

    # 3. Validate parent geographies and get FIPS codes
    state_fips = None
    county_fips = None
    place_fips = None # Placeholder for future place FIPS lookup if needed directly

    # For state-level queries (Phase 3), we don't require state_name since we get all states
    if normalized_geo_level not in ["us", "state"]:
        if not state_name:
            return {"error": f"State name is required for geography level: {normalized_geo_level}"}
        state_fips = STATE_FIPS_MAP.get(state_name.lower())
        if not state_fips:
            return {"error": f"Invalid state name: {state_name}"}

    # Phase 3: For county-level mapping, we get ALL counties in a state, so county_name is not required
    # Only require county_name for specific tract/block group queries
    if normalized_geo_level in ["tract", "block group"]:
        if not county_name:
            return {"error": f"County name is required for geography level: {normalized_geo_level}"}
        # County FIPS will be looked up by the CensusAPIClient or needs a more complex lookup here
        # For now, we'll pass the name and let the client try to resolve if it can, or enhance later.

    # 4. Map user-friendly variable names to Census variable IDs
    census_vars = []
    unknown_vars = []
    print(f"Input all_required_raw_vars: {all_required_raw_vars}")
    for var_name in all_required_raw_vars:
        normalized_var_name = var_name.lower() # Normalize once
        print(f"Checking variable: '{var_name}' -> normalized: '{normalized_var_name}'")
        if normalized_var_name in CENSUS_VARIABLE_MAP: # CORRECTED: Check directly against CENSUS_VARIABLE_MAP keys
            census_var_id = CENSUS_VARIABLE_MAP[normalized_var_name]
            census_vars.append(census_var_id)
            print(f"Mapped '{normalized_var_name}' to '{census_var_id}'")
        else:
            unknown_vars.append(var_name)
            print(f"Unknown variable: '{var_name}'")

    # Always include NAME to get geographic entity names for charts and labels
    print(f"Before adding NAME: census_vars = {census_vars}")
    if "NAME" not in census_vars:
        census_vars.append("NAME")
        print("Added NAME variable for geographic entity labels")
    else:
        print("NAME already in census_vars")
    
    print(f"Final census_vars: {census_vars}")
    print(f"Unknown vars: {unknown_vars}")
    
    if unknown_vars:
        return {"error": f"Unknown variables: {', '.join(unknown_vars)}. Please check available variables."}
    if not census_vars:
        return {"error": "No valid variables provided."}

    # 5. Construct 'for_query' and 'in_queries' for CensusAPIClient
    for_query = None
    in_queries = {}

    if normalized_geo_level == "us":
        for_query = "us:1" # Special case for US - single value
        
    elif normalized_geo_level == "state":
        # Phase 3: For state-level maps, get ALL states for choropleth visualization
        for_query = "state:*" # Get all states
        # No in_queries needed for states
        
    elif normalized_geo_level == "county":
        # Phase 3: For county-level maps, get all counties within a specific state
        if not state_name:
            return {"error": "State name is required for county-level queries. Example: 'Show counties in California'"}
        for_query = "county:*" # Get all counties
        in_queries["state"] = state_fips # Within the specified state
        
    elif normalized_geo_level == "place":
        # Get all places (cities, towns) within a specific state
        if not state_name:
            return {"error": "State name is required for place-level queries. Example: 'Show cities in Oregon'"}
        for_query = "place:*" # Get all places
        in_queries["state"] = state_fips # Within the specified state
        
    elif normalized_geo_level == "zip code tabulation area":
        # ZCTA queries - can be national or state-specific
        if zip_code_tabulation_area:
            for_query = f"zip code tabulation area:{zip_code_tabulation_area}" # Specific ZCTA
        else:
            for_query = "zip code tabulation area:*" # All ZCTAs
            if state_fips: # Optionally filter by state
                in_queries["state"] = state_fips
                
    elif normalized_geo_level == "tract":
        # Census tracts require both state and county - not supported in Phase 3
        return {"error": "Tract-level queries are not yet supported in Phase 3. Please use state or county level."}
        
    else:
        return {"error": f"Geographic level '{normalized_geo_level}' is not supported. Supported levels: us, state, county, place, zip code tabulation area."}


    # 6. Call CensusAPIClient
    if not CENSUS_API_KEY: # This check is somewhat redundant if CensusAPIClient handles it, but good for early exit.
        return {"error": "Census API key is not configured in the environment for the tool to check."}

    client = CensusAPIClient() # CORRECTED: No longer passing api_key argument
    try:
        print(f"Calling CensusAPIClient with: variables={census_vars}, for_query='{for_query}', in_queries={in_queries}")
        # The get_acs5_data method in CensusAPIClient needs a year parameter.
        # We should decide on a default year or make it a parameter of get_demographic_data.
        # For now, let's hardcode a recent, commonly available ACS5 year like 2022.
        # This should ideally be configurable or passed in.
        year = 2022 
        data = await client.get_acs5_data(
            year=year, 
            variables=census_vars,
            for_geo=for_query, # CORRECTED: Pass the constructed for_query string to for_geo
            in_geos=in_queries if in_queries else None 
        )
        
        # 7. Enrich data with derived metrics if requested
        if derived_metrics:
            data = enrich_data(data, derived_metrics)
            
        return data
    except Exception as e:
        return {"error": f"Error calling Census API: {str(e)}"}


def calculate_summary_statistics(data: list[dict], variable_id: str) -> dict | None:
    """Calculates summary stats for a given variable in the dataset."""
    # Extract valid, numeric values, handling None and non-numeric types
    values = []
    for row in data:
        if variable_id in row and row[variable_id] is not None:
            try:
                # Handle string representations of numbers
                if isinstance(row[variable_id], str):
                    if row[variable_id].replace('.', '', 1).replace('-', '', 1).isdigit():
                        values.append(float(row[variable_id]))
                elif isinstance(row[variable_id], (int, float)):
                    values.append(float(row[variable_id]))
            except (ValueError, TypeError):
                # Skip invalid values
                continue
    
    if not values:
        return None
    
    # Calculate stats
    import statistics
    mean = statistics.mean(values)
    median = statistics.median(values)
    min_val = min(values)
    max_val = max(values)
    count = len(values)
    
    # Find entities with min/max values
    min_entity = next((item.get('NAME', 'N/A') for item in data 
                      if variable_id in item and item[variable_id] is not None 
                      and float(str(item[variable_id]).replace('-', '', 1)) == min_val), 'N/A')
    max_entity = next((item.get('NAME', 'N/A') for item in data 
                      if variable_id in item and item[variable_id] is not None 
                      and float(str(item[variable_id]).replace('-', '', 1)) == max_val), 'N/A')

    return {
        "mean": round(mean, 2),
        "median": round(median, 2), 
        "min": round(min_val, 2),
        "max": round(max_val, 2), 
        "count": count,
        "min_entity_name": min_entity,
        "max_entity_name": max_entity
    }


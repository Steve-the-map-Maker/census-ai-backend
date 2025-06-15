from config import CENSUS_VARIABLE_MAP, STATE_FIPS_MAP, GEOGRAPHY_HIERARCHY, GEOGRAPHY_ALIASES # TEMP: absolute import for testing
from census_api_client import CensusAPIClient # TEMP: absolute import for testing
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")

async def get_demographic_data(
    geography_level: str,
    variables: list[str],
    state_name: str | None = None,
    county_name: str | None = None,
    place_name: str | None = None,
    tract_code: str | None = None,
    block_group_code: str | None = None,
    zip_code_tabulation_area: str | None = None
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

    Returns:
        dict: A dictionary containing the requested demographic data or an error message.
    """
    print(f"Attempting to get demographic data with params: {{'geography_level': '{geography_level}', 'variables': {variables}, 'state_name': '{state_name}', 'county_name': '{county_name}', 'place_name': '{place_name}', 'tract_code': '{tract_code}', 'block_group_code': '{block_group_code}', 'zip_code_tabulation_area': '{zip_code_tabulation_area}'}}")

    # 1. Normalize geography level
    normalized_geo_level = GEOGRAPHY_ALIASES.get(geography_level.lower(), geography_level.lower())
    if normalized_geo_level not in GEOGRAPHY_HIERARCHY:
        return {"error": f"Invalid geography level: {geography_level}. Supported levels are: {list(GEOGRAPHY_HIERARCHY.keys())}"}

    # 2. Validate parent geographies and get FIPS codes
    state_fips = None
    county_fips = None
    place_fips = None # Placeholder for future place FIPS lookup if needed directly

    if normalized_geo_level != "us":
        if not state_name:
            return {"error": f"State name is required for geography level: {normalized_geo_level}"}
        state_fips = STATE_FIPS_MAP.get(state_name.lower())
        if not state_fips:
            return {"error": f"Invalid state name: {state_name}"}

    if normalized_geo_level in ["county", "tract", "block group"]:
        if not county_name:
            return {"error": f"County name is required for geography level: {normalized_geo_level}"}
        # County FIPS will be looked up by the CensusAPIClient or needs a more complex lookup here
        # For now, we'll pass the name and let the client try to resolve if it can, or enhance later.

    # 3. Map user-friendly variable names to Census variable IDs
    census_vars = []
    unknown_vars = []
    for var_name in variables:
        normalized_var_name = var_name.lower() # Normalize once
        if normalized_var_name in CENSUS_VARIABLE_MAP: # CORRECTED: Check directly against CENSUS_VARIABLE_MAP keys
            census_vars.append(CENSUS_VARIABLE_MAP[normalized_var_name])
        else:
            unknown_vars.append(var_name)

    if unknown_vars:
        return {"error": f"Unknown variables: {', '.join(unknown_vars)}. Please check available variables."}
    if not census_vars:
        return {"error": "No valid variables provided."}

    # 4. Construct 'for_query' and 'in_queries' for CensusAPIClient
    for_query = None
    in_queries = {}

    if normalized_geo_level == "us":
        for_query = "us:1" # Special case for US
    elif normalized_geo_level == "state":
        for_query = f"state:{state_fips}"
    elif normalized_geo_level == "county":
        for_query = f"county:*" # Get all counties
        in_queries["state"] = state_fips
        if county_name: # If specific county is requested, this needs more specific handling
             # This part is tricky: mapping county name to FIPS without knowing the state first.
             # The CensusAPIClient's get_acs5_data expects FIPS.
             # We might need a helper function to get county FIPS by name and state FIPS.
             # For now, we'll assume the API client can handle county name if state FIPS is provided,
             # or this part needs refinement.
             # A direct query for a specific county by name usually requires its FIPS.
             # Let's assume for now we want all counties in a state if no specific county FIPS is found.
             # If a county_name is provided, we'd ideally resolve it to its FIPS code here.
             # This is a simplification for now.
             pass
    elif normalized_geo_level == "place":
        for_query = f"place:*" # Get all places in a state
        in_queries["state"] = state_fips
        # Similar to county, resolving place_name to FIPS would be needed for specific place.
    elif normalized_geo_level == "tract":
        if not county_name: # County name is essential for tract queries
            return {"error": "County name is required for tract level queries."}
        for_query = f"tract:*"
        in_queries["state"] = state_fips
        # County FIPS is needed here. This is a known gap.
        # We'd need to look up county FIPS from county_name and state_fips.
        # For now, this will likely fail or fetch all tracts in a state if county_fips isn't resolved.
        # Let's assume county_name is passed and client handles it, or we refine this.
        # The API usually requires county FIPS for 'in' clause for tracts.
        # This needs a robust county FIPS lookup.
        # For now, we'll pass county_name and assume client or a future step resolves it.
        # This is a simplification.
        # A more robust solution would be:
        # county_fips = await get_county_fips_by_name(county_name, state_fips)
        # if not county_fips:
        #     return {"error": f"Could not find FIPS for county: {county_name} in state: {state_name}"}
        # in_queries["county"] = county_fips
        # For now, we'll rely on the census_api_client to handle this if possible, or flag for improvement.
        # The current census_api_client expects FIPS codes in in_queries.
        # This will require modification or a helper.
        # Let's assume for now we are querying all tracts in a state, and filter later if county_name is given.
        # Or, the AI orchestrator should be prompted to provide county FIPS if county_name is given.
        # This is a complex part of name-to-FIPS resolution.
        # For the initial tool, let's keep it simpler and highlight this as an area for enhancement.
        # The `census_api_client` expects FIPS codes.
        # We need a way to get county FIPS from county_name and state_fips.
        # This is not directly in `STATE_FIPS_MAP`.
        # For now, this tool will be limited for sub-state queries by name without FIPS.
        # Let's assume the AI will provide FIPS codes if it knows them, or we handle simple cases.
        # The current structure of `get_acs5_data` expects FIPS.
        # We will need to add a county FIPS lookup.
        # For now, let's make a note that this part is incomplete for named counties.
        # The API call will be: client.get_acs5_data(variables=census_vars, for_query=f"tract:*", in_queries={"state": state_fips, "county": "COUNTY_FIPS_HERE"})
        # This means we MUST resolve county_name to county_fips.
        # This is a critical step.
        # For now, if county_name is provided but we can't get FIPS, we should error or return all tracts in state.
        # Let's return an error if county_name is given but we can't resolve it yet.
        # This functionality (name to FIPS for counties/places) is non-trivial.
        return {"error": "Querying by county_name without providing county FIPS is not yet supported. Please provide state and county FIPS codes for tract queries or query all tracts in a state."}

    elif normalized_geo_level == "block group":
        # Similar to tract, requires state and county FIPS.
        return {"error": "Querying by block group is not yet fully supported by name. Please provide state and county FIPS codes."}
    elif normalized_geo_level == "zcta":
        for_query = f"zip code tabulation area:{zip_code_tabulation_area if zip_code_tabulation_area else '*'}"
        if state_fips: # ZCTAs can span states, but often queried within a state context
            in_queries["state"] = state_fips
    else:
        return {"error": f"Logic for geography level '{normalized_geo_level}' is not fully implemented."}


    # 5. Call CensusAPIClient
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
        return data
    except Exception as e:
        return {"error": f"Error calling Census API: {str(e)}"}

# Example usage (for testing purposes)
async def main_test():
    # Test Case 1: Total population for California
    # result1 = await get_demographic_data(
    #     geography_level="state",
    #     variables=["total population"],
    #     state_name="California"
    # )
    # print("Test Case 1 Result:", result1)

    # Test Case 2: Median household income for all counties in Texas
    # result2 = await get_demographic_data(
    #     geography_level="county",
    #     variables=["median household income"],
    #     state_name="Texas"
    # )
    # print("Test Case 2 Result:", result2)

    # Test Case 3: Total population for a specific ZCTA (e.g., Beverly Hills)
    # result3 = await get_demographic_data(
    #     geography_level="zcta",
    #     variables=["total population"],
    #     zip_code_tabulation_area="90210"
    # )
    # print("Test Case 3 Result:", result3)

    # Test Case 4: Invalid variable
    # result4 = await get_demographic_data(
    #     geography_level="state",
    #     variables=["total unicorns"],
    #     state_name="Nevada"
    # )
    # print("Test Case 4 Result:", result4)

    # Test Case 5: US total population
    result5 = await get_demographic_data(
        geography_level="us",
        variables=["total population"]
    )
    print("Test Case 5 Result (US):", result5)


if __name__ == "__main__":
    # Ensure an event loop is running if calling async main_test directly
    # This is simplified; in a real app, FastAPI/Uvicorn handles the loop.
    # For direct script execution:
    if os.name == 'nt': # For Windows compatibility with asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # To run the test, you would uncomment the desired test cases in main_test()
    # and then run: python -m census_ai_backend.tools
    # Make sure your .env file with CENSUS_API_KEY is in census-ai-backend/
    # For now, this main_test is more for illustration.
    # Actual testing will be via the AI orchestrator and API endpoints.
    # print("To test, uncomment calls in main_test() and run: python -m census_ai_backend.tools")
    # Example:
    asyncio.run(main_test())

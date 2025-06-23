import asyncio
import httpx # Using httpx for async requests, requests for sync if preferred
import os
import config # TEMP: absolute import for testing

class CensusAPIClient:
    BASE_URL = "https://api.census.gov/data"

    def __init__(self):
        self.api_key = os.getenv("CENSUS_API_KEY")
        if not self.api_key:
            raise ValueError("CENSUS_API_KEY not found in .env file. Please add it.")

    async def get_acs5_data(self, year: int, variables: list[str], for_geo: str, in_geos: dict = None) -> list[dict]:
        """
        Fetches data from the ACS 5-Year Estimates.

        Args:
            year: The year of the data (e.g., 2022).
            variables: A list of Census variable IDs (e.g., ["B01003_001E", "B19013_001E"]).
            for_geo: The target geography level's API name (e.g., "county", "state", "us").
            in_geos: A dictionary of parent geographies and their FIPS codes 
                     (e.g., {"state": "06"} for counties in California, 
                      or {"state": "06", "county": "037"} for tracts in Los Angeles County).
                     Can be None if for_geo is 'us' or 'state' (when no parent is needed beyond what's implied by for_geo).

        Returns:
            A list of dictionaries, where each dictionary represents a record.
            Returns an empty list if an error occurs or no data is found.
        """
        if not variables:
            print("Error: No variables specified for Census API call.")
            return []

        get_vars = ",".join(variables)
        params = {
            "get": get_vars,
            "for": for_geo, # CORRECTED: Use for_geo directly as tools.py now formats it correctly.
            "key": self.api_key
        }

        # Construct the &in= part of the query if in_geos is provided
        in_clause_parts = []
        if in_geos:
            # Order matters for Census API: state, then county, etc.
            # We can refine this order based on GEOGRAPHY_HIERARCHY if needed, but for now, a simple sort might work
            # or we rely on the caller (tools.py) to provide them in a sensible order if multiple.
            # For ACS, typical hierarchy is state -> county -> tract, or state -> place, etc.
            for parent_geo_api_name, parent_geo_id in in_geos.items():
                in_clause_parts.append(f"{parent_geo_api_name}:{parent_geo_id}")
        
        if in_clause_parts:
            params["in"] = " ".join(in_clause_parts) # Note: Census API uses space for multiple &in, but we only support one chain for now
            # Example: &in=state:06 county:037. If we need multiple &in for different hierarchies, this needs adjustment.
            # The plan implies a single chain: &in=state:value&in=county:value (which is not how Census API works)
            # Correct Census API for chained &in is more like: for=tract:*&in=state:06&in=county:037
            # So, the `params["in"]` should be a list of strings if httpx supports it, or handle multiple `&in=` by constructing the URL string manually.
            # For now, let's assume `in_geos` provides the full hierarchy for a single `for` target.
            # The `for` clause should be the most granular level, and `in` clauses specify its parents.
            # Example: for_geo="tract", in_geos={"state":"06", "county":"037"}
            # URL part: ...&for=tract:*&in=state:06&in=county:037
            # The current `params["in"]` construction is simplified and might need refinement based on how `tools.py` structures `in_geos`.
            # Let's refine this to build the &in clauses correctly.
            del params["in"] # Remove the simplified one
            in_params_string = ""
            if in_geos:
                for parent_geo_api_name, parent_geo_id in in_geos.items():
                    in_params_string += f"&in={parent_geo_api_name}:{parent_geo_id}"

        # Construct the full URL
        # Example dataset: American Community Survey 5-Year Data (ACS5)
        # We might need to make the dataset (e.g., "acs/acs5") configurable too.
        # For now, hardcoding to acs/acs5 for 5-year estimates.
        url = f"{self.BASE_URL}/{year}/acs/acs5?get={get_vars}&for={for_geo}" # CORRECTED: Use for_geo directly
        if in_geos: # Re-evaluating how to add &in clauses with httpx
             url += in_params_string
        url += f"&key={self.api_key}"

        print(f"Requesting Census Data from URL: {url}") # For debugging

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()  # Raises an exception for 4XX/5XX responses
                data = response.json()
                
                if not data or len(data) < 2: # Expecting header row + data rows
                    print(f"No data returned or unexpected format from Census API for query: {url}")
                    return []

                # Convert list of lists to list of dicts using the header row
                header = data[0]
                records = [dict(zip(header, row)) for row in data[1:]]
                return records
        except httpx.HTTPStatusError as e:
            print(f"HTTP error occurred: {e} - {e.response.text}")
            return []
        except httpx.RequestError as e:
            print(f"Request error occurred: {e}")
            return []
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return []



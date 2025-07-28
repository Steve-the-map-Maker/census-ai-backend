# Maps human-readable names to Census Bureau ACS 5-Year variable IDs.
# Grouped by topic for clarity and future expansion.
CENSUS_VARIABLE_MAP = {
    # --- Demographics ---
    "total_population": "B01003_001E",  # Total Population
    "median_age": "B01002_001E",        # Median Age
    "male_population": "B01001_002E",      # Male Population
    "female_population": "B01001_026E",    # Female Population

    # --- Economics ---
    "median_household_income": "B19013_001E", # Median Household Income in the Past 12 Months
    "per_capita_income": "B19301_001E",     # Per Capita Income in the Past 12 Months
    "population_in_poverty": "B17001_002E",   # Population with Poverty Status in the Past 12 Months
    "employment_rate": "B23025_004E",     # Employed Civilian Population 16 Years and Over
    "unemployment_rate": "B23025_005E",   # Unemployed Civilian Population 16 Years and Over

    # --- Housing ---
    "total_housing_units": "B25001_001E", # Total Housing Units
    "owner_occupied_housing_units": "B25003_002E", # Owner-Occupied Housing Units
    "renter_occupied_housing_units": "B25003_003E", # Renter-Occupied Housing Units
    "median_home_value": "B25077_001E",   # Median Value of Owner-Occupied Housing Units
    "median_gross_rent": "B25064_001E",     # Median Gross Rent

    # --- Social & Education ---
    "population_with_bachelors_degree_or_higher": "B15003_022E", # Population 25+ with Bachelor's Degree
    "population_with_high_school_diploma": "B15003_017E", # Population 25+ with High School Graduate (or equivalent)
    "foreign_born_population": "B05002_013E", # Foreign-Born Population
}

# Maps state/territory names to their FIPS codes.
# Uses lowercase for easy, case-insensitive matching.
STATE_FIPS_MAP = {
    "alabama": "01", "alaska": "02", "arizona": "04", "arkansas": "05", "california": "06",
    "colorado": "08", "connecticut": "09", "delaware": "10", "district of columbia": "11",
    "florida": "12", "georgia": "13", "hawaii": "15", "idaho": "16", "illinois": "17",
    "indiana": "18", "iowa": "19", "kansas": "20", "kentucky": "21", "louisiana": "22",
    "maine": "23", "maryland": "24", "massachusetts": "25", "michigan": "26",
    "minnesota": "27", "mississippi": "28", "missouri": "29", "montana": "30",
    "nebraska": "31", "nevada": "32", "new hampshire": "33", "new jersey": "34",
    "new mexico": "35", "new york": "36", "north carolina": "37", "north dakota": "38",
    "ohio": "39", "oklahoma": "40", "oregon": "41", "pennsylvania": "42",
    "rhode island": "44", "south carolina": "45", "south dakota": "46", "tennessee": "47",
    "texas": "48", "utah": "49", "vermont": "50", "virginia": "51", "washington": "53",
    "west virginia": "54", "wisconsin": "55", "wyoming": "56",
    # --- Territories ---
    "puerto rico": "72", "guam": "66", "virgin islands": "78", "american samoa": "60",
    "northern mariana islands": "69"
}

# Defines supported Census geographic levels, their API names, and required parent geographies.
GEOGRAPHY_HIERARCHY = {
    "us": {"api_name": "us", "requires": []},
    "state": {"api_name": "state", "requires": []},
    "county": {"api_name": "county", "requires": ["state"]},
    "place": {"api_name": "place", "requires": ["state"]}, # Cities, towns, etc.
    "congressional district": {"api_name": "congressional district", "requires": ["state"]},
    "zip code tabulation area": {"api_name": "zip code tabulation area", "requires": ["state"]},
    "metropolitan statistical area": {"api_name": "metropolitan statistical area/micropolitan statistical area", "requires": []},
    "tract": {"api_name": "tract", "requires": ["state", "county"]},
}

# Maps common user terms to the official keys in GEOGRAPHY_HIERARCHY.
GEOGRAPHY_ALIASES = {
    "nation": "us", "country": "us", "united states": "us",
    "states": "state",
    "counties": "county",
    "city": "place", "town": "place", "cities": "place",
    "zip": "zip code tabulation area", "zip code": "zip code tabulation area",
    "metro area": "metropolitan statistical area",
    "census tract": "tract",
}

# Defines calculations that can be performed on raw Census data.
# 'name': Human-readable name for the metric.
# 'required_variables': List of keys from CENSUS_VARIABLE_MAP needed for the calculation.
# 'calculation': A lambda function to compute the new value from a data row.
DERIVED_METRICS_MAP = {
    "male_female_difference": {
        "name": "Male-Female Population Difference",
        "required_variables": ["male_population", "female_population"],
        "calculation": lambda row, labels: float(row.get(labels["male_population"], 0)) - float(row.get(labels["female_population"], 0))
    },
    "unemployment_percentage": {
        "name": "Unemployment Rate (%)",
        "required_variables": ["unemployment_rate", "employment_rate"],
        "calculation": lambda row, labels: (float(row.get(labels["unemployment_rate"], 0)) / (float(row.get(labels["unemployment_rate"], 0)) + float(row.get(labels["employment_rate"], 0)))) * 100 if (float(row.get(labels["unemployment_rate"], 0)) + float(row.get(labels["employment_rate"], 0))) > 0 else 0
    },
    "owner_occupied_percentage": {
        "name": "Owner-Occupied Housing Rate (%)",
        "required_variables": ["owner_occupied_housing_units", "total_housing_units"],
        "calculation": lambda row, labels: (float(row.get(labels["owner_occupied_housing_units"], 0)) / float(row.get(labels["total_housing_units"], 1))) * 100 if float(row.get(labels["total_housing_units"], 1)) > 0 else 0
    },
    "poverty_percentage": {
        "name": "Poverty Rate (%)",
        "required_variables": ["population_in_poverty", "total_population"],
        "calculation": lambda row, labels: (float(row.get(labels["population_in_poverty"], 0)) / float(row.get(labels["total_population"], 1))) * 100 if float(row.get(labels["total_population"], 1)) > 0 else 0
    },
    "bachelors_degree_percentage": {
        "name": "Population with Bachelor's Degree or Higher (%)",
        "required_variables": ["population_with_bachelors_degree_or_higher", "total_population"],
        "calculation": lambda row, labels: (float(row.get(labels["population_with_bachelors_degree_or_higher"], 0)) / float(row.get(labels["total_population"], 1))) * 100 if float(row.get(labels["total_population"], 1)) > 0 else 0
    },
    "housing_vacancy_rate": {
        "name": "Housing Vacancy Rate (%)",
        "required_variables": ["total_housing_units", "owner_occupied_housing_units", "renter_occupied_housing_units"],
        "calculation": lambda row, labels: ((float(row.get(labels["total_housing_units"], 0)) - float(row.get(labels["owner_occupied_housing_units"], 0)) - float(row.get(labels["renter_occupied_housing_units"], 0))) / float(row.get(labels["total_housing_units"], 1))) * 100 if float(row.get(labels["total_housing_units"], 1)) > 0 else 0
    }
}

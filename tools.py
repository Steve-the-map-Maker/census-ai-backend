from config import CENSUS_VARIABLE_MAP, STATE_FIPS_MAP, GEOGRAPHY_HIERARCHY, GEOGRAPHY_ALIASES, DERIVED_METRICS_MAP # TEMP: absolute import for testing
from census_api_client import CensusAPIClient # TEMP: absolute import for testing
from data_enricher import enrich_data
import asyncio
import copy
import os
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")
DEFAULT_ACS_YEAR = int(os.getenv("DEFAULT_ACS_YEAR", "2022"))
MIN_ACS_YEAR = int(os.getenv("MIN_ACS_YEAR", "2010"))
MAX_ACS_YEAR = int(os.getenv("MAX_ACS_YEAR", str(DEFAULT_ACS_YEAR)))

_TIME_SERIES_CACHE: Dict[str, Dict[str, Any]] = {}


def _coerce_numeric(value: Any) -> Optional[float]:
    coerced = _safe_float(value)
    if coerced is None and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return coerced


def _row_matches_filter(row: Dict[str, Any], condition: Dict[str, Any]) -> bool:
    """Evaluate a single filter condition against a row."""

    if not isinstance(condition, dict):
        return True

    field = condition.get("field")
    if not field:
        return True

    operator = str(condition.get("operator", "eq")).lower()
    target_value = condition.get("value")
    row_value = row.get(field)

    if operator in {"eq", "equals"}:
        return row_value == target_value
    if operator in {"neq", "not_equals"}:
        return row_value != target_value
    if operator in {"contains", "includes"}:
        if row_value is None or target_value is None:
            return False
        return str(target_value).lower() in str(row_value).lower()

    numeric_row = _coerce_numeric(row_value)
    numeric_target = _coerce_numeric(target_value)
    if numeric_row is None or numeric_target is None:
        return False

    if operator in {"gt", "greater_than"}:
        return numeric_row > numeric_target
    if operator in {"gte", "ge", "greater_or_equal"}:
        return numeric_row >= numeric_target
    if operator in {"lt", "less_than"}:
        return numeric_row < numeric_target
    if operator in {"lte", "le", "less_or_equal"}:
        return numeric_row <= numeric_target

    return True


def _apply_filters(rows: List[Dict[str, Any]], filters: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not filters:
        return rows
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        if all(_row_matches_filter(row, condition) for condition in filters):
            filtered.append(row)
    return filtered


def _apply_sort(rows: List[Dict[str, Any]], sort_spec: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not sort_spec:
        return rows

    field = sort_spec.get("field")
    if not field:
        return rows

    direction = str(sort_spec.get("direction", "desc")).lower()
    reverse = direction in {"desc", "descending", "-1"}

    def sort_key(row: Dict[str, Any]) -> Any:
        numeric_value = _coerce_numeric(row.get(field))
        return numeric_value if numeric_value is not None else row.get(field)

    try:
        return sorted(rows, key=sort_key, reverse=reverse)
    except TypeError:
        return rows


def refine_dashboard_data(
    raw_payload: Dict[str, Any],
    filters: Optional[List[Dict[str, Any]]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    current_year: Optional[int] = None,
) -> Dict[str, Any]:
    """Refine an existing dashboard payload without issuing new Census API calls."""

    if not isinstance(raw_payload, dict):
        return {"error": "raw_payload must be an object"}

    payload = copy.deepcopy(raw_payload)
    metadata = payload.setdefault("metadata", {})

    data_rows = payload.get("data")
    if not isinstance(data_rows, list):
        data_rows = []

    working_rows = [dict(row) for row in data_rows]

    if current_year is not None:
        metadata["active_year"] = current_year
        year_filtered = [row for row in working_rows if str(row.get("year")) == str(current_year)]
        if year_filtered:
            working_rows = year_filtered

    working_rows = _apply_filters(working_rows, filters)
    working_rows = _apply_sort(working_rows, sort)

    if isinstance(limit, int) and limit > 0:
        working_rows = working_rows[:limit]
        metadata["applied_limit"] = limit

    if filters:
        metadata["applied_filters"] = copy.deepcopy(filters)
    if sort:
        metadata["applied_sort"] = copy.deepcopy(sort)

    payload["data"] = working_rows

    summary_components: List[str] = []
    if filters:
        summary_components.append("filters applied")
    if sort:
        summary_components.append("sorted")
    if limit:
        summary_components.append(f"top {limit}")
    if current_year is not None:
        summary_components.append(f"year {current_year}")

    if summary_components:
        base_summary = payload.get("summary_text", "Refined dashboard view")
        payload["summary_text"] = f"{base_summary} (" + ", ".join(summary_components) + ")"

    return payload


def _normalize_geography_level(geography_level: str | None) -> str:
    if not geography_level:
        return ""
    return GEOGRAPHY_ALIASES.get(geography_level.lower(), geography_level.lower())


def _safe_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            return float(value.replace(",", ""))
    except (TypeError, ValueError):
        return None
    return None


def _coerce_year(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _build_census_request(
    geography_level: str,
    variables: Optional[List[str]],
    derived_metrics: Optional[List[str]],
    state_name: Optional[str],
    county_name: Optional[str],
    place_name: Optional[str],
    tract_code: Optional[str],
    block_group_code: Optional[str],
    zip_code_tabulation_area: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    normalized_geo_level = _normalize_geography_level(geography_level)
    if normalized_geo_level not in GEOGRAPHY_HIERARCHY:
        return None, f"Invalid geography level: {geography_level}. Supported levels are: {list(GEOGRAPHY_HIERARCHY.keys())}"

    variables = variables or []
    derived_metrics = derived_metrics or []
    normalized_variables = [var.lower() for var in variables]

    if not normalized_variables and not derived_metrics:
        return None, "Either 'variables' or 'derived_metrics' must be provided"

    all_required_raw_vars = set(normalized_variables)
    for metric in derived_metrics:
        if metric in DERIVED_METRICS_MAP:
            all_required_raw_vars.update(DERIVED_METRICS_MAP[metric]["required_variables"])
        else:
            return None, f"Unknown derived metric: {metric}. Available metrics: {list(DERIVED_METRICS_MAP.keys())}"

    resolved_variable_codes: Dict[str, str] = {}
    unknown_vars: List[str] = []
    for raw_var in all_required_raw_vars:
        normalized = raw_var.lower()
        if normalized in CENSUS_VARIABLE_MAP:
            resolved_variable_codes[normalized] = CENSUS_VARIABLE_MAP[normalized]
        else:
            unknown_vars.append(raw_var)

    if unknown_vars:
        unique_unknowns = sorted(set(unknown_vars))
        return None, f"Unknown variables: {', '.join(unique_unknowns)}. Please check available variables."

    primary_variable_codes: List[str] = []
    user_variable_code_map: Dict[str, str] = {}
    for var in variables:
        normalized = var.lower()
        code = CENSUS_VARIABLE_MAP.get(normalized)
        if code:
            user_variable_code_map[var] = code
            if code not in primary_variable_codes:
                primary_variable_codes.append(code)

    additional_codes = [code for code in resolved_variable_codes.values() if code not in primary_variable_codes]
    census_vars = primary_variable_codes + additional_codes
    if "NAME" not in census_vars:
        census_vars.append("NAME")

    state_fips = None
    if state_name:
        state_fips = STATE_FIPS_MAP.get(state_name.lower())
        if not state_fips:
            return None, f"Invalid state name: {state_name}"

    if normalized_geo_level not in ["us", "state"]:
        if not state_name:
            return None, f"State name is required for geography level: {normalized_geo_level}"
        if not state_fips:
            return None, f"Invalid state name: {state_name}"

    in_queries: Dict[str, str] = {}
    if normalized_geo_level == "us":
        for_query = "us:1"
    elif normalized_geo_level == "state":
        if state_fips:
            for_query = f"state:{state_fips}"
        else:
            for_query = "state:*"
    elif normalized_geo_level == "county":
        if not state_name:
            return None, "State name is required for county-level queries. Example: 'Show counties in California'"
        for_query = "county:*"
        in_queries["state"] = state_fips or ""
    elif normalized_geo_level == "place":
        if not state_name:
            return None, "State name is required for place-level queries. Example: 'Show cities in Oregon'"
        for_query = "place:*"
        in_queries["state"] = state_fips or ""
    elif normalized_geo_level == "zip code tabulation area":
        if zip_code_tabulation_area:
            for_query = f"zip code tabulation area:{zip_code_tabulation_area}"
            if state_fips:
                in_queries["state"] = state_fips
        else:
            for_query = "zip code tabulation area:*"
            if state_fips:
                in_queries["state"] = state_fips
    elif normalized_geo_level == "tract":
        return None, "Tract-level queries are not yet supported. Please use state or county level."
    else:
        return None, f"Geographic level '{normalized_geo_level}' is not supported."

    request_config = {
        "normalized_geography_level": normalized_geo_level,
        "requested_geography_level": geography_level,
        "variables": variables,
        "normalized_variables": normalized_variables,
        "derived_metrics": derived_metrics,
        "resolved_variable_codes": resolved_variable_codes,
        "primary_variable_codes": primary_variable_codes,
        "user_variable_code_map": user_variable_code_map,
        "required_census_vars": census_vars,
        "for_query": for_query,
        "in_queries": {k: v for k, v in in_queries.items() if v},
        "state_fips": state_fips,
        "state_name": state_name,
        "county_name": county_name,
        "place_name": place_name,
        "tract_code": tract_code,
        "block_group_code": block_group_code,
        "zip_code_tabulation_area": zip_code_tabulation_area,
    }

    return request_config, None


def _time_series_cache_key(config: Dict[str, Any], start_year: int, end_year: int) -> str:
    key_parts = (
        config.get("normalized_geography_level", ""),
        config.get("state_name") or "",
        config.get("county_name") or "",
        config.get("place_name") or "",
        config.get("zip_code_tabulation_area") or "",
        tuple(config.get("normalized_variables", [])),
        tuple(config.get("derived_metrics", [])),
        start_year,
        end_year,
    )
    return str(key_parts)


async def _fetch_year_data(request_config: Dict[str, Any], year: int) -> Tuple[int, List[Dict[str, Any]]]:
    client = CensusAPIClient()
    data = await client.get_acs5_data(
        year=year,
        variables=request_config["required_census_vars"],
        for_geo=request_config["for_query"],
        in_geos=request_config["in_queries"] or None,
    )
    if request_config["derived_metrics"]:
        data = enrich_data(data, request_config["derived_metrics"])
    return year, data


def _compose_geo_identifier(row: Dict[str, Any], normalized_geo_level: str) -> Tuple[str, Dict[str, Any]]:
    hierarchy = GEOGRAPHY_HIERARCHY.get(normalized_geo_level, {})
    component_fields: List[str] = []
    component_values: Dict[str, Any] = {}

    for parent in hierarchy.get("requires", []):
        api_field = GEOGRAPHY_HIERARCHY[parent]["api_name"]
        component_fields.append(api_field)
        component_values[api_field] = row.get(api_field)

    api_field = hierarchy.get("api_name", normalized_geo_level)
    component_fields.append(api_field)
    component_values[api_field] = row.get(api_field)

    identifier_parts = [str(component_values[field]) for field in component_fields if component_values.get(field) not in [None, ""]]
    identifier = "-".join(identifier_parts) if identifier_parts else row.get("NAME", "unknown")
    return identifier, component_values


def _compute_time_series_metrics(values: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not values:
        return {
            "start_year": None,
            "end_year": None,
            "start_value": None,
            "end_value": None,
            "absolute_change": None,
            "percent_change": None,
            "cagr": None,
            "max_point": None,
            "min_point": None,
        }

    ordered = sorted(values, key=lambda item: item.get("year", 0))
    numeric = [item for item in ordered if item.get("value") is not None]

    if not numeric:
        return {
            "start_year": ordered[0].get("year"),
            "end_year": ordered[-1].get("year"),
            "start_value": None,
            "end_value": None,
            "absolute_change": None,
            "percent_change": None,
            "cagr": None,
            "max_point": None,
            "min_point": None,
        }

    start = numeric[0]
    end = numeric[-1]
    span_years = (end["year"] or 0) - (start["year"] or 0)

    absolute_change = None
    percent_change = None
    cagr = None

    if start.get("value") is not None and end.get("value") is not None:
        absolute_change = end["value"] - start["value"]
        if start["value"] != 0:
            percent_change = (absolute_change / start["value"]) * 100
        if span_years > 0 and start["value"] not in [None, 0] and end["value"] is not None and start["value"] > 0:
            try:
                cagr = (end["value"] / start["value"]) ** (1 / span_years) - 1
            except ZeroDivisionError:
                cagr = None

    max_point = max(numeric, key=lambda item: item["value"], default=None)
    min_point = min(numeric, key=lambda item: item["value"], default=None)

    return {
        "start_year": start.get("year"),
        "end_year": end.get("year"),
        "start_value": start.get("value"),
        "end_value": end.get("value"),
        "absolute_change": absolute_change,
        "percent_change": percent_change,
        "cagr": cagr,
        "max_point": max_point,
        "min_point": min_point,
    }


def _select_best_series(series_list: List[Dict[str, Any]], metric_key: str) -> Optional[Dict[str, Any]]:
    candidates = [series for series in series_list if series.get("metrics", {}).get(metric_key) not in [None, float("nan")]]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item["metrics"][metric_key])


def _format_metric_entry(entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not entry:
        return None
    return {
        "geography_id": entry.get("geography_id"),
        "NAME": entry.get("NAME"),
        "metrics": entry.get("metrics"),
    }


async def get_demographic_data(
    geography_level: str,
    variables: Optional[List[str]] = None,
    state_name: Optional[str] = None,
    county_name: Optional[str] = None,
    place_name: Optional[str] = None,
    tract_code: Optional[str] = None,
    block_group_code: Optional[str] = None,
    zip_code_tabulation_area: Optional[str] = None,
    derived_metrics: Optional[List[str]] = None,
    year: Optional[int] = None,
) -> List[Dict[str, Any]] | Dict[str, Any]:
    """Fetch demographic data for a single ACS year."""

    request_config, error = _build_census_request(
        geography_level=geography_level,
        variables=variables,
        derived_metrics=derived_metrics,
        state_name=state_name,
        county_name=county_name,
        place_name=place_name,
        tract_code=tract_code,
        block_group_code=block_group_code,
        zip_code_tabulation_area=zip_code_tabulation_area,
    )

    if error:
        return {"error": error}

    target_year = _coerce_year(year) or DEFAULT_ACS_YEAR
    target_year = max(MIN_ACS_YEAR, min(target_year, MAX_ACS_YEAR))

    if not CENSUS_API_KEY:
        return {"error": "Census API key is not configured in the environment."}

    try:
        _, data = await _fetch_year_data(request_config, target_year)
        return data
    except Exception as exc:
        return {"error": f"Error calling Census API: {exc}"}


async def get_demographic_time_series(
    geography_level: str,
    variables: Optional[List[str]] = None,
    state_name: Optional[str] = None,
    county_name: Optional[str] = None,
    place_name: Optional[str] = None,
    tract_code: Optional[str] = None,
    block_group_code: Optional[str] = None,
    zip_code_tabulation_area: Optional[str] = None,
    derived_metrics: Optional[List[str]] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
) -> Dict[str, Any]:
    """Fetch demographic data across multiple years to support time-series analysis."""

    request_config, error = _build_census_request(
        geography_level=geography_level,
        variables=variables,
        derived_metrics=derived_metrics,
        state_name=state_name,
        county_name=county_name,
        place_name=place_name,
        tract_code=tract_code,
        block_group_code=block_group_code,
        zip_code_tabulation_area=zip_code_tabulation_area,
    )

    if error:
        return {"error": error}

    primary_code: Optional[str] = None
    if request_config["primary_variable_codes"]:
        primary_code = request_config["primary_variable_codes"][0]
    elif request_config["derived_metrics"]:
        primary_code = request_config["derived_metrics"][0]

    if not primary_code:
        return {"error": "Time series requests require at least one variable or derived metric."}

    start = _coerce_year(start_year) or MIN_ACS_YEAR
    end = _coerce_year(end_year) or MAX_ACS_YEAR
    start = max(MIN_ACS_YEAR, start)
    end = min(MAX_ACS_YEAR, end)

    if start > end:
        return {"error": "Invalid year range: start_year must be less than or equal to end_year."}

    if not CENSUS_API_KEY:
        return {"error": "Census API key is not configured in the environment."}

    cache_key = _time_series_cache_key(request_config, start, end)
    cached = _TIME_SERIES_CACHE.get(cache_key)
    if cached:
        return copy.deepcopy(cached)

    years = list(range(start, end + 1))
    tasks = [_fetch_year_data(request_config, year) for year in years]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    aggregated_rows: List[Dict[str, Any]] = []
    series_map: Dict[str, Dict[str, Any]] = {}
    available_years: List[int] = []
    missing_years: List[int] = []
    error_messages: List[str] = []

    for index, result in enumerate(results):
        year = years[index]
        if isinstance(result, Exception):
            missing_years.append(year)
            error_messages.append(f"Year {year}: {result}")
            continue

        result_year, year_data = result
        if not year_data:
            missing_years.append(result_year)
            continue

        available_years.append(result_year)
        for row in year_data:
            row_with_year = row.copy()
            row_with_year["year"] = result_year
            aggregated_rows.append(row_with_year)

            geo_id, geo_components = _compose_geo_identifier(row, request_config["normalized_geography_level"])
            entry = series_map.setdefault(
                geo_id,
                {
                    "geography_id": geo_id,
                    "NAME": row.get("NAME", geo_id),
                    "components": geo_components,
                    "values": [],
                },
            )

            raw_value = row.get(primary_code)
            entry["values"].append(
                {
                    "year": result_year,
                    "value": _safe_float(raw_value),
                    "raw_value": raw_value,
                }
            )

    series_list: List[Dict[str, Any]] = []
    for entry in series_map.values():
        entry["values"].sort(key=lambda item: item["year"])
        entry["metrics"] = _compute_time_series_metrics(entry["values"])
        series_list.append(entry)

    series_list.sort(key=lambda item: item.get("NAME", ""))

    largest_increase_entry = _select_best_series(series_list, "absolute_change")
    fastest_growth_entry = _select_best_series(series_list, "percent_change")

    metadata = {
        "geography_level": request_config["normalized_geography_level"],
        "geography_display": request_config["requested_geography_level"],
        "state_name": request_config.get("state_name"),
        "state_fips": request_config.get("state_fips"),
        "county_name": request_config.get("county_name"),
        "place_name": request_config.get("place_name"),
        "variables": request_config.get("variables"),
        "variable_codes": request_config.get("user_variable_code_map"),
        "primary_variable_code": primary_code,
        "years_requested": years,
        "years_available": sorted(available_years),
        "start_year": start,
        "end_year": end,
        "series_count": len(series_list),
    }

    result = {
        "data": aggregated_rows,
        "series": series_list,
        "metrics": {
            "largest_increase": _format_metric_entry(largest_increase_entry),
            "fastest_growth": _format_metric_entry(fastest_growth_entry),
            "year_range": [start, end],
        },
        "metadata": metadata,
        "errors": {
            "missing_years": missing_years,
            "messages": error_messages,
        } if missing_years or error_messages else {},
    }

    _TIME_SERIES_CACHE[cache_key] = copy.deepcopy(result)
    return copy.deepcopy(result)


def calculate_summary_statistics(data: List[Dict[str, Any]], variable_id: str) -> Optional[Dict[str, Any]]:
    """Calculates summary stats for a given variable in the dataset."""

    values: List[Tuple[float, str]] = []
    for row in data:
        value = _safe_float(row.get(variable_id))
        if value is not None:
            values.append((value, row.get("NAME", "N/A")))

    if not values:
        return None

    numeric_values = [value for value, _ in values]
    import statistics

    mean = statistics.mean(numeric_values)
    median = statistics.median(numeric_values)
    min_value = min(values, key=lambda item: item[0])
    max_value = max(values, key=lambda item: item[0])

    return {
        "mean": round(mean, 2),
        "median": round(median, 2),
        "min": round(min_value[0], 2),
        "max": round(max_value[0], 2),
        "count": len(values),
        "min_entity_name": min_value[1],
        "max_entity_name": max_value[1],
    }


from config import DERIVED_METRICS_MAP, CENSUS_VARIABLE_MAP

def enrich_data(data: list[dict], derived_metrics_to_calculate: list[str]) -> list[dict]:
    """
    Enriches raw Census data by calculating derived metrics.
    
    Args:
        data: List of dictionaries containing raw Census data
        derived_metrics_to_calculate: List of metric keys from DERIVED_METRICS_MAP to calculate
        
    Returns:
        List of dictionaries with original data plus calculated derived metrics
    """
    if not derived_metrics_to_calculate:
        return data

    # Create a map from the human-readable variable name to its Census code
    variable_code_map = {name: code for name, code in CENSUS_VARIABLE_MAP.items()}

    enriched_data = []
    for row in data:
        new_row = row.copy()
        for metric_key in derived_metrics_to_calculate:
            if metric_key in DERIVED_METRICS_MAP:
                metric_info = DERIVED_METRICS_MAP[metric_key]
                # Create a dictionary of labels needed for this specific calculation
                required_labels = {var_name: variable_code_map[var_name] for var_name in metric_info["required_variables"]}
                try:
                    # Pass the row and the required labels to the calculation function
                    new_row[metric_key] = metric_info["calculation"](row, required_labels)
                except Exception as e:
                    print(f"Could not calculate metric '{metric_key}': {e}")
                    new_row[metric_key] = None  # Set to None on failure
        enriched_data.append(new_row)
    return enriched_data

import os
import json
import asyncio
from typing import Any, Dict, List, Tuple

from proto.marshal.collections.repeated import RepeatedComposite

import google.generativeai as genai
from dotenv import load_dotenv

from llm_config import CENSUS_TOOL, SYSTEM_INSTRUCTION, get_variable_labels
from tools import (
    get_demographic_data,
    get_demographic_time_series,
    calculate_summary_statistics,
)  # TEMP: absolute import for testing

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("WARNING: GOOGLE_API_KEY not found in environment variables.")
    print("The application will not work properly without this API key.")
    # For development/debugging, you might want to continue, but for production this should fail
    raise ValueError("GOOGLE_API_KEY not found in environment variables. Please add it.")
genai.configure(api_key=api_key)

model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    tools=[CENSUS_TOOL],
    system_instruction=SYSTEM_INSTRUCTION
)

AVAILABLE_FUNCTIONS = {
    "get_demographic_data": get_demographic_data,
    "get_demographic_time_series": get_demographic_time_series,
}

DEFAULT_HISTORY_LIMIT = int(os.getenv("LLM_HISTORY_LIMIT", "6"))
NON_VALUE_KEYS = {"state", "county", "tract", "place", "zip code tabulation area"}
MAP_TOOL_HINT = "Hint: Use the get_demographic_data tool when answering geographic visualization questions."
TIME_SERIES_TOOL_HINT = "Hint: Use the get_demographic_time_series tool when users ask about change over time or trends."


def _normalize_tool_value(value: Any) -> Any:
    """Convert protobuf marshalled values into plain Python types for tool execution."""
    if isinstance(value, RepeatedComposite):
        return [_normalize_tool_value(item) for item in list(value)]
    if isinstance(value, dict):
        return {key: _normalize_tool_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_tool_value(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _normalize_tool_args(raw_args: Dict[str, Any]) -> Dict[str, Any]:
    return {key: _normalize_tool_value(value) for key, value in raw_args.items()}


def truncate_history(history: List[Dict[str, Any]] | None, max_messages: int = DEFAULT_HISTORY_LIMIT) -> List[Dict[str, Any]]:
    """Return only the most recent chat messages to keep prompt size small."""
    if not history:
        return []
    return history[-max_messages:]


def build_query_prompt(user_query: str, is_map_request: bool, is_time_series_request: bool) -> str:
    """Append lightweight hints for map or time-series requests without duplicating the system prompt."""
    hints: List[str] = []
    if is_map_request:
        hints.append(MAP_TOOL_HINT)
    if is_time_series_request:
        hints.append(TIME_SERIES_TOOL_HINT)
    if hints:
        return f"{user_query}\n\n" + "\n".join(hints)
    return user_query


def detect_time_series_request(user_query: str) -> bool:
    """Heuristically determine if the query is asking about change over time or trends."""
    query_lower = user_query.lower()
    time_keywords = [
        "over time",
        "time series",
        "trend",
        "since ",
        "year over year",
        "year-by-year",
        "historical",
        "change from",
        "changes from",
        "growth from",
        "growth since",
        "timeline",
    ]
    if any(keyword in query_lower for keyword in time_keywords):
        return True

    # Look for multiple year references (e.g., 2010 and 2020) to infer a range
    years_found = [token for token in query_lower.split() if token.isdigit() and len(token) == 4]
    unique_years = {year for year in years_found if year.startswith("19") or year.startswith("20")}
    return len(unique_years) >= 2


def summarize_tool_result(data: Any, args: Dict[str, Any], top_n: int = 5) -> Dict[str, Any]:
    """Produce a compact summary of tool results for the LLM."""
    if not isinstance(data, list) or not data:
        return {
            "summary": {
                "total_records": 0,
                "geography_level": args.get("geography_level"),
                "variables": args.get("variables"),
                "derived_metrics": args.get("derived_metrics"),
            },
            "samples": [],
        }

    fields = [str(key) for key in data[0].keys()]
    samples: List[Dict[str, Any]] = []
    for item in data[:top_n]:
        sample: Dict[str, Any] = {}
        if "NAME" in item:
            sample["NAME"] = item["NAME"]
        for key, value in item.items():
            if key in NON_VALUE_KEYS or key == "NAME":
                continue
            if isinstance(value, (int, float, str)):
                sample[key] = value
        samples.append(sample)

    return {
        "summary": {
            "total_records": len(data),
            "geography_level": args.get("geography_level"),
            "variables": args.get("variables"),
            "derived_metrics": args.get("derived_metrics"),
            "fields": fields,
        },
        "samples": samples,
    }


def _safe_float(value: Any) -> float | None:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            return float(value.replace(",", ""))
    except ValueError:
        return None
    return None


def _format_value(value: float | None) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1_000_000:
        return f"{value/1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value/1_000:.1f}K"
    if value.is_integer():
        return f"{int(value)}"
    return f"{value:.2f}"


def generate_basic_insights(data: List[Dict[str, Any]], variable_id: str, variable_label: str) -> List[str]:
    """Create lightweight insights without a second LLM round-trip."""
    numeric_rows: List[Tuple[float, str]] = []
    for row in data:
        value = _safe_float(row.get(variable_id))
        if value is None:
            continue
        numeric_rows.append((value, row.get("NAME", "Unknown")))

    if not numeric_rows:
        return []

    numeric_rows.sort()
    min_value, min_name = numeric_rows[0]
    max_value, max_name = numeric_rows[-1]
    mid = len(numeric_rows) // 2
    median_value, median_name = numeric_rows[mid]

    spread = max_value - min_value
    insights = [
        f"{max_name} reports the highest {variable_label} at {_format_value(max_value)}.",
        f"{min_name} has the lowest {variable_label} at {_format_value(min_value)}.",
    ]

    if len(numeric_rows) > 2:
        insights.append(
            f"Median entity ({median_name}) sits at {_format_value(median_value)}, showing overall spread of {_format_value(spread)}."
        )

    return insights


def build_time_series_dashboard(
    tool_result: Dict[str, Any],
    args: Dict[str, Any],
    total_prompt_tokens: int,
    total_completion_tokens: int,
) -> Dict[str, Any]:
    if not isinstance(tool_result, dict):
        return {
            "response": "Sorry, the time-series tool did not return structured data.",
            "token_usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
            },
        }

    if "error" in tool_result:
        return {
            "response": tool_result.get("error", "Time-series tool reported an error."),
            "token_usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
            },
        }

    data = tool_result.get("data", [])
    metadata = dict(tool_result.get("metadata", {}))
    series = tool_result.get("series", [])
    metrics = tool_result.get("metrics", {})

    variable_labels = get_variable_labels()
    primary_code = metadata.get("primary_variable_code")

    fallback_label = None
    requested_variables = args.get("variables") or []
    if requested_variables:
        fallback_label = variable_labels.get(requested_variables[0], requested_variables[0])
    elif args.get("derived_metrics"):
        fallback_label = variable_labels.get(args["derived_metrics"][0], args["derived_metrics"][0])

    variable_label = variable_labels.get(primary_code, fallback_label or primary_code or "Value")

    variable_code_map = metadata.get("variable_codes", {})

    label_keys: List[str] = []
    for user_var in requested_variables:
        label_keys.append(user_var)
        code = variable_code_map.get(user_var)
        if code:
            label_keys.append(code)
    for metric_key in args.get("derived_metrics") or []:
        label_keys.append(metric_key)
    if primary_code:
        label_keys.append(primary_code)

    metadata_labels: Dict[str, str] = metadata.get("variable_labels", {}) or {}
    for key in label_keys:
        if not key:
            continue
        if key not in metadata_labels:
            label_value = variable_labels.get(key)
            if not label_value and isinstance(key, str):
                label_value = key.replace("_", " ").title()
            metadata_labels[key] = label_value or str(key)

    metadata.setdefault("primary_variable_code", primary_code)
    metadata["primary_variable_label"] = metadata_labels.get(primary_code, variable_label)
    metadata["variable_labels"] = metadata_labels

    insights: List[str] = []
    if data and primary_code:
        latest_year = metadata.get("end_year")
        latest_rows = [row for row in data if latest_year is not None and row.get("year") == latest_year]
        baseline_rows = latest_rows or data
        insights = generate_basic_insights(baseline_rows, primary_code, variable_label)

    largest_increase = metrics.get("largest_increase") or {}
    if largest_increase.get("metrics"):
        change_value = largest_increase["metrics"].get("absolute_change")
        insights.append(
            f"{largest_increase.get('NAME', 'This geography')} shows the largest change at {_format_value(change_value)} between {metadata.get('start_year')} and {metadata.get('end_year')}."
        )

    fastest_growth = metrics.get("fastest_growth") or {}
    if fastest_growth.get("metrics") and fastest_growth["metrics"].get("percent_change") is not None:
        percent_change = fastest_growth["metrics"].get("percent_change")
        insights.append(
            f"Fastest growth occurs in {fastest_growth.get('NAME', 'this geography')} at {percent_change:.1f}% over the period."
        )

    def _series_sort_key(entry: Dict[str, Any]) -> float:
        metrics_block = entry.get("metrics", {})
        end_value = metrics_block.get("end_value")
        if end_value is None:
            return float("-inf")
        try:
            return float(end_value)
        except (TypeError, ValueError):
            return float("-inf")

    top_series = sorted(series, key=_series_sort_key, reverse=True)[:10]

    chart_series = []
    for entry in top_series:
        values = [
            {"year": point.get("year"), "value": point.get("value")}
            for point in entry.get("values", [])
        ]
        chart_series.append(
            {
                "geography_id": entry.get("geography_id"),
                "name": entry.get("NAME", entry.get("geography_id")),
                "values": values,
            }
        )

    charts = []
    if chart_series:
        charts.append(
            {
                "chart_type": "line_chart",
                "title": f"{variable_label} ({metadata.get('start_year')}–{metadata.get('end_year')})",
                "series": chart_series,
            }
        )

    summary_text = (
        f"Time-series analysis of {variable_label} across {metadata.get('series_count', len(series))} "
        f"{metadata.get('geography_level', 'regions')} from {metadata.get('start_year')} to {metadata.get('end_year')}."
    )

    errors = tool_result.get("errors", {})

    try:
        serializable_data = json.loads(json.dumps({
            "data": data,
            "series": series,
            "metadata": metadata,
            "metrics": metrics,
            "errors": errors,
        }))
    except TypeError:
        serializable_data = {
            "data": data,
            "series": series,
            "metadata": metadata,
            "metrics": metrics,
            "errors": errors,
        }

    return {
        "type": "time_series_dashboard",
        "summary_text": summary_text,
        "data": serializable_data.get("data", data),
        "series": serializable_data.get("series", series),
        "charts": charts,
        "metrics": serializable_data.get("metrics", metrics),
        "metadata": serializable_data.get("metadata", metadata),
        "errors": serializable_data.get("errors", errors),
        "insights": insights,
        "token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
        },
    }
async def get_ai_response(user_query: str, chat_history: list = None) -> dict:
    """
    Generates a response from the Gemini Pro model, potentially using tools.
    Implements a two-step process for tool usage:
    1. LLM suggests a tool call.
    2. We execute the tool and send the result back to the LLM for interpretation.
    
    For Phase 3, returns structured responses for map requests.
    Tracks token usage for each response.
    """
    # Initialize token counters
    total_prompt_tokens = 0
    total_completion_tokens = 0
    
    try:
        map_keywords = ['map', 'show me', 'display', 'visualize', 'chart', 'counties', 'states', 'income', 'population', 'demographic']
        lower_query = user_query.lower()
        is_map_request = any(keyword in lower_query for keyword in map_keywords)
        is_time_series_request = detect_time_series_request(user_query)

        trimmed_history = truncate_history(chat_history)
        current_chat_session = model.start_chat(history=trimmed_history)

        query_for_llm = build_query_prompt(user_query, is_map_request, is_time_series_request)

        print(
            f"\nSending to Gemini (1st call): Query: '{user_query}' "
            f"(Map request: {is_map_request}, Time-series: {is_time_series_request})"
        )
        response = await current_chat_session.send_message_async(query_for_llm)
        
        # Track token usage from first LLM call
        if response.usage_metadata:
            total_prompt_tokens += response.usage_metadata.prompt_token_count
            total_completion_tokens += response.usage_metadata.candidates_token_count
            print(f"Token usage (1st call): Prompt={response.usage_metadata.prompt_token_count}, Completion={response.usage_metadata.candidates_token_count}")
        
        # It's good practice to check if candidates exist and have content
        if not response.candidates or not response.candidates[0].content.parts:
            return {
                "response": "AI did not return a valid response structure.",
                "token_usage": {
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "total_tokens": total_prompt_tokens + total_completion_tokens
                }
            }
        response_part = response.candidates[0].content.parts[0]

        if hasattr(response_part, 'function_call') and response_part.function_call:
            function_call = response_part.function_call
            function_name = function_call.name
            args = _normalize_tool_args(dict(function_call.args))

            print(f"Gemini wants to call function: {function_name} with args: {args}")

            if function_name in AVAILABLE_FUNCTIONS:
                actual_function = AVAILABLE_FUNCTIONS[function_name]
                function_response_content_for_llm = None # Renamed for clarity
                try:
                    debug_arg_types = {key: str(type(value)) for key, value in args.items()}
                    print(f"Function call argument types: {debug_arg_types}")
                    print(f"Executing tool: {function_name}")
                    if asyncio.iscoroutinefunction(actual_function):
                        tool_execution_result = await actual_function(**args)
                    else:
                        loop = asyncio.get_running_loop()
                        tool_execution_result = await loop.run_in_executor(None, actual_function, **args)
                    
                    record_count = len(tool_execution_result) if isinstance(tool_execution_result, list) else 'n/a'
                    print(f"Tool '{function_name}' executed. Result type: {type(tool_execution_result)}, records: {record_count}")
                    if function_name == "get_demographic_time_series":
                        print("Time-series response detected, constructing dashboard output.")
                        return build_time_series_dashboard(
                            tool_execution_result,
                            args,
                            total_prompt_tokens,
                            total_completion_tokens,
                        )
                    
                    # Phase 7: Check if this is a map/dashboard request and we have valid data
                    if is_map_request and function_name == "get_demographic_data" and isinstance(tool_execution_result, list) and tool_execution_result:
                        print("Dashboard request detected with valid data, creating structured response")
                        # tool_execution_result is already a list of data items
                        data_items = tool_execution_result

                        variable_labels = get_variable_labels()
                        
                        # Find the display variable - prioritize derived metrics, then regular variables
                        sample_item = data_items[0]
                        display_variable_id = None
                        
                        # First, check if we have any derived metrics (they take priority for display)
                        requested_derived_metrics = args.get("derived_metrics", [])
                        if requested_derived_metrics:
                            # Use the first derived metric as the display variable
                            for metric in requested_derived_metrics:
                                if metric in sample_item:
                                    display_variable_id = metric
                                    if isinstance(tool_execution_result, list):
                                        record_count = len(tool_execution_result)
                                    elif isinstance(tool_execution_result, dict):
                                        record_count = len(tool_execution_result.get("data", []))
                                    else:
                                        record_count = 'n/a'
                        
                        # If no derived metrics, find the first regular variable
                                    if function_name == "get_demographic_time_series" and isinstance(tool_execution_result, dict):
                                        print("Time-series request detected, creating structured time-series dashboard response")
                                        return build_time_series_dashboard(
                                            tool_execution_result,
                                            args,
                                            total_prompt_tokens,
                                            total_completion_tokens,
                                        )

                        if not display_variable_id:
                            requested_variables = args.get("variables", [])
                            for var in requested_variables:
                                if var in sample_item:
                                    display_variable_id = var
                                    break
                        
                        # Fallback: find any non-geographic variable
                        if not display_variable_id:
                            for key in sample_item.keys():
                                if key not in ['state', 'county', 'tract', 'place', 'zip code tabulation area']:
                                    display_variable_id = key
                                    break
                        
                        print(f"Found display_variable_id: {display_variable_id}")
                        
                        if display_variable_id:
                            # === Phase 7: Create Dashboard Data Response ===
                            
                            # 1. Get all variables present in the data
                            all_variables = []
                            for key in sample_item.keys():
                                if key not in ['state', 'county', 'tract', 'place', 'zip code tabulation area', 'NAME']:
                                    if key in variable_labels:
                                        all_variables.append({"id": key, "name": variable_labels[key]})
                            
                            # 2. Calculate summary statistics for all numeric variables
                            summary_statistics = {}
                            for var_info in all_variables:
                                var_id = var_info["id"]
                                stats = calculate_summary_statistics(data_items, var_id)
                                if stats:
                                    summary_statistics[var_id] = stats
                            
                            # 3. Prepare chart data (Top 5 entities by display variable)
                            chart_data = []
                            if display_variable_id in [item["id"] for item in all_variables]:
                                # Sort by display variable and get top 5
                                sorted_data = sorted(data_items, 
                                                   key=lambda x: float(x.get(display_variable_id, 0) or 0), 
                                                   reverse=True)[:5]
                                chart_data = [
                                    {"name": item.get("NAME", "Unknown"), "value": float(item.get(display_variable_id, 0) or 0)}
                                    for item in sorted_data
                                ]
                            
                            charts = [{
                                "chart_type": "bar_chart",
                                "title": f"Top 5 {args.get('geography_level', 'entities').title()} by {variable_labels.get(display_variable_id, display_variable_id)}",
                                "variable_id": display_variable_id,
                                "data": chart_data
                            }] if chart_data else []
                            
                            # 4. Generate heuristic insights without extra LLM calls
                            variable_label = variable_labels.get(display_variable_id, display_variable_id)
                            insights = generate_basic_insights(data_items, display_variable_id, variable_label)
                            summary_text = f"Analysis of {variable_label} across {len(data_items)} {args.get('geography_level', 'entities')}"
                            
                            # 5. Ensure data is JSON serializable
                            import json
                            try:
                                serializable_data = json.loads(json.dumps(data_items))
                            except:
                                serializable_data = data_items  # fallback
                            
                            # 6. Construct dashboard response
                            response = {
                                "type": "dashboard_data",
                                "summary_text": summary_text,
                                "data": serializable_data,
                                "metadata": {
                                    "geography_level": str(args.get("geography_level", "")),
                                    "display_variable_id": str(display_variable_id),
                                    "variable_labels": variable_labels,
                                    "available_variables": all_variables
                                },
                                "charts": charts,
                                "summary_statistics": summary_statistics,
                                "insights": insights,
                                "token_usage": {
                                    "prompt_tokens": total_prompt_tokens,
                                    "completion_tokens": total_completion_tokens,
                                    "total_tokens": total_prompt_tokens + total_completion_tokens
                                }
                            }
                            print(f"Returning dashboard response")
                            return response

                    # Construct the function response as a dictionary for the LLM
                    # This structure is what the Gemini API expects for function responses.
                    summarized_content = summarize_tool_result(tool_execution_result, args)
                    function_response_content_for_llm = [
                        {
                            "function_response": {
                                "name": function_name,
                                "response": {
                                    "content": summarized_content,
                                }
                            }
                        }
                    ]

                except Exception as e:
                    import traceback
                    print(f"Error executing function {function_name}: {e}")
                    traceback.print_exc()
                    function_response_content_for_llm = [
                        {
                            "function_response": {
                                "name": function_name,
                                "response": {
                                    "content": {"error": f"Error executing function {function_name}: {str(e)}"},
                                }
                            }
                        }
                    ]
                
                print(f"\nSending to Gemini (2nd call): Tool response for {function_name}")
                # Send the list containing the function response dictionary
                response_after_tool = await current_chat_session.send_message_async(function_response_content_for_llm)
                
                # Track token usage from second LLM call
                if response_after_tool.usage_metadata:
                    total_prompt_tokens += response_after_tool.usage_metadata.prompt_token_count
                    total_completion_tokens += response_after_tool.usage_metadata.candidates_token_count
                    print(f"Token usage (2nd call): Prompt={response_after_tool.usage_metadata.prompt_token_count}, Completion={response_after_tool.usage_metadata.candidates_token_count}")
                
                if not response_after_tool.candidates or not response_after_tool.candidates[0].content.parts:
                    return {
                        "response": "AI did not return a valid response structure after tool execution.",
                        "token_usage": {
                            "prompt_tokens": total_prompt_tokens,
                            "completion_tokens": total_completion_tokens,
                            "total_tokens": total_prompt_tokens + total_completion_tokens
                        }
                    }
                final_response_part = response_after_tool.candidates[0].content.parts[0]

                if hasattr(final_response_part, 'text'):
                    return {
                        "response": final_response_part.text,
                        "token_usage": {
                            "prompt_tokens": total_prompt_tokens,
                            "completion_tokens": total_completion_tokens,
                            "total_tokens": total_prompt_tokens + total_completion_tokens
                        }
                    }
                else:
                    return {
                        "response": "AI processed tool output, but no text response was generated.",
                        "token_usage": {
                            "prompt_tokens": total_prompt_tokens,
                            "completion_tokens": total_completion_tokens,
                            "total_tokens": total_prompt_tokens + total_completion_tokens
                        }
                    }
            else:
                return {
                    "response": f"Error: Model tried to call unknown function '{function_name}'.",
                    "token_usage": {
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_prompt_tokens + total_completion_tokens
                    }
                }
        
        elif hasattr(response_part, 'text'):
            return {
                "response": response_part.text,
                "token_usage": {
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "total_tokens": total_prompt_tokens + total_completion_tokens
                }
            }
        
        return {
            "response": "Sorry, I couldn't generate a valid response (no function call or text).",
            "token_usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens
            }
        }

    except Exception as e:
        print(f"Error in get_ai_response: {e}")
        import traceback
        traceback.print_exc()
        return {
            "response": "Sorry, there was a critical error in the AI orchestration.",
            "token_usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens
            }
        }


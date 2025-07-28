import os
import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool 
from dotenv import load_dotenv
import asyncio

# Import the new tool and config for schema generation
from tools import get_demographic_data, calculate_summary_statistics # TEMP: absolute import for testing
from config import CENSUS_VARIABLE_MAP, GEOGRAPHY_HIERARCHY, DERIVED_METRICS_MAP # TEMP: absolute import for testing

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("WARNING: GOOGLE_API_KEY not found in environment variables.")
    print("The application will not work properly without this API key.")
    # For development/debugging, you might want to continue, but for production this should fail
    raise ValueError("GOOGLE_API_KEY not found in environment variables. Please add it.")
genai.configure(api_key=api_key)

# --- Dynamic Tool Schema Generation for get_demographic_data ---
def create_get_demographic_data_tool():
    user_friendly_variable_names = list(CENSUS_VARIABLE_MAP.keys())
    geography_level_names = list(GEOGRAPHY_HIERARCHY.keys())
    derived_metric_names = list(DERIVED_METRICS_MAP.keys())

    get_demographic_data_declaration = FunctionDeclaration(
        name="get_demographic_data",
        description="""Fetches demographic data from the US Census Bureau for data visualization and interactive maps. 

ALWAYS use this tool when users ask for:
- Maps (e.g., "map of population by state", "show me a map", "map median income")
- Charts or visualizations of demographic data
- County-level data for any state
- State-level data across the US
- Any demographic statistics (population, income, age, housing, etc.)
- Comparative queries (e.g., "Which states have more men than women?", "States with highest unemployment")

For MAP REQUESTS:
- Use geography_level="state" for US-wide state maps
- Use geography_level="county" for county maps within a state (requires state_name)
- The system will automatically create interactive choropleth maps

For COMPARATIVE QUERIES:
- Use derived_metrics for calculated comparisons (e.g., male_female_difference, unemployment_percentage)
- Derived metrics automatically compute differences, ratios, and percentages

For COUNTY REQUESTS: Always include the state_name parameter (e.g., "California", "Texas", "New York")""",
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
                # Simplified parameter descriptions for brevity in this test
                "state_name": {"type": "string", "description": "The name of the state (not required for state-level queries when getting all states)."},
                "county_name": {"type": "string", "description": "The name of the county."},
                "place_name": {"type": "string", "description": "The name of the place."},
                "tract_code": {"type": "string", "description": "The Census tract code."},
                "block_group_code": {"type": "string", "description": "The block group code."},
                "zip_code_tabulation_area": {"type": "string", "description": "The 5-digit ZCTA code."},
            },
            "required": ["geography_level"],
        },
    )
    # Ensure Tool is used correctly here
    return Tool(function_declarations=[get_demographic_data_declaration])

census_tool = create_get_demographic_data_tool()

model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    tools=[census_tool],
    system_instruction="""You are a helpful assistant that provides US Census demographic data and visualizations. When users ask for maps, charts, or data visualization, always use the get_demographic_data tool to fetch the required data. 

For US-wide maps, use geography_level='state'. For state-specific maps, use geography_level='county' and include the state_name parameter.

For comparative queries (e.g., "Which states have more men than women?", "States with highest unemployment"), use derived_metrics without needing variables:
- male_female_difference: Calculates difference between male and female population
- unemployment_percentage: Calculates unemployment rate as a percentage  
- owner_occupied_percentage: Calculates owner-occupied housing percentage

You can use EITHER variables OR derived_metrics or both. The geography_level is the only required parameter.

Available derived metrics: male_female_difference, unemployment_percentage, owner_occupied_percentage

When users ask comparative questions, determine the appropriate derived metric and use it to create meaningful visualizations."""
)

AVAILABLE_FUNCTIONS = {
    "get_demographic_data": get_demographic_data
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
        # Phase 3: Detect map requests with better keywords
        map_keywords = ['map', 'show me', 'display', 'visualize', 'chart', 'counties', 'states', 'income', 'population', 'demographic']
        is_map_request = any(keyword in user_query.lower() for keyword in map_keywords)
        
        current_chat_session = model.start_chat(history=chat_history or [])
        
        # Add system instruction for map requests
        system_instruction = """You are a Census data visualization assistant. When users ask for maps, demographic data, or statistics about states/counties, you should ALWAYS use the get_demographic_data tool. 

Examples that require the tool:
- "Map median income for California counties" → Use get_demographic_data with geography_level="county", state_name="California", variables=["median_household_income"]
- "Show population by state" → Use get_demographic_data with geography_level="state", variables=["total_population"]
- "Counties in Texas" → Use get_demographic_data with geography_level="county", state_name="Texas"
- "Which states have more men than women?" → Use get_demographic_data with geography_level="state", derived_metrics=["male_female_difference"]
- "States with highest unemployment" → Use get_demographic_data with geography_level="state", derived_metrics=["unemployment_percentage"]

For comparative queries, use derived_metrics instead of or in addition to variables.

The tool will provide data that gets automatically converted into interactive maps."""
        
        print(f"\nSending to Gemini (1st call): Query: '{user_query}' (Map request: {is_map_request})")
        
        # For map requests, prepend instruction
        if is_map_request:
            enhanced_query = f"{system_instruction}\n\nUser request: {user_query}"
            response = await current_chat_session.send_message_async(enhanced_query)
        else:
            response = await current_chat_session.send_message_async(user_query)
        
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
            args = dict(function_call.args)

            print(f"Gemini wants to call function: {function_name} with args: {args}")

            if function_name in AVAILABLE_FUNCTIONS:
                actual_function = AVAILABLE_FUNCTIONS[function_name]
                function_response_content_for_llm = None # Renamed for clarity
                try:
                    print(f"Executing tool: {function_name}")
                    if asyncio.iscoroutinefunction(actual_function):
                        tool_execution_result = await actual_function(**args)
                    else:
                        loop = asyncio.get_running_loop()
                        tool_execution_result = await loop.run_in_executor(None, actual_function, **args)
                    
                    print(f"Tool '{function_name}' executed. Result type: {type(tool_execution_result)}, Result: {tool_execution_result}")
                    
                    # Phase 7: Check if this is a map/dashboard request and we have valid data
                    if is_map_request and function_name == "get_demographic_data" and isinstance(tool_execution_result, list) and tool_execution_result:
                        print("Dashboard request detected with valid data, creating structured response")
                        # tool_execution_result is already a list of data items
                        data_items = tool_execution_result
                        
                        # Create variable labels mapping for human-readable names
                        variable_labels = {}
                        
                        # Add labels for regular variables (both human-readable keys and Census codes)
                        for var_key, census_code in CENSUS_VARIABLE_MAP.items():
                            human_readable_name = var_key.replace("_", " ").title()
                            variable_labels[var_key] = human_readable_name  # human-readable key -> name
                            variable_labels[census_code] = human_readable_name  # Census code -> name
                        
                        # Add labels for derived metrics
                        for metric_key, metric_info in DERIVED_METRICS_MAP.items():
                            variable_labels[metric_key] = metric_info["name"]
                        
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
                                    break
                        
                        # If no derived metrics, find the first regular variable
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
                            
                            # 4. Generate AI insights using a follow-up LLM call
                            insights_prompt = f"""Based on the following demographic data analysis, generate 2-3 concise bullet-point insights:

Data Summary:
- Geography Level: {args.get('geography_level', 'unknown')}
- Primary Variable: {variable_labels.get(display_variable_id, display_variable_id)}
- Number of Entities: {len(data_items)}

Statistics for {variable_labels.get(display_variable_id, display_variable_id)}:
- Mean: {summary_statistics.get(display_variable_id, {}).get('mean', 'N/A')}
- Median: {summary_statistics.get(display_variable_id, {}).get('median', 'N/A')}
- Range: {summary_statistics.get(display_variable_id, {}).get('min', 'N/A')} to {summary_statistics.get(display_variable_id, {}).get('max', 'N/A')}
- Highest: {summary_statistics.get(display_variable_id, {}).get('max_entity_name', 'N/A')}
- Lowest: {summary_statistics.get(display_variable_id, {}).get('min_entity_name', 'N/A')}

Chart shows: Top 5 entities with highest values

Provide insights as a JSON array of strings, for example: ["Insight 1 here", "Insight 2 here"]"""

                            # Make follow-up call to LLM for insights
                            insights = []
                            summary_text = f"Analysis of {variable_labels.get(display_variable_id, display_variable_id)} across {len(data_items)} {args.get('geography_level', 'entities')}."
                            
                            try:
                                insights_response = await current_chat_session.send_message_async(insights_prompt)
                                if insights_response.usage_metadata:
                                    total_prompt_tokens += insights_response.usage_metadata.prompt_token_count
                                    total_completion_tokens += insights_response.usage_metadata.candidates_token_count
                                
                                # Try to parse insights from response
                                insights_text = insights_response.text
                                # Extract insights - look for JSON array or bullet points
                                import re
                                import json
                                
                                # Try to find JSON array first
                                json_match = re.search(r'\[.*?\]', insights_text, re.DOTALL)
                                if json_match:
                                    try:
                                        insights = json.loads(json_match.group())
                                    except:
                                        pass
                                
                                # Fallback: extract bullet points or numbered items
                                if not insights:
                                    bullet_pattern = r'(?:[-•*]|\d+\.)\s*(.+?)(?=\n|$)'
                                    matches = re.findall(bullet_pattern, insights_text)
                                    insights = [match.strip() for match in matches if match.strip()]
                                
                                # Extract clean summary text (remove JSON parts and clean up)
                                clean_text = re.sub(r'\[.*?\]', '', insights_text, flags=re.DOTALL)  # Remove JSON arrays
                                clean_text = re.sub(r'^```.*?```', '', clean_text, flags=re.DOTALL | re.MULTILINE)  # Remove code blocks
                                clean_text = re.sub(r'json\s*', '', clean_text, flags=re.IGNORECASE)  # Remove "json" keywords
                                clean_text = clean_text.strip()
                                
                                # Use cleaned text as summary if it's descriptive and doesn't look like JSON
                                if len(clean_text) > 50 and not clean_text.startswith('[') and not clean_text.startswith('{'):
                                    summary_text = clean_text[:300] + "..." if len(clean_text) > 300 else clean_text
                                    
                            except Exception as e:
                                print(f"Error generating insights: {e}")
                                insights = [f"Analysis of {len(data_items)} {args.get('geography_level', 'entities')} showing {variable_labels.get(display_variable_id, display_variable_id)}"]
                            
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
                    function_response_content_for_llm = [
                        {
                            "function_response": {
                                "name": function_name,
                                "response": {
                                    "content": tool_execution_result, # The actual data from our function
                                }
                            }
                        }
                    ]

                except Exception as e:
                    print(f"Error executing function {function_name}: {e}")
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


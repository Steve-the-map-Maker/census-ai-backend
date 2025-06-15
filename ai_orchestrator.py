import os
import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool 
from dotenv import load_dotenv
import asyncio

# Import the new tool and config for schema generation
from tools import get_demographic_data # TEMP: absolute import for testing
from config import CENSUS_VARIABLE_MAP, GEOGRAPHY_HIERARCHY # TEMP: absolute import for testing

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("GOOGLE_API_KEY not found in .env file. Please add it.")
genai.configure(api_key=api_key)

# --- Dynamic Tool Schema Generation for get_demographic_data ---
def create_get_demographic_data_tool():
    user_friendly_variable_names = list(CENSUS_VARIABLE_MAP.keys())
    geography_level_names = list(GEOGRAPHY_HIERARCHY.keys())

    get_demographic_data_declaration = FunctionDeclaration(
        name="get_demographic_data",
        description="""Fetches demographic data from the US Census Bureau for data visualization and interactive maps. 

ALWAYS use this tool when users ask for:
- Maps (e.g., "map of population by state", "show me a map", "map median income")
- Charts or visualizations of demographic data
- County-level data for any state
- State-level data across the US
- Any demographic statistics (population, income, age, housing, etc.)

For MAP REQUESTS:
- Use geography_level="state" for US-wide state maps
- Use geography_level="county" for county maps within a state (requires state_name)
- The system will automatically create interactive choropleth maps

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
                # Simplified parameter descriptions for brevity in this test
                "state_name": {"type": "string", "description": "The name of the state (not required for state-level queries when getting all states)."},
                "county_name": {"type": "string", "description": "The name of the county."},
                "place_name": {"type": "string", "description": "The name of the place."},
                "tract_code": {"type": "string", "description": "The Census tract code."},
                "block_group_code": {"type": "string", "description": "The block group code."},
                "zip_code_tabulation_area": {"type": "string", "description": "The 5-digit ZCTA code."},
            },
            "required": ["geography_level", "variables"],
        },
    )
    # Ensure Tool is used correctly here
    return Tool(function_declarations=[get_demographic_data_declaration])

census_tool = create_get_demographic_data_tool()

model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    tools=[census_tool],
    system_instruction="You are a helpful assistant that provides US Census demographic data and visualizations. When users ask for maps, charts, or data visualization, always use the get_demographic_data tool to fetch the required data. For US-wide maps, use geography_level='state'. For state-specific maps, use geography_level='county' and include the state_name parameter."
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
    """
    try:
        # Phase 3: Detect map requests with better keywords
        map_keywords = ['map', 'show me', 'display', 'visualize', 'chart', 'counties', 'states', 'income', 'population', 'demographic']
        is_map_request = any(keyword in user_query.lower() for keyword in map_keywords)
        
        current_chat_session = model.start_chat(history=chat_history or [])
        
        # Add system instruction for map requests
        system_instruction = """You are a Census data visualization assistant. When users ask for maps, demographic data, or statistics about states/counties, you should ALWAYS use the get_demographic_data tool. 

Examples that require the tool:
- "Map median income for California counties" → Use get_demographic_data with geography_level="county", state_name="California"
- "Show population by state" → Use get_demographic_data with geography_level="state"
- "Counties in Texas" → Use get_demographic_data with geography_level="county", state_name="Texas"

The tool will provide data that gets automatically converted into interactive maps."""
        
        print(f"\nSending to Gemini (1st call): Query: '{user_query}' (Map request: {is_map_request})")
        
        # For map requests, prepend instruction
        if is_map_request:
            enhanced_query = f"{system_instruction}\n\nUser request: {user_query}"
            response = await current_chat_session.send_message_async(enhanced_query)
        else:
            response = await current_chat_session.send_message_async(user_query)
        
        # It's good practice to check if candidates exist and have content
        if not response.candidates or not response.candidates[0].content.parts:
            return {"response": "AI did not return a valid response structure."}
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
                    
                    # Phase 3: Check if this is a map request and we have valid data
                    if is_map_request and function_name == "get_demographic_data" and isinstance(tool_execution_result, list) and tool_execution_result:
                        print("Map request detected with valid data, creating structured response")
                        # tool_execution_result is already a list of data items
                        data_items = tool_execution_result
                        # Find the first non-FIPS variable (these are typically the demographic data)
                        sample_item = data_items[0]
                        variable_id = None
                        for key in sample_item.keys():
                            if key not in ['state', 'county', 'tract', 'place', 'zip code tabulation area']:
                                variable_id = key
                                break
                        
                        print(f"Found variable_id: {variable_id}")
                        
                        if variable_id:
                            # Return structured map response - ensure all data is JSON serializable
                            import json
                            try:
                                serializable_data = json.loads(json.dumps(data_items))
                            except:
                                serializable_data = data_items  # fallback
                            
                            response = {
                                "type": "map",
                                "data": serializable_data,
                                "metadata": {
                                    "geography_level": str(args.get("geography_level", "")),
                                    "variable_id": str(variable_id),
                                    "variables": list(args.get("variables", [])),
                                    "state_name": str(args.get("state_name")) if args.get("state_name") else None
                                },
                                "summary": f"Map showing {args.get('variables', ['data'])[0]} at {args.get('geography_level', 'unknown')} level"
                            }
                            print(f"Returning map response: {response}")
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
                
                if not response_after_tool.candidates or not response_after_tool.candidates[0].content.parts:
                    return {"response": "AI did not return a valid response structure after tool execution."}
                final_response_part = response_after_tool.candidates[0].content.parts[0]

                if hasattr(final_response_part, 'text'):
                    return {"response": final_response_part.text}
                else:
                    return {"response": "AI processed tool output, but no text response was generated."}
            else:
                return {"response": f"Error: Model tried to call unknown function '{function_name}'."}
        
        elif hasattr(response_part, 'text'):
            return {"response": response_part.text}
        
        return {"response": "Sorry, I couldn't generate a valid response (no function call or text)."}

    except Exception as e:
        print(f"Error in get_ai_response: {e}")
        import traceback
        traceback.print_exc()
        return {"response": "Sorry, there was a critical error in the AI orchestration."}

if __name__ == '__main__':
    async def main_test():
        print("=== COMPREHENSIVE PHASE 2 TESTING ===\n")
        
        # Test Case 1: US Population (already working)
        print("--- Test Case 1: US Total Population ---")
        response1 = await get_ai_response("What is the total population of the United States?")
        print(f"AI Response 1: {response1}\n")

        # Test Case 2: State-level data with multiple variables
        print("--- Test Case 2: Oregon Population and Median Age ---")  
        response2 = await get_ai_response("What is the total population and median age in Oregon?")
        print(f"AI Response 2: {response2}\n")

        # Test Case 3: Case-insensitive state name
        print("--- Test Case 3: Lowercase State Name ---")
        response3 = await get_ai_response("What is the population of california?")
        print(f"AI Response 3: {response3}\n")

        # Test Case 4: Invalid state (error handling)
        print("--- Test Case 4: Invalid State Name ---")
        response4 = await get_ai_response("What is the population of Wakanda?")
        print(f"AI Response 4: {response4}\n")

        # Test Case 5: Unsupported variable (error handling)
        print("--- Test Case 5: Unsupported Variable ---")
        response5 = await get_ai_response("How many dogs live in California?")
        print(f"AI Response 5: {response5}\n")

    asyncio.run(main_test())

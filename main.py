from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
import ai_orchestrator # Import the new AI orchestrator - back to absolute since main.py is at package root

# Determine the environment and load the appropriate .env file
env = os.getenv("ENVIRONMENT", "development")

# Debug logging to see what environment we're in
print(f"Environment detected: {env}")
print(f"Available env vars: RENDER={os.getenv('RENDER')}, RENDER_SERVICE_NAME={os.getenv('RENDER_SERVICE_NAME')}")

# Check if we're on Render (production) by checking for Render-specific environment variables
is_production = os.getenv("RENDER") or os.getenv("RENDER_SERVICE_NAME") or env == "production"

if is_production:
    # For production, variables are loaded from the hosting environment (Render)
    print("Running in PRODUCTION mode")
    origins = [
        "https://census-ai-frontend.onrender.com",
        "https://census-ai-frontend.onrender.com/",  # Include trailing slash variant
    ]
else:
    # For local development, load variables from .env.development
    print("Running in DEVELOPMENT mode")
    load_dotenv(dotenv_path=".env.development")
    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

print(f"CORS Origins configured: {origins}")

app = FastAPI()

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Accept-Language",
        "Content-Language",
        "Content-Type",
        "Authorization",
        "X-Requested-With",
    ],
    expose_headers=["*"],
)

print("CORS middleware configured successfully")

@app.get("/")
async def read_root():
    return {"message": "Census AI Backend is running"}

@app.post("/ask_ai")
async def ask_ai(query_data: dict):
    user_query = query_data.get("query")
    if not user_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    print(f"Received query: {user_query}")
    try:
        ai_response = await ai_orchestrator.get_ai_response(user_query)
        # Phase 3: ai_response is now a dict, not just a string
        print(f"AI response: {ai_response}")
        
        # Log token usage if available
        if isinstance(ai_response, dict) and "token_usage" in ai_response:
            token_info = ai_response["token_usage"]
            print(f"Token usage - Prompt: {token_info.get('prompt_tokens', 0)}, "
                  f"Completion: {token_info.get('completion_tokens', 0)}, "
                  f"Total: {token_info.get('total_tokens', 0)}")
        
        return ai_response
    except Exception as e:
        print(f"Error during AI processing: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error processing your request with the AI: {str(e)}")

@app.options("/ask_ai")
async def ask_ai_options():
    """Handle CORS preflight requests"""
    return {"message": "OK"}



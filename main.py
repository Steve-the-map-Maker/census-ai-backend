from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
import ai_orchestrator # Import the new AI orchestrator - back to absolute since main.py is at package root

# Determine the environment and load the appropriate .env file
env = os.getenv("ENVIRONMENT", "development")

if env == "development":
    # For local development, load variables from .env.development
    load_dotenv(dotenv_path=".env.development")
    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
else:
    # For production, variables are loaded from the hosting environment (Render)
    load_dotenv()  # Load default .env if it exists
    origins = [
        "https://census-ai-frontend.onrender.com"
    ]

app = FastAPI()

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

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



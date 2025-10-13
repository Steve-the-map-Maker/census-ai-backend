from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field

import ai_orchestrator # Import the new AI orchestrator - back to absolute since main.py is at package root

# Determine the environment - check for any production indicators
env = os.getenv("ENVIRONMENT", "development")
render_vars = os.getenv("RENDER") or os.getenv("RENDER_SERVICE_NAME") or os.getenv("RENDER_SERVICE_ID") or os.getenv("RENDER_EXTERNAL_HOSTNAME")

# Debug logging to see what environment we're in
print(f"Environment detected: {env}")
print(f"Render vars: RENDER={os.getenv('RENDER')}, RENDER_SERVICE_NAME={os.getenv('RENDER_SERVICE_NAME')}")
print(f"RENDER_SERVICE_ID={os.getenv('RENDER_SERVICE_ID')}, RENDER_EXTERNAL_HOSTNAME={os.getenv('RENDER_EXTERNAL_HOSTNAME')}")

# Check if we're on Render (production) - be more aggressive about detecting production
is_production = render_vars or env == "production" or "render.com" in str(os.getenv("RENDER_EXTERNAL_HOSTNAME", ""))

if is_production:
    # For production, variables are loaded from the hosting environment (Render)
    print("Running in PRODUCTION mode")
    origins = [
        "https://census-ai-frontend.onrender.com",
        "https://census-ai-frontend.onrender.com/",  # Include trailing slash variant
        "*"  # Temporary wildcard for debugging
    ]
else:
    # For local development, load variables from .env.development
    print("Running in DEVELOPMENT mode")
    load_dotenv(dotenv_path=".env.development")
    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]
    

print(f"CORS Origins configured: {origins}")

app = FastAPI()

# Temporary request/response logging to diagnose 400 preflight errors
@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"Incoming request: {request.method} {request.url}")
    print(f"  Headers: {dict(request.headers)}")
    response = await call_next(request)
    print(f"Response status: {response.status_code} for {request.method} {request.url}")
    return response

# CORS middleware configuration - more permissive for production debugging
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
    expose_headers=["*"],
)

print("CORS middleware configured successfully")

@app.get("/")
async def read_root():
    return {"message": "Census AI Backend is running"}

class AskAIRequest(BaseModel):
    """Typed request payload for /ask_ai."""

    query: str = Field(..., description="User's natural-language query")
    conversation_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional conversational context payload captured on the frontend",
    )


@app.post("/ask_ai")
async def ask_ai(query_data: AskAIRequest):
    user_query = query_data.query.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    print(f"Received query: {user_query}")
    try:
        ai_response = await ai_orchestrator.get_ai_response(
            user_query,
            conversation_context=query_data.conversation_context,
        )
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
async def ask_ai_options(request: Request) -> Response:
    """Handle CORS preflight requests and log headers for debugging."""
    print("Received CORS preflight for /ask_ai with headers:")
    for header, value in request.headers.items():
        print(f"  {header}: {value}")
    return Response(status_code=200)



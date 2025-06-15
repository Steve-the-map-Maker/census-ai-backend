from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
import ai_orchestrator # Import the new AI orchestrator - back to absolute since main.py is at package root

load_dotenv()

app = FastAPI()

# CORS middleware configuration
origins = [
    "http://localhost:5173",  # Default Vite frontend URL
    "http://127.0.0.1:5173", # Also common for Vite
    # Add any other origins if your frontend is served from a different port/domain
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
        ai_response_text = await ai_orchestrator.get_ai_response(user_query)
        return {"response": ai_response_text}
    except Exception as e:
        print(f"Error during AI processing: {e}")
        raise HTTPException(status_code=500, detail="Error processing your request with the AI.")

# Placeholder for GOOGLE_API_KEY, will be used in ai_orchestrator.py
# GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
# if not GOOGLE_API_KEY:
#     print("Warning: GOOGLE_API_KEY not found in .env file.")

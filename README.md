🚀 Quick Start Summary:
For the backend (with virtual environment):

For the frontend:

1.  Navigate to the frontend directory:
```bash
cd census-ai-frontend
```

2.  Install dependencies:
```bash
npm install
```

3.  Start the development server:
```bash
npm run dev
```

# Census AI Backend

This backend service powers the Natural Language Census Data Visualizer with **full AI-driven Census data retrieval capabilities**. It integrates Google Gemini Pro LLM with the U.S. Census Bureau API to answer natural language queries about demographics, economics, housing, and social data.

## 🚀 **PHASE 2 COMPLETE** - Features Include:
- **AI-Powered Natural Language Processing**: Ask questions like "What is the population of California?" 
- **Comprehensive Census Data Access**: 17+ variables across Demographics, Economics, Housing, Education
- **Geographic Intelligence**: Supports US, state, county, place, tract, and ZCTA levels
- **Smart Geography Validation**: Handles case-insensitive state names, validates requirements
- **Robust Error Handling**: Graceful responses for invalid locations or unsupported queries
- **Two-Step AI Orchestration**: LLM → Tool Execution → Data Interpretation → Natural Response

## Technology Stack
- **Python 3.12+**
- **FastAPI** - Modern async web framework
- **Uvicorn** - ASGI server
- **Google Gemini Pro** - LLM for natural language processing
- **U.S. Census Bureau API** - Official demographic data source
- **httpx** - Async HTTP client for API calls

## Setup Instructions

### Prerequisites
- Python 3.12+ installed
- Google AI API key ([Get one here](https://aistudio.google.com/app/apikey))
- U.S. Census Bureau API key ([Get one here](https://www.census.gov/data/developers/data-sets.html))

### 1. Environment Setup
```bash
# Navigate to the backend directory
cd census-ai-backend

# Create and activate Python virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install all dependencies
pip install fastapi uvicorn python-dotenv google-generativeai httpx
```

### 2. Environment Variables
Create a `.env` file in the `census-ai-backend` directory:
```bash
# Required API Keys
GOOGLE_API_KEY=your_google_gemini_api_key_here
CENSUS_API_KEY=your_census_bureau_api_key_here
```

### 3. Start the Backend Server
```bash
# From the census-ai-backend directory with venv activated
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The backend will be available at: **http://localhost:8000**

## 🎯 **Starting Both Services (Full Stack)**

### Option 1: Start Both Services Separately

**Terminal 1 - Backend:**
```bash
cd census-ai-backend
source venv/bin/activate  # Activate Python virtual environment
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd census-ai-frontend
npm run dev  # Starts on http://localhost:5173 or next available port
```

### Option 2: Quick Start Script (Recommended)
From the project root directory:
```bash
# Make sure backend venv is set up first (see above)
cd census-ai-backend && source venv/bin/activate && uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
cd ../census-ai-frontend && npm run dev
```

## 📊 **Supported Census Queries**

The system can answer natural language questions about:

### **Demographics**
- Total population, median age, male/female population

### **Economics** 
- Median household income, per capita income, poverty rates, employment/unemployment

### **Housing**
- Total housing units, owner/renter occupied units, median home values, median rent

### **Education & Social**
- Bachelor's degree rates, high school graduation, foreign-born population

### **Geographic Levels**
- **US**: National data
- **State**: All 50 states + DC + territories (case-insensitive)
- **County**: County-level data (requires state)
- **Place**: Cities, towns, CDPs (requires state)
- **ZCTA**: ZIP Code Tabulation Areas
- **Tract**: Census tracts (requires state and county)

## 🧪 **Example Queries**

Try these in the chat interface:
- `"What is the total population of the United States?"`
- `"What is the population and median age in Oregon?"`
- `"Compare median household income between california and texas"`
- `"What is the unemployment rate in Florida?"`
- `"Show me housing data for New York"`

## 🔧 **API Endpoints**

### POST `/ask_ai`
**Request:**
```json
{
  "query": "What is the population of California?"
}
```

**Response:**
```json
{
  "response": "The population of California is 39,356,104."
}
```

## 🚨 **Troubleshooting**

### Common Issues:
1. **Import Errors**: Ensure you're running from the correct directory with the virtual environment activated
2. **Port Conflicts**: Backend uses port 8000, frontend uses 5173 (or next available)
3. **API Key Errors**: Verify both Google AI and Census Bureau API keys are correctly set in `.env`
4. **Module Not Found**: Make sure all dependencies are installed in the virtual environment

### Reset Instructions:
```bash
# Clear Python cache and restart
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
# Then restart the server
```

## 📁 **Project Structure**
```
census-ai-backend/
├── main.py              # FastAPI application entry point
├── ai_orchestrator.py   # Google Gemini Pro integration & tool orchestration
├── tools.py             # Census data retrieval tool
├── census_api_client.py # U.S. Census Bureau API client
├── config.py            # Variable mappings, geography definitions, FIPS codes
├── .env                 # API keys (not in git)
├── .gitignore          # Excludes .env and cache files
├── __init__.py         # Package marker
└── README.md           # This file
```

## 🎊 **Status: Phase 2 Complete!**
✅ Secure API key management  
✅ Comprehensive Census variable mapping (17+ variables)  
✅ Geographic hierarchy handling (6 levels)  
✅ AI-powered natural language processing  
✅ Two-step tool execution with data interpretation  
✅ Robust error handling and validation  
✅ Full-stack integration working  

**Ready for Phase 3: GeoJSON Processing & Interactive Mapping!** 🗺️

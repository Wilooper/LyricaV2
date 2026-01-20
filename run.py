import uvicorn
import sys
import os

# Ensure src directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    # Run FastAPI app with uvicorn
    # Import from src.main instead of root main
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=9999,
        reload=True,
        log_level="info"
    )

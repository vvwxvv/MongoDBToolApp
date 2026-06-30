import sys
from pathlib import Path

# Add the project root to the Python path
root_dir = Path(__file__).parent.parent
sys.path.append(str(root_dir))

# Import the FastAPI app from test.py
from test import app

# (Optional) If you want to run the app directly in serverless,
# Vercel will look for an ASGI application named "app".
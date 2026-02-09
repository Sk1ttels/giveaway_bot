import sys
import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Load .env if present
env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(env_path if os.path.exists(env_path) else None)

import uvicorn
from app.admin.admin_app import app

if __name__ == "__main__":
    host = os.getenv("ADMIN_HOST", "0.0.0.0")
    port = int(os.getenv("ADMIN_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)

"""Production entry point for uvicorn.

Run: uvicorn api.uvicorn_entry:app --host 0.0.0.0 --port $PORT
"""

from app.main import app

__all__ = ["app"]

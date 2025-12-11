"""Main FastAPI application"""
import logging

# Configure logging FIRST, before any other imports that might trigger watchfiles
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Reduce watchfiles logging noise (only show warnings/errors)
# This must be set BEFORE uvicorn imports watchfiles
logging.getLogger("watchfiles").setLevel(logging.ERROR)
logging.getLogger("watchfiles.main").setLevel(logging.ERROR)

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pathlib import Path
from app.config import settings
from app.database.db import init_db
from app.api import routes, auth
import asyncio

# Initialize database (this will also create default admin user)
init_db()

# Create FastAPI app
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description="Music Server API for managing music library compatible with Plex"
)

# Start queue processor on startup
@app.on_event("startup")
async def startup_event():
    """Start queue processor on application startup"""
    from app.services.queue_manager import get_queue_manager
    from app.services.task_manager import task_manager
    from app.api.routes import process_download_sync
    
    queue_mgr = get_queue_manager(task_manager)
    # Start queue processor in background
    asyncio.create_task(queue_mgr.start_processing(process_download_sync))
    logging.info("✅ Queue processor started")

# CORS middleware
# En production, limitez allow_origins à vos domaines spécifiques
# Exemple: allow_origins=["https://votre-domaine.com", "https://www.votre-domaine.com"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Configurez avec vos domaines en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(routes.router, prefix="/api", tags=["music"])

# Serve static files
static_dir = Path(__file__).parent.parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root endpoint - redirect to login or app based on auth"""
    # Check if user has a token in cookie or will check in frontend
    return RedirectResponse(url="/login")


@app.get("/login", response_class=FileResponse)
async def serve_login():
    """Serve the login page"""
    login_file = Path(__file__).parent.parent / "static" / "login.html"
    if login_file.exists():
        return FileResponse(login_file)
    raise HTTPException(status_code=404, detail="Login page not found")


@app.get("/app", response_class=FileResponse)
async def serve_app(request: Request):
    """Serve the application page (requires authentication)"""
    # Check authentication via token in header
    auth_header = request.headers.get("Authorization")
    token = None
    
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
    else:
        # Try to get token from query parameter (for initial page load)
        token = request.cookies.get("auth_token")
    
    # If no token, let frontend handle redirect
    # Frontend will check localStorage and redirect if needed
    app_file = Path(__file__).parent.parent / "static" / "app.html"
    if app_file.exists():
        return FileResponse(app_file)
    raise HTTPException(status_code=404, detail="App page not found")


if __name__ == "__main__":
    import uvicorn
    from pathlib import Path
    
    # Only watch relevant directories to avoid reloading on download/music file changes
    base_dir = Path(__file__).parent.parent
    reload_dirs = [
        str(base_dir / "app"),
        str(base_dir / "static"),
        str(base_dir / "config")
    ]
    
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,
        reload_dirs=reload_dirs
    )


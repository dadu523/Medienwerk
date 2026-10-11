import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Database and routers initialize files during import.
os.makedirs(os.getenv("MEDIENWERK_WORKSPACE", "workspace"), exist_ok=True)

from server.routers import generation, publish, tools, brand, studio, campaigns, clipper, director

# Ensure workspace dir exists
os.makedirs("workspace", exist_ok=True)

app = FastAPI(
    title="AI Content Studio Engine",
    description="Scalable backend API for AI video generation",
    version="2.0.0"
)

from server.core.scheduler import start_scheduler

@app.on_event("startup")
def on_startup():
    from server.core.database import init_database
    from server.core.queue import recover_interrupted_jobs
    init_database()
    recover_interrupted_jobs()
    if os.getenv("MEDIENWERK_DISABLE_SCHEDULER") != "1":
        start_scheduler()

# Allow Next.js frontend to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(generation.router, prefix="/api/generate", tags=["Generation"])

from server.routers import clipper
app.include_router(clipper.router, prefix="/api/clipper", tags=["Clipper"])

from server.routers import videofx
app.include_router(videofx.router, prefix="/api/videofx", tags=["VideoFX Flow"])

from server.routers import director
app.include_router(director.router, prefix="/api/director", tags=["Director"])

from server.routers import explainer
app.include_router(explainer.router, prefix="/api/explainer", tags=["Explainer"])

from server.routers import brand
app.include_router(brand.router, prefix="/api/brand", tags=["Brand"])

from server.routers import tools
app.include_router(tools.router, prefix="/api/tools", tags=["Tools"])

from server.routers import publish
app.include_router(publish.router, prefix="/api/publish", tags=["Publish"])

from server.routers import studio
app.include_router(studio.router, prefix="/api/studio", tags=["Studio"])

from server.routers import campaigns
app.include_router(campaigns.router, prefix="/api/campaigns", tags=["Campaigns"])

from server.routers import social
app.include_router(social.router, prefix="/api/social", tags=["Social"])

from server.routers import projects
app.include_router(projects.router, prefix="/api/projects", tags=["Projects"])

from config import public_config, update_config as save_public_config, ConfigFileError
from server.core.config_schema import ConfigValidationError

@app.exception_handler(ConfigValidationError)
async def configuration_validation_error(request: Request, exc: ConfigValidationError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})

@app.exception_handler(ConfigFileError)
async def configuration_file_error(request: Request, exc: ConfigFileError):
    return JSONResponse(status_code=500, content={"detail": str(exc)})

@app.get("/api/config")
def get_config():
    return public_config()

@app.post("/api/config")
def update_config(new_config: dict):
    config = save_public_config(new_config)
    return {"message": "Configuration updated successfully.", "config": config}

@app.get("/health")
@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "AI Content Studio Engine"}

if __name__ == "__main__":
    import uvicorn
    # Run the server
    uvicorn.run("server.main:app", host="0.0.0.0", port=8008, reload=True)

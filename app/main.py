from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.db.session import init_db
from app.api.router import router
from app.api.admin import router as admin_router

app = FastAPI(title="AI MUD Server", version="0.1.0")

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for images/assets
static_path = Path(__file__).parent.parent / "static"
uploads_path = static_path / "uploads"
uploads_path.mkdir(parents=True, exist_ok=True)  # 确保目录存在
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

@app.on_event("startup")
async def on_startup():
    await init_db()

# Include API routers
app.include_router(router, prefix="/api")
app.include_router(admin_router, prefix="/api")

@app.get("/")
async def root():
    return {
        "message": "AI MUD Server is running",
        "version": "0.1.0",
        "docs": "/docs"
    }

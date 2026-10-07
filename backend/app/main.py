from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai import ollama_client
from app.clearing_codes import sync_clearing_codes
from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import Base
from app.routes import classify, exceptions, insights, prevention

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        sync_clearing_codes(db)
    yield


app = FastAPI(
    title="OV Exception - AI Root Cause & Prevention POC",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(exceptions.router)
app.include_router(classify.router)
app.include_router(insights.router)
app.include_router(prevention.router)


@app.get("/health", tags=["meta"])
def health():
    return {
        "status": "ok",
        "database": settings.database_url.split("@")[-1],
        "ollama": ollama_client.health(),
    }

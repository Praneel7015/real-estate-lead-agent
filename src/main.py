"""FastAPI entrypoint for the Real Estate Lead Agent."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()  # reads .env before any module touches os.environ

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.coordinator.router import router as coordinator_router
from src.tasks.followups import router as tasks_router

app = FastAPI(
    title="Real Estate Lead Agent",
    description="AI-powered lead qualification and scheduling system.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(coordinator_router)
app.include_router(tasks_router, prefix="/internal/tasks")


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}

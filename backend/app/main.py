from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal
from app.routers import assessments, auth, data_sources, evidence, governance, intake, lifecycle, models, org, registry, scenarios

settings = get_settings()

app = FastAPI(
    title="AI Model Selection & Governance Agent",
    description="Shared, risk-proportionate path from use case to approved, monitored AI model. Synthetic data only.",
    version="0.5.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=False,  # auth is a bearer token in the header, not a cookie
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, org, intake, models, evidence, data_sources, assessments, governance, lifecycle, scenarios, registry):
    app.include_router(module.router)


@app.get("/health", tags=["health"])
async def health():
    async with SessionLocal() as session:
        await session.execute(text("select 1"))
    return {"status": "ok", "environment": settings.environment, "llm_mode": settings.llm_mode}

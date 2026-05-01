"""
main.py
Точка входа FastAPI-приложения DentalNotifier.

Запуск:
    uvicorn main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from database import init_db
from services.scheduler import start_scheduler, stop_scheduler

from routers import auth, clinic, services, doctors, patients, appointments, stats, webhooks, booking, schedules
from routers.teeth import router as teeth_router, mkb_router

# ──────────────────────────────────────────────────────────────
#  Логирование
# ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
#  Lifespan (startup / shutdown)
# ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Allowed CORS Origins: %s", settings.cors_origins_list)
    logger.info("Инициализация БД...")
    await init_db()
    logger.info("Запуск планировщика напоминаний...")
    start_scheduler()
    yield
    logger.info("Остановка планировщика...")
    stop_scheduler()


# ──────────────────────────────────────────────────────────────
#  Создание приложения
# ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="DentalNotifier API",
    version="1.0.0",
    description="Сервис автоматических WhatsApp-напоминаний для стоматологических клиник",
    lifespan=lifespan,
)

# CORS — разрешаем фронтенду (React) обращаться к API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────
#  Роутеры
# ──────────────────────────────────────────────────────────────
API_PREFIX = "/api"

app.include_router(auth.router,         prefix=API_PREFIX)
app.include_router(clinic.router,       prefix=API_PREFIX)
app.include_router(services.router,     prefix=API_PREFIX)
app.include_router(doctors.router,      prefix=API_PREFIX)
app.include_router(patients.router,     prefix=API_PREFIX)
app.include_router(appointments.router, prefix=API_PREFIX)
app.include_router(stats.router,        prefix=API_PREFIX)
app.include_router(webhooks.router,     prefix=API_PREFIX)
app.include_router(booking.router,      prefix=API_PREFIX)
app.include_router(schedules.router,    prefix=API_PREFIX)
app.include_router(teeth_router,         prefix=API_PREFIX)
app.include_router(mkb_router,           prefix=API_PREFIX)

import os
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


@app.get("/health")
async def health():
    """Эндпоинт для healthcheck (nginx upstream_check, Docker healthcheck и т.д.)."""
    return {"status": "ok", "service": "DentalNotifier"}

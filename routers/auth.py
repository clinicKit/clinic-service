"""
routers/auth.py
Регистрация, вход, выход, /me.
"""

from fastapi import APIRouter, Depends, HTTPException, status
import aiosqlite
import bcrypt
import secrets
from datetime import datetime, timedelta

from database import get_db
from middleware.auth import create_access_token, get_current_user, CurrentUser
from models.schemas import RegisterRequest, LoginRequest, TokenResponse, MeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, db: aiosqlite.Connection = Depends(get_db)):
    """Создаёт клинику и первого администратора. Возвращает JWT."""

    # Проверяем уникальность email
    async with db.execute("SELECT id FROM users WHERE email = ?", (body.email,)) as cur:
        if await cur.fetchone():
            raise HTTPException(status_code=400, detail="Email уже зарегистрирован")

    # Создаём клинику с 14-дневным пробным периодом и уникальной ссылкой для бронирования
    trial_start = datetime.utcnow().isoformat()
    trial_end = (datetime.utcnow() + timedelta(days=14)).isoformat()
    booking_slug = secrets.token_urlsafe(12)  # Генерируем уникальный slug
    
    async with db.execute(
        "INSERT INTO clinics (name, address, timezone, trial_start_date, trial_end_date, is_active, booking_slug) VALUES (?, ?, ?, ?, ?, 1, ?)",
        (body.clinic_name, body.address, body.timezone, trial_start, trial_end, booking_slug),
    ) as cur:
        clinic_id = cur.lastrowid

    # Создаём пользователя
    pw_hash = hash_password(body.password)
    async with db.execute(
        "INSERT INTO users (clinic_id, email, password_hash) VALUES (?, ?, ?)",
        (clinic_id, body.email, pw_hash),
    ) as cur:
        user_id = cur.lastrowid

    await db.commit()

    token = create_access_token({"sub": str(user_id)})
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: aiosqlite.Connection = Depends(get_db)):
    """Проверяет email/пароль, возвращает JWT."""
    async with db.execute(
        "SELECT id, password_hash FROM users WHERE email = ?", (body.email,)
    ) as cur:
        row = await cur.fetchone()

    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    token = create_access_token({"sub": str(row["id"])})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=MeResponse)
async def me(
    current_user: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Возвращает данные текущего пользователя с информацией о пробном периоде."""
    async with db.execute(
        "SELECT name, trial_start_date, trial_end_date, is_active, booking_slug FROM clinics WHERE id = ?", 
        (current_user.clinic_id,)
    ) as cur:
        clinic = await cur.fetchone()
    
    if not clinic:
        raise HTTPException(status_code=404, detail="Клиника не найдена")
    
    # Проверяем истёк ли пробный период
    is_trial_expired = False
    if clinic["trial_end_date"]:
        trial_end = datetime.fromisoformat(clinic["trial_end_date"])
        is_trial_expired = datetime.utcnow() > trial_end
    
    return MeResponse(
        user_id=current_user.user_id,
        email=current_user.email,
        clinic_id=current_user.clinic_id,
        clinic_name=clinic["name"],
        trial_start_date=clinic["trial_start_date"],
        trial_end_date=clinic["trial_end_date"],
        is_active=bool(clinic["is_active"]),
        is_trial_expired=is_trial_expired,
        booking_slug=clinic["booking_slug"],
    )

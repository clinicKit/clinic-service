"""
middleware/auth.py
JWT-аутентификация: создание токена, верификация, FastAPI dependency.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import aiosqlite

from config import settings
from database import get_db

bearer_scheme = HTTPBearer(auto_error=True)


def create_access_token(data: dict) -> str:
    """Создаёт JWT с временем жизни из настроек."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode_token(token: str) -> dict:
    """Декодирует и валидирует JWT. Бросает HTTPException при ошибке."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен недействителен или истёк",
            headers={"WWW-Authenticate": "Bearer"},
        )


class CurrentUser:
    """Контейнер данных авторизованного пользователя."""
    def __init__(self, user_id: int, clinic_id: int, email: str):
        self.user_id = user_id
        self.clinic_id = clinic_id
        self.email = email


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: aiosqlite.Connection = Depends(get_db),
) -> CurrentUser:
    """
    FastAPI dependency.
    Читает Bearer-токен, проверяет существование пользователя в БД
    и возвращает CurrentUser с clinic_id.
    """
    payload = _decode_token(credentials.credentials)
    user_id: Optional[int] = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Некорректный токен")

    async with db.execute(
        "SELECT id, clinic_id, email FROM users WHERE id = ?", (int(user_id),)
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    return CurrentUser(user_id=row["id"], clinic_id=row["clinic_id"], email=row["email"])

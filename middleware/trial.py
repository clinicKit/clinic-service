"""
middleware/trial.py
Middleware to check if clinic's trial period is active
"""

from fastapi import Depends, HTTPException, status
import aiosqlite
from datetime import datetime

from database import get_db
from middleware.auth import get_current_user, CurrentUser


async def check_trial_active(
    current_user: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Проверяет активен ли пробный период клиники.
    Если истёк и is_active=0, блокирует доступ.
    """
    async with db.execute(
        "SELECT trial_end_date, is_active FROM clinics WHERE id = ?",
        (current_user.clinic_id,)
    ) as cur:
        clinic = await cur.fetchone()
    
    if not clinic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Клиника не найдена"
        )
    
    # Если клиника деактивирована
    if not clinic["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ к клинике заблокирован. Свяжитесь с поддержкой."
        )
    
    # Проверяем истёк ли пробный период
    if clinic["trial_end_date"]:
        trial_end = datetime.fromisoformat(clinic["trial_end_date"])
        if datetime.utcnow() > trial_end:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Пробный период истёк. Пожалуйста, оформите подписку."
            )
    
    return current_user

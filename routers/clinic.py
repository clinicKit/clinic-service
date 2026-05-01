"""
routers/clinic.py
Получение и обновление данных клиники, шаблонов сообщений.
"""

from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from database import get_db
from middleware.auth import get_current_user, CurrentUser
from models.schemas import ClinicOut, ClinicUpdate, TemplatesOut, TemplatesUpdate
from services.whatsapp import DEFAULT_TEMPLATE_24H, DEFAULT_TEMPLATE_2H

router = APIRouter(prefix="/clinic", tags=["clinic"])


@router.get("", response_model=ClinicOut)
async def get_clinic(
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute("SELECT * FROM clinics WHERE id = ?", (cu.clinic_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Клиника не найдена")
    return dict(row)


@router.put("", response_model=ClinicOut)
async def update_clinic(
    body: ClinicUpdate,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "Нет данных для обновления")

    fields = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [cu.clinic_id]
    await db.execute(f"UPDATE clinics SET {fields} WHERE id = ?", values)
    await db.commit()

    async with db.execute("SELECT * FROM clinics WHERE id = ?", (cu.clinic_id,)) as cur:
        row = await cur.fetchone()
    return dict(row)


@router.get("/templates", response_model=TemplatesOut)
async def get_templates(
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "SELECT template_24h, template_2h FROM clinics WHERE id = ?", (cu.clinic_id,)
    ) as cur:
        row = await cur.fetchone()
    return TemplatesOut(
        reminder_24h=row["template_24h"] or DEFAULT_TEMPLATE_24H,
        reminder_2h=row["template_2h"] or DEFAULT_TEMPLATE_2H,
    )


@router.put("/templates", response_model=TemplatesOut)
async def update_templates(
    body: TemplatesUpdate,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    await db.execute(
        "UPDATE clinics SET template_24h = ?, template_2h = ? WHERE id = ?",
        (body.reminder_24h, body.reminder_2h, cu.clinic_id),
    )
    await db.commit()
    return TemplatesOut(
        reminder_24h=body.reminder_24h or DEFAULT_TEMPLATE_24H,
        reminder_2h=body.reminder_2h or DEFAULT_TEMPLATE_2H,
    )

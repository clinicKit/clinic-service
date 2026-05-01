"""
routers/services.py
CRUD для услуг клиники.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from database import get_db
from middleware.auth import get_current_user, CurrentUser
from models.schemas import ServiceCreate, ServiceUpdate, ServiceOut

router = APIRouter(prefix="/services", tags=["services"])


@router.get("", response_model=List[ServiceOut])
async def list_services(
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "SELECT * FROM services WHERE clinic_id = ? ORDER BY name", (cu.clinic_id,)
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


@router.post("", response_model=ServiceOut, status_code=201)
async def create_service(
    body: ServiceCreate,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "INSERT INTO services (clinic_id, name, duration_minutes, color) VALUES (?,?,?,?)",
        (cu.clinic_id, body.name, body.duration_minutes, body.color),
    ) as cur:
        sid = cur.lastrowid
    await db.commit()
    async with db.execute("SELECT * FROM services WHERE id = ?", (sid,)) as cur:
        return dict(await cur.fetchone())


@router.put("/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: int,
    body: ServiceUpdate,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "Нет данных")
    # Убеждаемся, что услуга принадлежит клинике
    async with db.execute(
        "SELECT id FROM services WHERE id = ? AND clinic_id = ?", (service_id, cu.clinic_id)
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(404, "Услуга не найдена")
    fields = ", ".join(f"{k} = ?" for k in updates)
    await db.execute(
        f"UPDATE services SET {fields} WHERE id = ?",
        [*updates.values(), service_id],
    )
    await db.commit()
    async with db.execute("SELECT * FROM services WHERE id = ?", (service_id,)) as cur:
        return dict(await cur.fetchone())


@router.delete("/{service_id}", status_code=204)
async def delete_service(
    service_id: int,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "SELECT id FROM services WHERE id = ? AND clinic_id = ?", (service_id, cu.clinic_id)
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(404, "Услуга не найдена")
    await db.execute("DELETE FROM services WHERE id = ?", (service_id,))
    await db.commit()

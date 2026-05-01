"""
routers/doctors.py
CRUD для врачей клиники.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from database import get_db
from middleware.auth import get_current_user, CurrentUser
from models.schemas import DoctorCreate, DoctorUpdate, DoctorOut

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get("", response_model=List[DoctorOut])
async def list_doctors(
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "SELECT * FROM doctors WHERE clinic_id = ? ORDER BY name", (cu.clinic_id,)
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


@router.post("", response_model=DoctorOut, status_code=201)
async def create_doctor(
    body: DoctorCreate,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "INSERT INTO doctors (clinic_id, name, specialty) VALUES (?,?,?)",
        (cu.clinic_id, body.name, body.specialty),
    ) as cur:
        did = cur.lastrowid
    await db.commit()
    async with db.execute("SELECT * FROM doctors WHERE id = ?", (did,)) as cur:
        return dict(await cur.fetchone())


@router.put("/{doctor_id}", response_model=DoctorOut)
async def update_doctor(
    doctor_id: int,
    body: DoctorUpdate,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "Нет данных")
    async with db.execute(
        "SELECT id FROM doctors WHERE id = ? AND clinic_id = ?", (doctor_id, cu.clinic_id)
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(404, "Врач не найден")
    fields = ", ".join(f"{k} = ?" for k in updates)
    await db.execute(
        f"UPDATE doctors SET {fields} WHERE id = ?",
        [*updates.values(), doctor_id],
    )
    await db.commit()
    async with db.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)) as cur:
        return dict(await cur.fetchone())


@router.delete("/{doctor_id}", status_code=204)
async def delete_doctor(
    doctor_id: int,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "SELECT id FROM doctors WHERE id = ? AND clinic_id = ?", (doctor_id, cu.clinic_id)
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(404, "Врач не найден")
    await db.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
    await db.commit()

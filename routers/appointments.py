"""
routers/appointments.py
CRUD записей на приём.

GET  /appointments?start=&end=   — для FullCalendar
POST /appointments               — создание записи
PUT  /appointments/:id           — редактирование
DELETE /appointments/:id         — удаление
PATCH /appointments/:id/status   — смена статуса вручную
"""

from typing import List, Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
import aiosqlite

from database import get_db
from middleware.auth import get_current_user, CurrentUser
from models.schemas import (
    AppointmentCreate,
    AppointmentUpdate,
    AppointmentOut,
    StatusPatch,
)

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _row_to_out(r) -> AppointmentOut:
    """Конвертирует строку БД в AppointmentOut."""
    return AppointmentOut(
        id=r["id"],
        clinic_id=r["clinic_id"],
        patient_id=r["patient_id"],
        doctor_id=r["doctor_id"],
        service_id=r["service_id"],
        start_time=r["start_time"],
        end_time=r["end_time"],
        status=r["status"],
        notes=r["notes"],
        created_at=r["created_at"],
        patient_name=r["patient_name"] if "patient_name" in r.keys() else None,
        doctor_name=r["doctor_name"] if "doctor_name" in r.keys() else None,
        service_name=r["service_name"] if "service_name" in r.keys() else None,
        service_color=r["service_color"] if "service_color" in r.keys() else None,
    )


# JOIN-запрос с расширенными полями для фронтенда
_SELECT_FULL = """
SELECT
    a.*,
    p.first_name || COALESCE(' ' || p.last_name, '') AS patient_name,
    d.name AS doctor_name,
    s.name AS service_name,
    s.color AS service_color,
    s.duration_minutes
FROM appointments a
JOIN patients p ON p.id = a.patient_id
JOIN doctors  d ON d.id = a.doctor_id
JOIN services s ON s.id = a.service_id
"""


@router.get("", response_model=List[AppointmentOut])
async def list_appointments(
    start: Optional[str] = Query(None, description="ISO datetime начало диапазона"),
    end: Optional[str] = Query(None, description="ISO datetime конец диапазона"),
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    conditions = ["a.clinic_id = ?"]
    params: list = [cu.clinic_id]

    if start:
        conditions.append("a.start_time >= ?")
        params.append(start)
    if end:
        conditions.append("a.start_time <= ?")
        params.append(end)

    where = " WHERE " + " AND ".join(conditions)
    sql = _SELECT_FULL + where + " ORDER BY a.start_time"

    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()

    return [_row_to_out(r) for r in rows]


@router.post("", response_model=AppointmentOut, status_code=201)
async def create_appointment(
    body: AppointmentCreate,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    # Проверяем принадлежность пациента/врача/услуги клинике
    for table, fid in [("patients", body.patient_id), ("doctors", body.doctor_id), ("services", body.service_id)]:
        async with db.execute(
            f"SELECT id FROM {table} WHERE id = ? AND clinic_id = ?", (fid, cu.clinic_id)
        ) as cur:
            if not await cur.fetchone():
                raise HTTPException(404, f"Запись в '{table}' с id={fid} не найдена")

    # Если end_time не передан — вычисляем из duration_minutes услуги
    if body.end_time:
        end_time = body.end_time
    else:
        async with db.execute(
            "SELECT duration_minutes FROM services WHERE id = ?", (body.service_id,)
        ) as cur:
            svc = await cur.fetchone()
        end_time = body.start_time + timedelta(minutes=svc["duration_minutes"])

    start_str = body.start_time.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = end_time.strftime("%Y-%m-%dT%H:%M:%S")

    async with db.execute(
        """
        INSERT INTO appointments (clinic_id, patient_id, doctor_id, service_id, start_time, end_time, notes)
        VALUES (?,?,?,?,?,?,?)
        """,
        (cu.clinic_id, body.patient_id, body.doctor_id, body.service_id, start_str, end_str, body.notes),
    ) as cur:
        aid = cur.lastrowid
    await db.commit()

    async with db.execute(_SELECT_FULL + " WHERE a.id = ?", (aid,)) as cur:
        return _row_to_out(await cur.fetchone())


@router.put("/{appt_id}", response_model=AppointmentOut)
async def update_appointment(
    appt_id: int,
    body: AppointmentUpdate,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    # Проверяем существование записи
    async with db.execute(
        "SELECT * FROM appointments WHERE id = ? AND clinic_id = ?", (appt_id, cu.clinic_id)
    ) as cur:
        existing = await cur.fetchone()
    if not existing:
        raise HTTPException(404, "Запись не найдена")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "Нет данных для обновления")

    # Конвертируем datetime в строки
    for dt_field in ("start_time", "end_time"):
        if dt_field in updates and isinstance(updates[dt_field], datetime):
            updates[dt_field] = updates[dt_field].strftime("%Y-%m-%dT%H:%M:%S")

    # Если сменилось время — удаляем старые уведомления (планировщик пересоздаст)
    if "start_time" in updates or "end_time" in updates:
        await db.execute("DELETE FROM notifications WHERE appointment_id = ?", (appt_id,))

    fields = ", ".join(f"{k} = ?" for k in updates)
    await db.execute(
        f"UPDATE appointments SET {fields} WHERE id = ?",
        [*updates.values(), appt_id],
    )
    await db.commit()

    async with db.execute(_SELECT_FULL + " WHERE a.id = ?", (appt_id,)) as cur:
        return _row_to_out(await cur.fetchone())


@router.delete("/{appt_id}", status_code=204)
async def delete_appointment(
    appt_id: int,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "SELECT id FROM appointments WHERE id = ? AND clinic_id = ?", (appt_id, cu.clinic_id)
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(404, "Запись не найдена")
    # Каскадное удаление уведомлений задано через FK ON DELETE CASCADE
    await db.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
    await db.commit()


@router.patch("/{appt_id}/status", response_model=AppointmentOut)
async def patch_status(
    appt_id: int,
    body: StatusPatch,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    async with db.execute(
        "SELECT id FROM appointments WHERE id = ? AND clinic_id = ?", (appt_id, cu.clinic_id)
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(404, "Запись не найдена")
    await db.execute(
        "UPDATE appointments SET status = ? WHERE id = ?", (body.status, appt_id)
    )
    await db.commit()
    async with db.execute(_SELECT_FULL + " WHERE a.id = ?", (appt_id,)) as cur:
        return _row_to_out(await cur.fetchone())

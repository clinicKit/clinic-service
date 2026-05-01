"""
routers/patients.py
CRUD пациентов клиники.
POST /patients — создаёт нового или возвращает существующего по phone + clinic_id.
GET /patients?search=... — поиск по имени / телефону.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
import aiosqlite

from database import get_db
from middleware.auth import get_current_user, CurrentUser
from models.schemas import PatientCreate, PatientUpdate, PatientOut

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("", response_model=List[PatientOut])
async def list_patients(
    search: Optional[str] = Query(default=None, description="Поиск по имени или телефону"),
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    if search:
        pattern = f"%{search}%"
        sql = """
            SELECT * FROM patients
            WHERE clinic_id = ?
              AND (first_name LIKE ? OR last_name LIKE ? OR phone LIKE ?)
            ORDER BY first_name
        """
        params = (cu.clinic_id, pattern, pattern, pattern)
    else:
        sql = "SELECT * FROM patients WHERE clinic_id = ? ORDER BY first_name"
        params = (cu.clinic_id,)

    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()

    return [
        PatientOut(
            id=r["id"],
            clinic_id=r["clinic_id"],
            phone=r["phone"],
            first_name=r["first_name"],
            last_name=r["last_name"],
            consent_given=bool(r["consent_given"]),
        )
        for r in rows
    ]


@router.post("", response_model=PatientOut, status_code=201)
async def create_or_get_patient(
    body: PatientCreate,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Если пациент с таким телефоном уже есть в клинике — возвращаем его (idempotent).
    Иначе создаём новую запись.
    """
    async with db.execute(
        "SELECT * FROM patients WHERE clinic_id = ? AND phone = ?",
        (cu.clinic_id, body.phone),
    ) as cur:
        existing = await cur.fetchone()

    if existing:
        return PatientOut(
            id=existing["id"],
            clinic_id=existing["clinic_id"],
            phone=existing["phone"],
            first_name=existing["first_name"],
            last_name=existing["last_name"],
            consent_given=bool(existing["consent_given"]),
        )

    async with db.execute(
        "INSERT INTO patients (clinic_id, phone, first_name, last_name, consent_given) VALUES (?,?,?,?,?)",
        (cu.clinic_id, body.phone, body.first_name, body.last_name, int(body.consent_given)),
    ) as cur:
        pid = cur.lastrowid
    await db.commit()

    async with db.execute("SELECT * FROM patients WHERE id = ?", (pid,)) as cur:
        row = await cur.fetchone()

    return PatientOut(
        id=row["id"],
        clinic_id=row["clinic_id"],
        phone=row["phone"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        consent_given=bool(row["consent_given"]),
    )


@router.put("/{patient_id}", response_model=PatientOut)
async def update_patient(
    patient_id: int,
    body: PatientUpdate,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "Нет данных для обновления")

    async with db.execute(
        "SELECT id FROM patients WHERE id = ? AND clinic_id = ?", (patient_id, cu.clinic_id)
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(404, "Пациент не найден")

    # consent_given сохраняем как int (SQLite)
    if "consent_given" in updates:
        updates["consent_given"] = int(updates["consent_given"])

    fields = ", ".join(f"{k} = ?" for k in updates)
    await db.execute(
        f"UPDATE patients SET {fields} WHERE id = ?",
        [*updates.values(), patient_id],
    )
    await db.commit()

    async with db.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)) as cur:
        row = await cur.fetchone()

    return PatientOut(
        id=row["id"],
        clinic_id=row["clinic_id"],
        phone=row["phone"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        consent_given=bool(row["consent_given"]),
    )

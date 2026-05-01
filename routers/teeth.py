"""
routers/teeth.py
Интерактивная зубная формула — CRUD зубов, снимков, история, МКБ-10 справочник.
"""

import os
import uuid
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
import aiosqlite

from database import get_db
from middleware.auth import get_current_user, CurrentUser

router = APIRouter(prefix="/patients/{patient_id}/teeth", tags=["teeth"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "teeth")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ──────────────────────────────────────────────────────────────
#  Модели
# ──────────────────────────────────────────────────────────────

VALID_STATUSES = ("healthy", "caries", "filled", "implant", "missing", "observation")

class ToothUpdate(BaseModel):
    status: str
    diagnosis_code: Optional[str] = None
    notes: Optional[str] = None

class ToothOut(BaseModel):
    tooth_number: int
    status: str
    diagnosis_code: Optional[str] = None
    notes: Optional[str] = None
    updated_at: Optional[str] = None

class ToothImageOut(BaseModel):
    id: int
    file_path: str
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    created_at: str

class ToothHistoryOut(BaseModel):
    id: int
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    changed_by: Optional[int] = None
    changed_at: str

class MKB10Item(BaseModel):
    code: str
    name: str


# ──────────────────────────────────────────────────────────────
#  Справочник МКБ-10 (стоматологические коды)
# ──────────────────────────────────────────────────────────────

MKB10_STOMATOLOGY = [
    {"code": "K00.0", "name": "Адентия"},
    {"code": "K00.1", "name": "Сверхкомплектные зубы"},
    {"code": "K00.6", "name": "Нарушения прорезывания зубов"},
    {"code": "K01.0", "name": "Ретенированные зубы"},
    {"code": "K01.1", "name": "Импактные зубы"},
    {"code": "K02.0", "name": "Кариес эмали"},
    {"code": "K02.1", "name": "Кариес дентина"},
    {"code": "K02.2", "name": "Кариес цемента"},
    {"code": "K02.3", "name": "Приостановившийся кариес"},
    {"code": "K02.5", "name": "Кариес с обнажением пульпы"},
    {"code": "K02.9", "name": "Кариес зубов неуточнённый"},
    {"code": "K03.0", "name": "Повышенная стираемость зубов"},
    {"code": "K03.1", "name": "Сошлифовывание зубов"},
    {"code": "K04.0", "name": "Пульпит"},
    {"code": "K04.1", "name": "Некроз пульпы"},
    {"code": "K04.4", "name": "Острый апикальный периодонтит"},
    {"code": "K04.5", "name": "Хронический апикальный периодонтит"},
    {"code": "K04.6", "name": "Периапикальный абсцесс со свищом"},
    {"code": "K04.7", "name": "Периапикальный абсцесс без свища"},
    {"code": "K05.0", "name": "Острый гингивит"},
    {"code": "K05.1", "name": "Хронический гингивит"},
    {"code": "K05.2", "name": "Острый пародонтит"},
    {"code": "K05.3", "name": "Хронический пародонтит"},
    {"code": "K06.0", "name": "Рецессия десны"},
    {"code": "K06.2", "name": "Поражения десны и беззубого альвеолярного края"},
    {"code": "K07.3", "name": "Аномалии положения зубов"},
    {"code": "K08.1", "name": "Потеря зубов вследствие удаления"},
    {"code": "K08.3", "name": "Оставшийся корень зуба"},
    {"code": "K09.0", "name": "Киста при прорезывании зубов"},
    {"code": "K10.0", "name": "Нарушения развития челюстей"},
    {"code": "K12.0", "name": "Рецидивирующие афты полости рта"},
    {"code": "K12.1", "name": "Другие формы стоматита"},
    {"code": "K13.0", "name": "Болезни губ"},
]


# ──────────────────────────────────────────────────────────────
#  Хелперы
# ──────────────────────────────────────────────────────────────

async def _check_patient_ownership(db, patient_id: int, clinic_id: int):
    async with db.execute(
        "SELECT id FROM patients WHERE id = ? AND clinic_id = ?",
        (patient_id, clinic_id),
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(404, "Пациент не найден")


# ──────────────────────────────────────────────────────────────
#  GET /api/patients/:patientId/teeth — все зубы пациента
# ──────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
async def get_patient_teeth(
    patient_id: int,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    await _check_patient_ownership(db, patient_id, cu.clinic_id)

    async with db.execute(
        "SELECT tooth_number, status, diagnosis_code, notes, updated_at FROM patient_teeth WHERE patient_id = ?",
        (patient_id,),
    ) as cur:
        rows = await cur.fetchall()

    teeth = {}
    for r in rows:
        teeth[str(r["tooth_number"])] = {
            "status": r["status"],
            "diagnosis_code": r["diagnosis_code"],
            "notes": r["notes"],
            "updated_at": r["updated_at"],
        }

    return {"teeth": teeth}


# ──────────────────────────────────────────────────────────────
#  PUT /api/patients/:patientId/teeth/:toothNumber — обновить статус
# ──────────────────────────────────────────────────────────────

@router.put("/{tooth_number}")
async def update_tooth(
    patient_id: int,
    tooth_number: int,
    body: ToothUpdate,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    await _check_patient_ownership(db, patient_id, cu.clinic_id)

    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"Недопустимый статус: {body.status}")

    if tooth_number < 11 or tooth_number > 48:
        raise HTTPException(400, f"Недопустимый номер зуба: {tooth_number}")

    # Получаем текущий статус для истории
    old_status = None
    async with db.execute(
        "SELECT status FROM patient_teeth WHERE patient_id = ? AND tooth_number = ?",
        (patient_id, tooth_number),
    ) as cur:
        existing = await cur.fetchone()
        if existing:
            old_status = existing["status"]

    now = datetime.utcnow().isoformat()

    if existing:
        await db.execute(
            """UPDATE patient_teeth
               SET status = ?, diagnosis_code = ?, notes = ?, updated_by = ?, updated_at = ?
               WHERE patient_id = ? AND tooth_number = ?""",
            (body.status, body.diagnosis_code, body.notes, cu.user_id, now,
             patient_id, tooth_number),
        )
    else:
        await db.execute(
            """INSERT INTO patient_teeth (patient_id, tooth_number, status, diagnosis_code, notes, updated_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (patient_id, tooth_number, body.status, body.diagnosis_code, body.notes, cu.user_id, now, now),
        )

    # Записываем в историю
    if old_status != body.status:
        await db.execute(
            "INSERT INTO tooth_history (patient_id, tooth_number, old_status, new_status, changed_by, changed_at) VALUES (?,?,?,?,?,?)",
            (patient_id, tooth_number, old_status, body.status, cu.user_id, now),
        )

    await db.commit()
    return {"success": True}


# ──────────────────────────────────────────────────────────────
#  GET /api/patients/:patientId/teeth/:toothNumber/history
# ──────────────────────────────────────────────────────────────

@router.get("/{tooth_number}/history", response_model=List[ToothHistoryOut])
async def get_tooth_history(
    patient_id: int,
    tooth_number: int,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    await _check_patient_ownership(db, patient_id, cu.clinic_id)

    async with db.execute(
        "SELECT * FROM tooth_history WHERE patient_id = ? AND tooth_number = ? ORDER BY changed_at DESC",
        (patient_id, tooth_number),
    ) as cur:
        rows = await cur.fetchall()

    return [
        ToothHistoryOut(
            id=r["id"],
            old_status=r["old_status"],
            new_status=r["new_status"],
            changed_by=r["changed_by"],
            changed_at=r["changed_at"],
        )
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────
#  GET /api/patients/:patientId/teeth/:toothNumber/images
# ──────────────────────────────────────────────────────────────

@router.get("/{tooth_number}/images", response_model=List[ToothImageOut])
async def get_tooth_images(
    patient_id: int,
    tooth_number: int,
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    await _check_patient_ownership(db, patient_id, cu.clinic_id)

    async with db.execute(
        "SELECT * FROM tooth_images WHERE patient_id = ? AND tooth_number = ? ORDER BY created_at DESC",
        (patient_id, tooth_number),
    ) as cur:
        rows = await cur.fetchall()

    return [
        ToothImageOut(
            id=r["id"],
            file_path=r["file_path"],
            file_name=r["file_name"],
            file_size=r["file_size"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────
#  POST /api/patients/:patientId/teeth/:toothNumber/images
# ──────────────────────────────────────────────────────────────

@router.post("/{tooth_number}/images", status_code=201)
async def upload_tooth_image(
    patient_id: int,
    tooth_number: int,
    file: UploadFile = File(...),
    cu: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    await _check_patient_ownership(db, patient_id, cu.clinic_id)

    # Проверяем что зуб существует (или создаём запись)
    async with db.execute(
        "SELECT id FROM patient_teeth WHERE patient_id = ? AND tooth_number = ?",
        (patient_id, tooth_number),
    ) as cur:
        if not await cur.fetchone():
            now = datetime.utcnow().isoformat()
            await db.execute(
                "INSERT INTO patient_teeth (patient_id, tooth_number, status, created_at, updated_at) VALUES (?,?,?,?,?)",
                (patient_id, tooth_number, "healthy", now, now),
            )

    # Сохраняем файл
    ext = os.path.splitext(file.filename or "image.jpg")[1]
    unique_name = f"{patient_id}_{tooth_number}_{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    contents = await file.read()
    with open(file_path, "wb") as f:
        f.write(contents)

    now = datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO tooth_images (patient_id, tooth_number, file_path, file_name, file_size, uploaded_by, created_at) VALUES (?,?,?,?,?,?,?)",
        (patient_id, tooth_number, f"/uploads/teeth/{unique_name}", file.filename, len(contents), cu.user_id, now),
    )
    await db.commit()

    return {"success": True, "file_path": f"/uploads/teeth/{unique_name}"}


# ──────────────────────────────────────────────────────────────
#  GET /api/reference/mkb10/stomatology — справочник МКБ-10
# ──────────────────────────────────────────────────────────────

mkb_router = APIRouter(prefix="/reference", tags=["reference"])

@mkb_router.get("/mkb10/stomatology", response_model=List[MKB10Item])
async def get_mkb10_stomatology():
    return [MKB10Item(**item) for item in MKB10_STOMATOLOGY]

"""
routers/booking.py
Public booking API for patients to book appointments via unique clinic link
"""

from fastapi import APIRouter, Depends, HTTPException, status
import aiosqlite
from typing import List
from pydantic import BaseModel
from datetime import datetime, timedelta

from database import get_db

router = APIRouter(prefix="/booking", tags=["booking"])


class ClinicInfoResponse(BaseModel):
    clinic_id: int
    clinic_name: str
    address: str
    timezone: str


class ServiceResponse(BaseModel):
    id: int
    name: str
    duration_minutes: int


class DoctorResponse(BaseModel):
    id: int
    name: str
    specialty: str | None


class CreateBookingRequest(BaseModel):
    patient_phone: str
    patient_first_name: str
    patient_last_name: str | None = None
    service_id: int
    doctor_id: int
    start_time: str  # ISO format
    end_time: str    # ISO format
    notes: str | None = None


@router.get("/{booking_slug}/info", response_model=ClinicInfoResponse)
async def get_clinic_info(booking_slug: str, db: aiosqlite.Connection = Depends(get_db)):
    """Получить информацию о клинике по booking_slug"""
    async with db.execute(
        "SELECT id, name, address, timezone FROM clinics WHERE booking_slug = ? AND is_active = 1",
        (booking_slug,)
    ) as cur:
        clinic = await cur.fetchone()
    
    if not clinic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Клиника не найдена или неактивна"
        )
    
    return ClinicInfoResponse(
        clinic_id=clinic["id"],
        clinic_name=clinic["name"],
        address=clinic["address"],
        timezone=clinic["timezone"],
    )


@router.get("/{booking_slug}/services", response_model=List[ServiceResponse])
async def get_services(booking_slug: str, db: aiosqlite.Connection = Depends(get_db)):
    """Получить список услуг клиники"""
    # Сначала найдем clinic_id по slug
    async with db.execute(
        "SELECT id FROM clinics WHERE booking_slug = ? AND is_active = 1",
        (booking_slug,)
    ) as cur:
        clinic = await cur.fetchone()
    
    if not clinic:
        raise HTTPException(status_code=404, detail="Клиника не найдена")
    
    # Получаем услуги
    async with db.execute(
        "SELECT id, name, duration_minutes FROM services WHERE clinic_id = ?",
        (clinic["id"],)
    ) as cur:
        services = await cur.fetchall()
    
    return [ServiceResponse(**dict(s)) for s in services]


@router.get("/{booking_slug}/doctors", response_model=List[DoctorResponse])
async def get_doctors(booking_slug: str, db: aiosqlite.Connection = Depends(get_db)):
    """Получить список врачей клиники"""
    async with db.execute(
        "SELECT id FROM clinics WHERE booking_slug = ? AND is_active = 1",
        (booking_slug,)
    ) as cur:
        clinic = await cur.fetchone()
    
    if not clinic:
        raise HTTPException(status_code=404, detail="Клиника не найдена")
    
    async with db.execute(
        "SELECT id, name, specialty FROM doctors WHERE clinic_id = ?",
        (clinic["id"],)
    ) as cur:
        doctors = await cur.fetchall()
    
    return [DoctorResponse(**dict(d)) for d in doctors]


@router.get("/{booking_slug}/available-slots")
async def get_available_slots(
    booking_slug: str,
    doctor_id: int,
    service_id: int,
    date: str,  # YYYY-MM-DD
    db: aiosqlite.Connection = Depends(get_db)
):
    """Get available time slots for booking"""
    # Get clinic_id
    async with db.execute(
        "SELECT id FROM clinics WHERE booking_slug = ? AND is_active = 1",
        (booking_slug,)
    ) as cur:
        clinic = await cur.fetchone()
    
    if not clinic:
        raise HTTPException(status_code=404, detail="Клиника не найдена")
    
    # Get service duration
    async with db.execute(
        "SELECT duration_minutes FROM services WHERE id = ?",
        (service_id,)
    ) as cur:
        service = await cur.fetchone()
        if not service:
            raise HTTPException(status_code=404, detail="Услуга не найдена")
        duration = service["duration_minutes"]
    
    # Get day of week
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    day_of_week = date_obj.weekday()
    
    # Get doctor's schedule
    async with db.execute(
        """SELECT start_time, end_time, slot_duration
           FROM doctor_schedules
           WHERE doctor_id = ? AND day_of_week = ?""",
        (doctor_id, day_of_week)
    ) as cur:
        schedules = await cur.fetchall()
    
    if not schedules:
        return []
    
    # Get existing appointments
    async with db.execute(
        """SELECT start_time, end_time FROM appointments
           WHERE doctor_id = ? AND DATE(start_time) = ? AND status != 'cancelled'""",
        (doctor_id, date)
    ) as cur:
        appointments = await cur.fetchall()
    
    # Generate available slots
    available_slots = []
    for schedule in schedules:
        start_time = datetime.strptime(f"{date} {schedule['start_time']}", "%Y-%m-%d %H:%M")
        end_time = datetime.strptime(f"{date} {schedule['end_time']}", "%Y-%m-%d %H:%M")
        slot_duration = schedule['slot_duration']
        
        current_time = start_time
        while current_time + timedelta(minutes=duration) <= end_time:
            slot_end = current_time + timedelta(minutes=duration)
            
            # Check if slot overlaps with existing appointments
            is_available = True
            for apt in appointments:
                apt_start = datetime.fromisoformat(apt['start_time'].replace('Z', '+00:00'))
                apt_end = datetime.fromisoformat(apt['end_time'].replace('Z', '+00:00'))
                
                if (current_time < apt_end and slot_end > apt_start):
                    is_available = False
                    break
            
            available_slots.append({
                "time": current_time.strftime("%H:%M"),
                "available": is_available
            })
            
            current_time += timedelta(minutes=slot_duration)
    
    return available_slots


@router.post("/{booking_slug}/book", status_code=201)
async def create_booking(
    booking_slug: str,
    body: CreateBookingRequest,
    db: aiosqlite.Connection = Depends(get_db)
):
    """Создать новую запись через публичную форму"""
    # Получаем clinic_id
    async with db.execute(
        "SELECT id FROM clinics WHERE booking_slug = ? AND is_active = 1",
        (booking_slug,)
    ) as cur:
        clinic = await cur.fetchone()
    
    if not clinic:
        raise HTTPException(status_code=404, detail="Клиника не найдена")
    
    clinic_id = clinic["id"]
    
    # Проверяем существование пациента или создаем нового
    async with db.execute(
        "SELECT id FROM patients WHERE clinic_id = ? AND phone = ?",
        (clinic_id, body.patient_phone)
    ) as cur:
        patient = await cur.fetchone()
    
    if patient:
        patient_id = patient["id"]
    else:
        # Создаем нового пациента
        async with db.execute(
            "INSERT INTO patients (clinic_id, phone, first_name, last_name, consent_given) VALUES (?, ?, ?, ?, 1)",
            (clinic_id, body.patient_phone, body.patient_first_name, body.patient_last_name or "")
        ) as cur:
            patient_id = cur.lastrowid
    
    # Создаем запись
    async with db.execute(
        """INSERT INTO appointments 
           (clinic_id, patient_id, doctor_id, service_id, start_time, end_time, status, notes)
           VALUES (?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
        (clinic_id, patient_id, body.doctor_id, body.service_id, 
         body.start_time, body.end_time, body.notes)
    ) as cur:
        appointment_id = cur.lastrowid
    
    await db.commit()
    
    return {
        "success": True,
        "appointment_id": appointment_id,
        "message": "Запись успешно создана"
    }

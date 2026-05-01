"""
routers/schedules.py
Doctor schedule management - working hours and available time slots
"""

from fastapi import APIRouter, Depends, HTTPException
import aiosqlite
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, time

from database import get_db
from middleware.auth import get_current_user, CurrentUser

router = APIRouter(prefix="/schedules", tags=["schedules"])


class TimeSlot(BaseModel):
    start_time: str  # HH:MM format
    end_time: str    # HH:MM format


class DoctorSchedule(BaseModel):
    doctor_id: int
    day_of_week: int  # 0=Monday, 6=Sunday
    start_time: str   # HH:MM
    end_time: str     # HH:MM
    slot_duration: int = 30  # minutes


class DoctorScheduleResponse(BaseModel):
    id: int
    doctor_id: int
    doctor_name: str
    day_of_week: int
    start_time: str
    end_time: str
    slot_duration: int


class AvailableSlot(BaseModel):
    date: str
    time: str
    available: bool


@router.get("", response_model=List[DoctorScheduleResponse])
async def get_schedules(
    current_user: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db)
):
    """Get all doctor schedules for the clinic"""
    async with db.execute(
        """SELECT s.id, s.doctor_id, d.name as doctor_name, s.day_of_week, 
                  s.start_time, s.end_time, s.slot_duration
           FROM doctor_schedules s
           JOIN doctors d ON s.doctor_id = d.id
           WHERE d.clinic_id = ?
           ORDER BY d.name, s.day_of_week""",
        (current_user.clinic_id,)
    ) as cur:
        schedules = await cur.fetchall()
    
    return [DoctorScheduleResponse(**dict(s)) for s in schedules]


@router.post("", status_code=201)
async def create_schedule(
    schedule: DoctorSchedule,
    current_user: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db)
):
    """Create a new doctor schedule"""
    # Verify doctor belongs to clinic
    async with db.execute(
        "SELECT id FROM doctors WHERE id = ? AND clinic_id = ?",
        (schedule.doctor_id, current_user.clinic_id)
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Doctor not found")
    
    # Check for overlapping schedules
    async with db.execute(
        """SELECT id FROM doctor_schedules 
           WHERE doctor_id = ? AND day_of_week = ?
           AND ((start_time <= ? AND end_time > ?) OR (start_time < ? AND end_time >= ?))""",
        (schedule.doctor_id, schedule.day_of_week, 
         schedule.start_time, schedule.start_time,
         schedule.end_time, schedule.end_time)
    ) as cur:
        if await cur.fetchone():
            raise HTTPException(status_code=400, detail="Overlapping schedule exists")
    
    async with db.execute(
        """INSERT INTO doctor_schedules (doctor_id, day_of_week, start_time, end_time, slot_duration)
           VALUES (?, ?, ?, ?, ?)""",
        (schedule.doctor_id, schedule.day_of_week, schedule.start_time, 
         schedule.end_time, schedule.slot_duration)
    ) as cur:
        schedule_id = cur.lastrowid
    
    await db.commit()
    return {"id": schedule_id, "message": "Schedule created"}


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db)
):
    """Delete a doctor schedule"""
    # Verify schedule belongs to clinic
    async with db.execute(
        """SELECT s.id FROM doctor_schedules s
           JOIN doctors d ON s.doctor_id = d.id
           WHERE s.id = ? AND d.clinic_id = ?""",
        (schedule_id, current_user.clinic_id)
    ) as cur:
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Schedule not found")
    
    await db.execute("DELETE FROM doctor_schedules WHERE id = ?", (schedule_id,))
    await db.commit()
    return {"message": "Schedule deleted"}


@router.get("/available-slots/{doctor_id}")
async def get_available_slots(
    doctor_id: int,
    date: str,  # YYYY-MM-DD
    service_id: int,
    db: aiosqlite.Connection = Depends(get_db)
):
    """Get available time slots for a doctor on a specific date"""
    # Get service duration
    async with db.execute(
        "SELECT duration_minutes FROM services WHERE id = ?",
        (service_id,)
    ) as cur:
        service = await cur.fetchone()
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")
        duration = service["duration_minutes"]
    
    # Get day of week (0=Monday)
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    day_of_week = date_obj.weekday()
    
    # Get doctor's schedule for this day
    async with db.execute(
        """SELECT start_time, end_time, slot_duration
           FROM doctor_schedules
           WHERE doctor_id = ? AND day_of_week = ?""",
        (doctor_id, day_of_week)
    ) as cur:
        schedules = await cur.fetchall()
    
    if not schedules:
        return []
    
    # Get existing appointments for this date
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


from datetime import timedelta

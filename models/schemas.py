"""
models/schemas.py
Pydantic v2 схемы для запросов и ответов.
"""

from __future__ import annotations
from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


# ─────────────────────────────────────────────────────────────
#  Auth
# ─────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=72, description="Password (6-72 characters)")
    clinic_name: str = Field(min_length=2)
    address: str = ""
    timezone: str = "Europe/Moscow"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    user_id: int
    email: str
    clinic_id: int
    clinic_name: str
    trial_start_date: Optional[str] = None
    trial_end_date: Optional[str] = None
    is_active: bool = True
    is_trial_expired: bool = False
    booking_slug: Optional[str] = None


# ─────────────────────────────────────────────────────────────
#  Clinic
# ─────────────────────────────────────────────────────────────
class ClinicUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    timezone: Optional[str] = None
    whatsapp_instance_id: Optional[str] = None
    whatsapp_api_token: Optional[str] = None


class ClinicOut(BaseModel):
    id: int
    name: str
    address: str
    timezone: str
    whatsapp_instance_id: Optional[str]
    whatsapp_api_token: Optional[str]
    created_at: str


class TemplatesUpdate(BaseModel):
    reminder_24h: Optional[str] = None
    reminder_2h: Optional[str] = None


class TemplatesOut(BaseModel):
    reminder_24h: str
    reminder_2h: str


# ─────────────────────────────────────────────────────────────
#  Service
# ─────────────────────────────────────────────────────────────
class ServiceCreate(BaseModel):
    name: str
    duration_minutes: int = 30
    color: str = "#3788d8"


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    duration_minutes: Optional[int] = None
    color: Optional[str] = None


class ServiceOut(BaseModel):
    id: int
    clinic_id: int
    name: str
    duration_minutes: int
    color: str


# ─────────────────────────────────────────────────────────────
#  Doctor
# ─────────────────────────────────────────────────────────────
class DoctorCreate(BaseModel):
    name: str
    specialty: Optional[str] = None


class DoctorUpdate(BaseModel):
    name: Optional[str] = None
    specialty: Optional[str] = None


class DoctorOut(BaseModel):
    id: int
    clinic_id: int
    name: str
    specialty: Optional[str]


# ─────────────────────────────────────────────────────────────
#  Patient
# ─────────────────────────────────────────────────────────────
class PatientCreate(BaseModel):
    phone: str = Field(pattern=r"^7\d{10}$")
    first_name: str
    last_name: Optional[str] = None
    consent_given: bool = True


class PatientUpdate(BaseModel):
    phone: Optional[str] = Field(default=None, pattern=r"^7\d{10}$")
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    consent_given: Optional[bool] = None


class PatientOut(BaseModel):
    id: int
    clinic_id: int
    phone: str
    first_name: str
    last_name: Optional[str]
    consent_given: bool


# ─────────────────────────────────────────────────────────────
#  Appointment
# ─────────────────────────────────────────────────────────────
class AppointmentCreate(BaseModel):
    patient_id: int
    doctor_id: int
    service_id: int
    start_time: datetime  # Treated as Asia/Almaty (UTC+5) timezone
    end_time: Optional[datetime] = None   # если None, вычислим из duration
    notes: Optional[str] = None
    
    class Config:
        # Accept timezone-naive datetime strings as Almaty time
        json_encoders = {
            datetime: lambda v: v.strftime("%Y-%m-%dT%H:%M:%S") if v else None
        }


class AppointmentUpdate(BaseModel):
    patient_id: Optional[int] = None
    doctor_id: Optional[int] = None
    service_id: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    notes: Optional[str] = None


class StatusPatch(BaseModel):
    status: Literal["scheduled", "confirmed", "cancelled", "no_show"]


class AppointmentOut(BaseModel):
    id: int
    clinic_id: int
    patient_id: int
    doctor_id: int
    service_id: int
    start_time: str
    end_time: str
    status: str
    notes: Optional[str]
    created_at: str
    # расширенные поля для календаря
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    service_name: Optional[str] = None
    service_color: Optional[str] = None


# ─────────────────────────────────────────────────────────────
#  Stats
# ─────────────────────────────────────────────────────────────
class StatsOut(BaseModel):
    total: int
    confirmed: int
    cancelled: int
    no_show: int
    rate: str  # процент явок: (total-cancelled-no_show)/total


# ─────────────────────────────────────────────────────────────
#  Webhook (Green API)
# ─────────────────────────────────────────────────────────────
class WAMessage(BaseModel):
    """Упрощённая схема входящего вебхука Green API."""
    typeWebhook: str
    instanceData: Optional[dict] = None
    senderData: Optional[dict] = None
    messageData: Optional[dict] = None

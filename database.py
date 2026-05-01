"""
database.py
Инициализация SQLite и создание таблиц при первом запуске.
Используем aiosqlite для async-доступа из FastAPI.
"""

import aiosqlite
from config import settings

DB_PATH = settings.DATABASE_URL

# ─────────────────────────────────────────────────────────────
#  DDL — создание таблиц (IF NOT EXISTS — идемпотентно)
# ─────────────────────────────────────────────────────────────
DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS clinics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    address     TEXT    NOT NULL DEFAULT '',
    timezone    TEXT    NOT NULL DEFAULT 'Europe/Moscow',
    template_24h TEXT,
    template_2h  TEXT,
    whatsapp_instance_id TEXT,
    whatsapp_api_token   TEXT,
    trial_start_date TEXT,
    trial_end_date   TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    booking_slug TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id     INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS services (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id        INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    name             TEXT    NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    color            TEXT    NOT NULL DEFAULT '#3788d8'
);

CREATE TABLE IF NOT EXISTS doctors (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    name      TEXT    NOT NULL,
    specialty TEXT
);

CREATE TABLE IF NOT EXISTS doctor_schedules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id     INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    day_of_week   INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6),
    start_time    TEXT    NOT NULL,
    end_time      TEXT    NOT NULL,
    slot_duration INTEGER NOT NULL DEFAULT 30,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS patients (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id     INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    phone         TEXT    NOT NULL,
    first_name    TEXT    NOT NULL,
    last_name     TEXT,
    consent_given INTEGER NOT NULL DEFAULT 1,
    UNIQUE (clinic_id, phone)
);

CREATE TABLE IF NOT EXISTS appointments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id  INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    doctor_id  INTEGER NOT NULL REFERENCES doctors(id),
    service_id INTEGER NOT NULL REFERENCES services(id),
    start_time TEXT    NOT NULL,
    end_time   TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'scheduled'
               CHECK (status IN ('scheduled','confirmed','cancelled','no_show')),
    notes      TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS patient_teeth (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    tooth_number  INTEGER NOT NULL CHECK (tooth_number >= 11 AND tooth_number <= 48),
    status        TEXT    NOT NULL DEFAULT 'healthy'
                  CHECK (status IN ('healthy','caries','filled','implant','missing','observation')),
    diagnosis_code TEXT,
    notes         TEXT,
    updated_by    INTEGER REFERENCES users(id),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(patient_id, tooth_number)
);

CREATE TABLE IF NOT EXISTS tooth_images (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    INTEGER NOT NULL,
    tooth_number  INTEGER NOT NULL,
    file_path     TEXT    NOT NULL,
    file_name     TEXT,
    file_size     INTEGER,
    uploaded_by   INTEGER REFERENCES users(id),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (patient_id, tooth_number) REFERENCES patient_teeth(patient_id, tooth_number)
);

CREATE TABLE IF NOT EXISTS tooth_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    INTEGER NOT NULL,
    tooth_number  INTEGER NOT NULL,
    old_status    TEXT,
    new_status    TEXT,
    changed_by    INTEGER REFERENCES users(id),
    changed_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id       INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    type                 TEXT    NOT NULL CHECK (type IN ('reminder_24h','reminder_2h')),
    sent_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    status               TEXT    NOT NULL DEFAULT 'sent'
                         CHECK (status IN ('sent','failed','delivered')),
    whatsapp_message_id  TEXT
);
"""


async def init_db() -> None:
    """Создаём таблицы при старте приложения (идемпотентно)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(DDL)
        await db.commit()


async def get_db() -> aiosqlite.Connection:
    """
    Dependency для FastAPI.
    Возвращает соединение с row_factory=aiosqlite.Row (dict-like строки).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        yield db

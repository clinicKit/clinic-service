import asyncio
import re
import aiosqlite
import asyncpg
from config import settings

DB_URL = settings.DATABASE_URL
IS_POSTGRES = DB_URL.startswith("postgresql://") or DB_URL.startswith("postgres://")

# ─────────────────────────────────────────────────────────────
#  DDL — создание таблиц (PostgreSQL & SQLite compatibility)
# ─────────────────────────────────────────────────────────────
def get_ddl():
    ddl = """
    CREATE TABLE IF NOT EXISTS clinics (
        id          {auto_inc_pk},
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
        created_at  TEXT    NOT NULL DEFAULT {now}
    );

    CREATE TABLE IF NOT EXISTS users (
        id            {auto_inc_pk},
        clinic_id     INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
        email         TEXT    NOT NULL UNIQUE,
        password_hash TEXT    NOT NULL,
        created_at    TEXT    NOT NULL DEFAULT {now}
    );

    CREATE TABLE IF NOT EXISTS services (
        id               {auto_inc_pk},
        clinic_id        INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
        name             TEXT    NOT NULL,
        duration_minutes INTEGER NOT NULL DEFAULT 30,
        color            TEXT    NOT NULL DEFAULT '#3788d8'
    );

    CREATE TABLE IF NOT EXISTS doctors (
        id        {auto_inc_pk},
        clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
        name      TEXT    NOT NULL,
        specialty TEXT
    );

    CREATE TABLE IF NOT EXISTS doctor_schedules (
        id            {auto_inc_pk},
        doctor_id     INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
        day_of_week   INTEGER NOT NULL,
        start_time    TEXT    NOT NULL,
        end_time      TEXT    NOT NULL,
        slot_duration INTEGER NOT NULL DEFAULT 30,
        created_at    TEXT    NOT NULL DEFAULT {now}
    );

    CREATE TABLE IF NOT EXISTS patients (
        id            {auto_inc_pk},
        clinic_id     INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
        phone         TEXT    NOT NULL,
        first_name    TEXT    NOT NULL,
        last_name     TEXT,
        consent_given INTEGER NOT NULL DEFAULT 1,
        UNIQUE (clinic_id, phone)
    );

    CREATE TABLE IF NOT EXISTS appointments (
        id         {auto_inc_pk},
        clinic_id  INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
        patient_id INTEGER NOT NULL REFERENCES patients(id),
        doctor_id  INTEGER NOT NULL REFERENCES doctors(id),
        service_id INTEGER NOT NULL REFERENCES services(id),
        start_time TEXT    NOT NULL,
        end_time   TEXT    NOT NULL,
        status     TEXT    NOT NULL DEFAULT 'scheduled',
        notes      TEXT,
        created_at TEXT    NOT NULL DEFAULT {now}
    );

    CREATE TABLE IF NOT EXISTS patient_teeth (
        id            {auto_inc_pk},
        patient_id    INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        tooth_number  INTEGER NOT NULL,
        status        TEXT    NOT NULL DEFAULT 'healthy',
        diagnosis_code TEXT,
        notes         TEXT,
        updated_by    INTEGER REFERENCES users(id),
        created_at    TEXT    NOT NULL DEFAULT {now},
        updated_at    TEXT    NOT NULL DEFAULT {now},
        UNIQUE(patient_id, tooth_number)
    );

    CREATE TABLE IF NOT EXISTS tooth_images (
        id            {auto_inc_pk},
        patient_id    INTEGER NOT NULL,
        tooth_number  INTEGER NOT NULL,
        file_path     TEXT    NOT NULL,
        file_name     TEXT,
        file_size     INTEGER,
        uploaded_by   INTEGER REFERENCES users(id),
        created_at    TEXT    NOT NULL DEFAULT {now},
        FOREIGN KEY (patient_id, tooth_number) REFERENCES patient_teeth(patient_id, tooth_number)
    );

    CREATE TABLE IF NOT EXISTS tooth_history (
        id            {auto_inc_pk},
        patient_id    INTEGER NOT NULL,
        tooth_number  INTEGER NOT NULL,
        old_status    TEXT,
        new_status    TEXT,
        changed_by    INTEGER REFERENCES users(id),
        changed_at    TEXT    NOT NULL DEFAULT {now}
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id                   {auto_inc_pk},
        appointment_id       INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
        type                 TEXT    NOT NULL,
        sent_at              TEXT    NOT NULL DEFAULT {now},
        status               TEXT    NOT NULL DEFAULT 'sent',
        whatsapp_message_id  TEXT
    );
    """
    if IS_POSTGRES:
        return ddl.format(
            auto_inc_pk="SERIAL PRIMARY KEY",
            now="CURRENT_TIMESTAMP::text"
        )
    else:
        return ddl.format(
            auto_inc_pk="INTEGER PRIMARY KEY AUTOINCREMENT",
            now="(datetime('now'))"
        )

# ─────────────────────────────────────────────────────────────
#  PostgreSQL Wrapper for asyncpg to match aiosqlite interface
# ─────────────────────────────────────────────────────────────

class PostgresCursor:
    def __init__(self, conn, sql, params):
        self.conn = conn
        self.sql = self._convert_placeholders(sql)
        self.params = params
        self.rows = None
        self.lastrowid = None

    def _convert_placeholders(self, sql):
        count = [0]
        def replace(match):
            count[0] += 1
            return f"${count[0]}"
        return re.sub(r'\?', replace, sql)

    async def __aenter__(self):
        if self.sql.strip().upper().startswith("INSERT"):
            # Append RETURNING id to get lastrowid
            sql_with_returning = f"{self.sql.rstrip(';')} RETURNING id"
            try:
                self.lastrowid = await self.conn.fetchval(sql_with_returning, *self.params)
            except Exception:
                # If RETURNING id fails, just execute normally
                await self.conn.execute(self.sql, *self.params)
        else:
            self.rows = await self.conn.fetch(self.sql, *self.params)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def fetchall(self):
        return [dict(r) for r in self.rows] if self.rows else []

    async def fetchone(self):
        return dict(self.rows[0]) if self.rows else None

class PostgresConnection:
    def __init__(self, pool):
        self.pool = pool
        self.conn = None

    async def __aenter__(self):
        self.conn = await self.pool.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.pool.release(self.conn)

    def execute(self, sql, params=()):
        return PostgresCursor(self.conn, sql, params)

    async def commit(self):
        pass # asyncpg handles autocommit or transactions differently

# Pool for Postgres
pg_pool = None

async def init_db() -> None:
    global pg_pool
    if IS_POSTGRES:
        pg_pool = await asyncpg.create_pool(DB_URL)
        async with pg_pool.acquire() as conn:
            for statement in get_ddl().split(";"):
                if statement.strip():
                    await conn.execute(statement)
    else:
        async with aiosqlite.connect(DB_URL) as db:
            await db.executescript(get_ddl())
            await db.commit()

async def get_db():
    if IS_POSTGRES:
        global pg_pool
        if not pg_pool:
            pg_pool = await asyncpg.create_pool(DB_URL)
        async with PostgresConnection(pg_pool) as db:
            yield db
    else:
        async with aiosqlite.connect(DB_URL) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            yield db

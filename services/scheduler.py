"""
services/scheduler.py
Фоновый планировщик напоминаний.

Каждую минуту проверяет таблицу appointments:
- если до start_time осталось <= 24ч + 5мин (запас) и напоминание reminder_24h ещё не отправлено — отправляем;
- если до start_time осталось <= 2ч + 5мин и напоминание reminder_2h ещё не отправлено — отправляем.

Используем APScheduler (AsyncIOScheduler).
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database import get_db
from services.whatsapp import (
    DEFAULT_TEMPLATE_24H,
    DEFAULT_TEMPLATE_2H,
    render_template,
    send_whatsapp_message,
)

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def _send_reminders() -> None:
    """Основная логика, вызываемая каждую минуту."""
    now_utc = datetime.now(timezone.utc)
    window_24h_start = now_utc
    window_24h_end = now_utc + timedelta(hours=24, minutes=5)
    window_2h_end = now_utc + timedelta(hours=2, minutes=5)

    async for db in get_db():
        # Получаем все предстоящие записи со статусом scheduled
        async with db.execute(
            """
            SELECT
                a.id, a.start_time, a.patient_id, a.doctor_id, a.service_id, a.clinic_id,
                p.phone, p.first_name, p.last_name,
                d.name AS doctor_name,
                s.name AS service_name,
                c.address AS clinic_address, c.timezone,
                c.template_24h, c.template_2h,
                c.whatsapp_instance_id, c.whatsapp_api_token
            FROM appointments a
            JOIN patients  p ON p.id = a.patient_id
            JOIN doctors   d ON d.id = a.doctor_id
            JOIN services  s ON s.id = a.service_id
            JOIN clinics   c ON c.id = a.clinic_id
            WHERE a.status = 'scheduled'
              AND a.start_time > ?
            """,
            (now_utc.strftime("%Y-%m-%dT%H:%M:%S"),),
        ) as cur:
            rows = await cur.fetchall()

        for row in rows:
            appt_id = row["id"]
            start_str = row["start_time"]

            # Парсим время записи (хранится в UTC ISO)
            try:
                start_dt = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning("Некорректный формат start_time для записи %s", appt_id)
                continue

            patient_name = row["first_name"] + (" " + row["last_name"] if row["last_name"] else "")
            local_date = start_dt.strftime("%d.%m.%Y")
            local_time = start_dt.strftime("%H:%M")  # UTC; в продакшене конвертировать по timezone

            template_vars = dict(
                patient_name=patient_name,
                date=local_date,
                time=local_time,
                doctor_name=row["doctor_name"],
                service_name=row["service_name"],
                clinic_address=row["clinic_address"] or "",
            )

            # Проверяем, какие уведомления уже отправлены для этой записи
            async with db.execute(
                "SELECT type FROM notifications WHERE appointment_id = ? AND status = 'sent'",
                (appt_id,),
            ) as n_cur:
                sent_types = {r["type"] for r in await n_cur.fetchall()}

            # ── 24h-напоминание ──────────────────────────────────────────
            if (
                "reminder_24h" not in sent_types
                and window_24h_start <= start_dt <= window_24h_end
            ):
                template = row["template_24h"] or DEFAULT_TEMPLATE_24H
                message = render_template(template, **template_vars)
                msg_id = await send_whatsapp_message(
                    phone=row["phone"],
                    message=message,
                    instance_id=row["whatsapp_instance_id"],
                    api_token=row["whatsapp_api_token"],
                )
                status_val = "sent" if msg_id else "failed"
                await db.execute(
                    """
                    INSERT INTO notifications (appointment_id, type, sent_at, status, whatsapp_message_id)
                    VALUES (?, 'reminder_24h', ?, ?, ?)
                    """,
                    (appt_id, now_utc.strftime("%Y-%m-%dT%H:%M:%S"), status_val, msg_id),
                )
                await db.commit()
                logger.info("reminder_24h для записи %s: %s", appt_id, status_val)

            # ── 2h-напоминание ───────────────────────────────────────────
            if (
                "reminder_2h" not in sent_types
                and window_24h_start <= start_dt <= window_2h_end
            ):
                template = row["template_2h"] or DEFAULT_TEMPLATE_2H
                message = render_template(template, **template_vars)
                msg_id = await send_whatsapp_message(
                    phone=row["phone"],
                    message=message,
                    instance_id=row["whatsapp_instance_id"],
                    api_token=row["whatsapp_api_token"],
                )
                status_val = "sent" if msg_id else "failed"
                await db.execute(
                    """
                    INSERT INTO notifications (appointment_id, type, sent_at, status, whatsapp_message_id)
                    VALUES (?, 'reminder_2h', ?, ?, ?)
                    """,
                    (appt_id, now_utc.strftime("%Y-%m-%dT%H:%M:%S"), status_val, msg_id),
                )
                await db.commit()
                logger.info("reminder_2h для записи %s: %s", appt_id, status_val)


def start_scheduler() -> None:
    """Запускает планировщик. Вызывается при старте приложения."""
    scheduler.add_job(_send_reminders, "interval", minutes=1, id="reminders", replace_existing=True)
    scheduler.start()
    logger.info("Планировщик напоминаний запущен (интервал: 1 мин)")


def stop_scheduler() -> None:
    """Останавливает планировщик. Вызывается при завершении приложения."""
    scheduler.shutdown(wait=False)
    logger.info("Планировщик остановлен")

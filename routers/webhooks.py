"""
routers/webhooks.py
Вебхук для входящих уведомлений Green API.
POST /webhooks/whatsapp

При получении сообщения «Отмена» / «не смогу» от пациента:
- ищем его активные записи в ближайшие 48ч
- переводим в статус 'cancelled'
- отправляем подтверждение пациенту
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
import aiosqlite

from database import get_db
from services.whatsapp import send_whatsapp_message, delete_notification

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Ключевые слова для определения намерения отменить
CANCEL_PATTERNS = re.compile(r"отмен|не смог|не приду|не могу", re.IGNORECASE)


def _extract_phone(chat_id: str) -> str:
    """
    Извлекает номер телефона из chatId формата '7XXXXXXXXXX@c.us'.
    Возвращает строку вида '7XXXXXXXXXX'.
    """
    return chat_id.split("@")[0]


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    """
    Принимает входящие уведомления от Green API.
    Структура тела: https://green-api.com/docs/api/receiving/notifications/

    Пример:
    {
      "typeWebhook": "incomingMessageReceived",
      "senderData": { "chatId": "79991234567@c.us", "sender": "79991234567@c.us" },
      "messageData": { "typeMessage": "textMessage", "textMessageData": { "textMessage": "Отмена" } },
      "receiptId": 12345
    }
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "bad_request"}

    webhook_type = body.get("typeWebhook", "")

    # Обрабатываем только входящие текстовые сообщения
    if webhook_type != "incomingMessageReceived":
        return {"status": "ignored"}

    sender_data = body.get("senderData", {})
    message_data = body.get("messageData", {})
    receipt_id = body.get("receiptId")

    chat_id = sender_data.get("chatId", "")
    msg_type = message_data.get("typeMessage", "")

    if msg_type != "textMessage":
        return {"status": "ignored", "reason": "not_text"}

    text = message_data.get("textMessageData", {}).get("textMessage", "")
    phone = _extract_phone(chat_id)

    logger.info("Входящее сообщение от %s: %s", phone, text)

    # Ищем пациента по номеру (во всех клиниках — ограничиваемся активными)
    async with db.execute(
        "SELECT id, clinic_id, first_name FROM patients WHERE phone = ?", (phone,)
    ) as cur:
        patient = await cur.fetchone()

    if not patient:
        logger.info("Пациент с телефоном %s не найден", phone)
        # Всё равно удаляем уведомление из очереди Green API
        if receipt_id:
            await _try_delete_notification(db, phone, receipt_id)
        return {"status": "patient_not_found"}

    # Проверяем намерение отменить
    if CANCEL_PATTERNS.search(text):
        now_utc = datetime.now(timezone.utc)
        window_end = (now_utc + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%S")
        now_str = now_utc.strftime("%Y-%m-%dT%H:%M:%S")

        # Ищем предстоящие записи пациента
        async with db.execute(
            """
            SELECT a.id, a.start_time, s.name AS service_name, c.whatsapp_instance_id, c.whatsapp_api_token
            FROM appointments a
            JOIN services s ON s.id = a.service_id
            JOIN clinics  c ON c.id = a.clinic_id
            WHERE a.patient_id = ?
              AND a.status = 'scheduled'
              AND a.start_time BETWEEN ? AND ?
            """,
            (patient["id"], now_str, window_end),
        ) as cur:
            upcoming = await cur.fetchall()

        if not upcoming:
            logger.info("Нет предстоящих записей для пациента %s", phone)
            return {"status": "no_upcoming_appointments"}

        cancelled_ids = []
        for appt in upcoming:
            await db.execute(
                "UPDATE appointments SET status = 'cancelled' WHERE id = ?", (appt["id"],)
            )
            cancelled_ids.append(appt["id"])

            # Отправляем подтверждение пациенту
            start_dt = appt["start_time"]
            try:
                dt = datetime.fromisoformat(start_dt)
                date_str = dt.strftime("%d.%m.%Y")
                time_str = dt.strftime("%H:%M")
            except ValueError:
                date_str = start_dt
                time_str = ""

            confirm_msg = (
                f"✅ Ваша запись на {date_str} в {time_str} «{appt['service_name']}» отменена.\n"
                "Позвоните нам для переноса."
            )
            await send_whatsapp_message(
                phone=phone,
                message=confirm_msg,
                instance_id=appt["whatsapp_instance_id"],
                api_token=appt["whatsapp_api_token"],
            )

        await db.commit()
        logger.info("Отменены записи %s для пациента %s", cancelled_ids, phone)

    # Удаляем уведомление из очереди Green API
    if receipt_id:
        await _try_delete_notification(db, phone, receipt_id)

    return {"status": "ok"}


async def _try_delete_notification(db: aiosqlite.Connection, phone: str, receipt_id: int):
    """
    Пытаемся найти инстанс клиники пациента и удалить уведомление из Green API.
    """
    async with db.execute(
        """
        SELECT c.whatsapp_instance_id, c.whatsapp_api_token
        FROM patients p
        JOIN clinics c ON c.id = p.clinic_id
        WHERE p.phone = ?
        LIMIT 1
        """,
        (phone,),
    ) as cur:
        clinic = await cur.fetchone()

    if clinic:
        await delete_notification(
            receipt_id,
            instance_id=clinic["whatsapp_instance_id"],
            api_token=clinic["whatsapp_api_token"],
        )

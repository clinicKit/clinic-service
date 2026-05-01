"""
services/whatsapp.py
Обёртка для работы с Green API WhatsApp Gateway.
Документация: https://green-api.com/docs/api/
"""

import logging
from typing import Optional

import aiohttp

from config import settings

logger = logging.getLogger(__name__)

# Дефолтные шаблоны (используются, если клиника не задала свои)
DEFAULT_TEMPLATE_24H = (
    "Здравствуйте, {patient_name}! 🦷\n"
    "Напоминаем, что завтра {date} в {time} у вас запись "
    "на «{service_name}» к врачу {doctor_name}.\n"
    "Адрес: {clinic_address}\n\n"
    "Для отмены ответьте «Отмена»."
)

DEFAULT_TEMPLATE_2H = (
    "Здравствуйте, {patient_name}! ⏰\n"
    "Напоминаем, что через 2 часа в {time} у вас запись "
    "на «{service_name}» к врачу {doctor_name}.\n"
    "Адрес: {clinic_address}\n\n"
    "Для отмены ответьте «Отмена»."
)


def _phone_to_chat_id(phone: str) -> str:
    """
    Преобразует номер формата 7XXXXXXXXXX в chatId для Green API.
    Если начинается с 8 — заменяем на 7.
    """
    phone = phone.strip().lstrip("+")
    if phone.startswith("8"):
        phone = "7" + phone[1:]
    return f"{phone}@c.us"


def render_template(template: str, **kwargs) -> str:
    """Подставляет переменные в шаблон. kwargs — именованные аргументы."""
    try:
        return template.format(**kwargs)
    except KeyError as e:
        logger.warning("Не найдена переменная в шаблоне: %s", e)
        return template


async def send_whatsapp_message(
    phone: str,
    message: str,
    instance_id: Optional[str] = None,
    api_token: Optional[str] = None,
) -> Optional[str]:
    """
    Отправляет сообщение через Green API.
    Возвращает idMessage при успехе, None при ошибке.

    Приоритет: параметры функции > env-переменные.
    """
    instance = instance_id or settings.WHATSAPP_INSTANCE
    token = api_token or settings.WHATSAPP_TOKEN
    base_url = settings.WHATSAPP_API_URL

    if not instance or not token:
        logger.error("WhatsApp не настроен: отсутствуют WHATSAPP_INSTANCE / WHATSAPP_TOKEN")
        return None

    url = f"{base_url}/waInstance{instance}/sendMessage/{token}"
    chat_id = _phone_to_chat_id(phone)

    payload = {"chatId": chat_id, "message": message}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("idMessage")
                else:
                    text = await resp.text()
                    logger.error("Green API error %s: %s", resp.status, text)
                    return None
    except Exception as exc:
        logger.exception("Ошибка при отправке в WhatsApp: %s", exc)
        return None


async def delete_notification(receipt_id: int, instance_id: Optional[str] = None, api_token: Optional[str] = None) -> bool:
    """
    Удаляет уведомление из очереди Green API (после обработки вебхука).
    """
    instance = instance_id or settings.WHATSAPP_INSTANCE
    token = api_token or settings.WHATSAPP_TOKEN
    base_url = settings.WHATSAPP_API_URL

    if not instance or not token:
        return False

    url = f"{base_url}/waInstance{instance}/deleteNotification/{token}/{receipt_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
    except Exception as exc:
        logger.exception("Ошибка при удалении уведомления Green API: %s", exc)
        return False

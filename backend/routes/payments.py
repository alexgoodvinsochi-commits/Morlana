import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import httpx

from config import settings
from services.auth import validate_telegram_init_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


class CreateInvoiceRequest(BaseModel):
    initData: str
    plan: str  # "monthly" or "quarterly"


class InvoiceResponse(BaseModel):
    invoice_link: str


PLANS = {
    "monthly": {
        "title": "Morlana Premium — 1 месяц",
        "description": "Безлимитные расклады с премиальными моделями ИИ",
        "payload": "subscription_monthly",
        "prices": [{"label": "Подписка", "amount": 29900}],  # 299 RUB in kopecks
    },
    "quarterly": {
        "title": "Morlana Premium — 3 месяца",
        "description": "Безлимитные расклады с премиальными моделями ИИ (скидка 22%)",
        "payload": "subscription_quarterly",
        "prices": [{"label": "Подписка", "amount": 69900}],  # 699 RUB in kopecks
    },
}


@router.post("/create-invoice", response_model=InvoiceResponse)
async def create_invoice(req: CreateInvoiceRequest):
    if not settings.PAYMENT_PROVIDER_TOKEN or settings.PAYMENT_PROVIDER_TOKEN == "YOUR_PAYMENT_PROVIDER_TOKEN":
        raise HTTPException(status_code=503, detail="Payment system not configured")

    user_data = validate_telegram_init_data(req.initData)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")

    plan = PLANS.get(req.plan)
    if not plan:
        raise HTTPException(status_code=400, detail="Invalid plan")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/createInvoiceLink",
            json={
                "title": plan["title"],
                "description": plan["description"],
                "payload": plan["payload"],
                "provider_token": settings.PAYMENT_PROVIDER_TOKEN,
                "currency": "RUB",
                "prices": plan["prices"],
                "need_name": False,
                "need_email": False,
                "need_phone_number": False,
                "need_shipping_address": False,
            },
        )

    if response.status_code != 200:
        logger.error(f"Telegram API error: {response.text}")
        raise HTTPException(status_code=502, detail="Failed to create invoice")

    data = response.json()
    if not data.get("ok"):
        logger.error(f"Telegram API error: {data}")
        raise HTTPException(status_code=502, detail=data.get("description", "Unknown error"))

    return InvoiceResponse(invoice_link=data["result"])

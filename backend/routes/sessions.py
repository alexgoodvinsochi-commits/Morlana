from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import TarotSession
from schemas import SessionCloseRequest

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.post("/close")
async def close_session(req: SessionCloseRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        update(TarotSession)
        .where(TarotSession.id == req.session_id, TarotSession.status == "active")
        .values(status="archived")
    )
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Session not found or already archived")

    return {"status": "archived"}

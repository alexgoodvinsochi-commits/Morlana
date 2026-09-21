from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from routes.reading import _get_init_data, _get_owned_session, _get_user_from_init_data
from schemas import SessionCloseRequest

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.post("/close")
async def close_session(
    req: SessionCloseRequest,
    initData: str = Depends(_get_init_data),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_from_init_data(initData, db)
    tarot_session = await _get_owned_session(db, req.session_id, user)

    if tarot_session.status != "active":
        raise HTTPException(status_code=404, detail="Session not found or already archived")

    tarot_session.status = "archived"
    await db.commit()

    return {"status": "archived"}

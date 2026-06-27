from routes.astrology import router as astrology_router
from routes.tarot import router as tarot_router
from routes.sessions import router as sessions_router
from routes.reading import router as reading_router
# from routes.payments import router as payments_router

__all__ = ["astrology_router", "tarot_router", "sessions_router", "reading_router"]  # , "payments_router"]

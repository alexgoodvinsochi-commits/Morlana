from routes.astrology import router as astrology_router
from routes.reading import router as reading_router
from routes.auth import router as auth_router
# from routes.payments import router as payments_router

__all__ = ["astrology_router", "reading_router", "auth_router"]  # , "payments_router"]

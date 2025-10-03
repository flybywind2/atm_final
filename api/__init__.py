# api/__init__.py - API 모듈 초기화
from .health import router as health_router
from .review import router as review_router
from .confluence import router as confluence_router
from .dashboard import router as dashboard_router

__all__ = [
    "health_router",
    "review_router",
    "confluence_router",
    "dashboard_router",
]

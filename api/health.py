# api/health.py - 헬스체크 및 정적 페이지 엔드포인트
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/")
async def root():
    """루트 경로에서 index.html 제공"""
    return FileResponse("static/index.html")


@router.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy", "service": "AI Proposal Reviewer"}


@router.get("/dashboard")
async def dashboard_page():
    """대시보드 HTML 제공"""
    return FileResponse("static/dashboard.html")

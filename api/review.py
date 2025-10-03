# api/review.py - 제안서 검토 관련 엔드포인트
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse
import json
import asyncio
from typing import Callable, Dict
from fastapi import WebSocket

router = APIRouter(prefix="/api/v1/review", tags=["review"])

# 의존성 주입을 위한 전역 변수들
_active_connections: Dict[str, WebSocket] = {}
_process_review_func: Callable = None
_generate_job_title_func: Callable = None
_create_job_func: Callable = None
_update_job_feedback_func: Callable = None
_update_job_status_func: Callable = None
_get_job_func: Callable = None


def init_review_router(
    active_connections: Dict[str, WebSocket],
    process_review_func: Callable,
    generate_job_title_func: Callable,
    create_job_func: Callable,
    update_job_feedback_func: Callable,
    update_job_status_func: Callable,
    get_job_func: Callable,
):
    """라우터 초기화 - 필요한 함수들을 주입"""
    global _active_connections, _process_review_func, _generate_job_title_func
    global _create_job_func, _update_job_feedback_func, _update_job_status_func, _get_job_func

    _active_connections = active_connections
    _process_review_func = process_review_func
    _generate_job_title_func = generate_job_title_func
    _create_job_func = create_job_func
    _update_job_feedback_func = update_job_feedback_func
    _update_job_status_func = update_job_status_func
    _get_job_func = get_job_func


@router.post("/submit")
async def submit_proposal(
    domain: str = Form(...),
    division: str = Form(...),
    hitl_stages: str = Form("[]"),
    enable_sequential_thinking: str = Form("false"),
    file: UploadFile = File(None),
    text: str = Form(None)
):
    """
    제안서 제출 - 파일 업로드 또는 텍스트 직접 입력
    """
    proposal_content = ""

    if file:
        # 파일 업로드 방식
        contents = await file.read()
        # MVP: 간단한 텍스트 추출
        if file.filename.endswith(('.txt', '.md')):
            proposal_content = contents.decode('utf-8', errors='ignore')
        else:
            # PDF/DOCX는 추후 고도화
            proposal_content = contents.decode('utf-8', errors='ignore')
    elif text:
        # 텍스트 직접 입력 방식
        proposal_content = text
    else:
        return JSONResponse(
            status_code=400,
            content={"error": "파일 또는 텍스트를 제공해주세요"}
        )

    # HITL 단계 파싱
    try:
        hitl_stages_list = json.loads(hitl_stages)
    except:
        hitl_stages_list = []  # 기본값: HITL 비활성화

    # Sequential Thinking 활성화 여부 파싱
    enable_seq_thinking = enable_sequential_thinking.lower() == "true"

    # 로그 출력
    print(f"[Job Submission] Sequential Thinking: {'활성화' if enable_seq_thinking else '비활성화'}")

    # 제목 자동 생성 (LLM)
    generated_title = await _generate_job_title_func(proposal_content, fallback=f"{domain} 제안서")

    # DB에 저장하고 job_id 생성
    job_id = _create_job_func(
        proposal_content,
        domain,
        division,
        title=generated_title,
        hitl_stages=hitl_stages_list,
        enable_sequential_thinking=enable_seq_thinking,
    )

    # 백그라운드에서 검토 프로세스 시작
    print(f"Starting background task for job {job_id}")
    asyncio.create_task(_process_review_func(job_id))

    return {"job_id": job_id, "status": "submitted"}


@router.post("/feedback/{job_id}")
async def submit_feedback(job_id: int, feedback: dict):
    """HITL 피드백 제출"""
    print(f"[DEBUG] Feedback received (Job {job_id}): {feedback}")

    # 피드백 텍스트 추출
    feedback_text = feedback.get("feedback", "") or ""
    if isinstance(feedback_text, str):
        feedback_text = feedback_text.strip()
    else:
        feedback_text = str(feedback_text)

    skip_requested = bool(feedback.get("skip"))
    print(f"[DEBUG] Feedback text: {feedback_text}")
    print(f"[DEBUG] Skip requested: {skip_requested}")

    # 피드백을 job의 metadata에 저장
    _update_job_feedback_func(job_id, feedback_text, skip=skip_requested)

    # DB 상태를 feedback_received로 업데이트
    _update_job_status_func(job_id, "feedback_received")

    print(f"[DEBUG] Feedback saved and status updated for job {job_id}")

    return {"status": "feedback_received", "job_id": job_id, "skip": skip_requested}


@router.get("/pdf/{job_id}")
async def download_pdf(job_id: int):
    """PDF 다운로드"""
    # MVP: 간단한 응답
    return {"message": "PDF 생성 기능은 추후 구현 예정", "job_id": job_id}

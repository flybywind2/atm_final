# api/review.py - 제안서 검토 관련 엔드포인트
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse
import json
import asyncio
from typing import Callable, Dict
from fastapi import WebSocket
import sys
import os

# utils 모듈 import를 위한 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.file_parser import extract_text_from_file, extract_text_and_images_from_file
from utils.internal_vlm import internal_vlm_client

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
    image_descriptions = []

    if file:
        # 파일 업로드 방식
        contents = await file.read()
        filename_lower = file.filename.lower()

        # 이미지 파일 확장자 체크
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg')
        is_image_file = filename_lower.endswith(image_extensions)

        # 이미지 파일인 경우 직접 VLM 처리
        if is_image_file and internal_vlm_client.is_enabled():
            print(f"[VLM] Direct image file upload detected: {file.filename}")
            try:
                # Base64 인코딩
                image_base64 = internal_vlm_client.encode_image_to_base64(contents)

                # VLM으로 이미지 분석
                description = internal_vlm_client.analyze_image(
                    image_base64,
                    prompt="이 이미지는 제안서 관련 이미지입니다. 이미지에서 보이는 내용을 상세하게 설명하고, 제안서 검토에 도움이 될 만한 정보를 추출해주세요.",
                    max_tokens=1500
                )

                proposal_content = f"업로드된 이미지: {file.filename}\n\n"
                proposal_content += "="*80 + "\n"
                proposal_content += "이미지 분석 결과\n"
                proposal_content += "="*80 + "\n"
                proposal_content += description

                print(f"[VLM] Image analyzed successfully")
            except Exception as img_err:
                print(f"[VLM] Error analyzing image: {str(img_err)}")
                proposal_content = f"[이미지 분석 실패: {str(img_err)}]"

        # VLM이 활성화되어 있고 문서 파일인 경우 이미지도 추출하여 분석
        elif internal_vlm_client.is_enabled():
            text_content, images = extract_text_and_images_from_file(contents, file.filename)
            proposal_content = text_content

            # 추출된 이미지를 VLM으로 분석
            if images:
                print(f"[VLM] Found {len(images)} images in {file.filename}")
                for idx, image_bytes in enumerate(images, 1):
                    try:
                        # Base64 인코딩
                        image_base64 = internal_vlm_client.encode_image_to_base64(image_bytes)

                        # VLM으로 이미지 분석
                        description = internal_vlm_client.analyze_image(
                            image_base64,
                            prompt=f"이 이미지는 제안서의 {idx}번째 이미지입니다. 이미지에서 보이는 내용을 상세하게 설명하고, 제안서 검토에 도움이 될 만한 정보를 추출해주세요.",
                            max_tokens=1000
                        )
                        image_descriptions.append(f"[이미지 {idx}]\n{description}")
                        print(f"[VLM] Image {idx} analyzed successfully")
                    except Exception as img_err:
                        print(f"[VLM] Error analyzing image {idx}: {str(img_err)}")
                        continue

                # 이미지 설명을 제안서 내용에 추가
                if image_descriptions:
                    proposal_content += "\n\n" + "="*80 + "\n"
                    proposal_content += "이미지 분석 결과\n"
                    proposal_content += "="*80 + "\n"
                    proposal_content += "\n\n".join(image_descriptions)
        else:
            # VLM 비활성화 시 또는 이미지 파일이지만 VLM 비활성화
            if is_image_file:
                proposal_content = f"[이미지 파일 업로드됨: {file.filename}]\n\n이미지 분석을 위해 VLM을 활성화해주세요."
            else:
                # 일반 문서 파일의 텍스트만 추출
                proposal_content = extract_text_from_file(contents, file.filename)

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

    # 입력 방식 결정
    input_method = "file" if file else "text"

    # DB에 저장하고 job_id 생성
    job_id = _create_job_func(
        proposal_content,
        domain,
        division,
        title=generated_title,
        hitl_stages=hitl_stages_list,
        enable_sequential_thinking=enable_seq_thinking,
        input_method=input_method,
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

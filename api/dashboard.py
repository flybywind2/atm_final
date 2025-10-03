# api/dashboard.py - 대시보드 및 Job CRUD 엔드포인트
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Callable

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

# 의존성 주입을 위한 전역 변수들
_list_jobs_func: Callable = None
_count_jobs_func: Callable = None
_get_job_func: Callable = None
_create_job_func: Callable = None
_update_job_record_func: Callable = None
_delete_job_func: Callable = None
_generate_job_title_func: Callable = None


class JobCreateRequest(BaseModel):
    title: Optional[str] = None
    proposal_content: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    division: str = Field(..., min_length=1)
    status: str = "pending"
    human_decision: str = "pending"
    llm_decision: Optional[str] = None
    hitl_stages: Optional[List[int]] = None
    metadata: Optional[dict] = None


class JobUpdateRequest(BaseModel):
    title: Optional[str] = None
    proposal_content: Optional[str] = None
    domain: Optional[str] = None
    division: Optional[str] = None
    status: Optional[str] = None
    human_decision: Optional[str] = None
    llm_decision: Optional[str] = None
    hitl_stages: Optional[List[int]] = None
    metadata: Optional[dict] = None


def init_dashboard_router(
    list_jobs_func: Callable,
    count_jobs_func: Callable,
    get_job_func: Callable,
    create_job_func: Callable,
    update_job_record_func: Callable,
    delete_job_func: Callable,
    generate_job_title_func: Callable,
):
    """라우터 초기화 - 필요한 함수들을 주입"""
    global _list_jobs_func, _count_jobs_func, _get_job_func, _create_job_func
    global _update_job_record_func, _delete_job_func, _generate_job_title_func

    _list_jobs_func = list_jobs_func
    _count_jobs_func = count_jobs_func
    _get_job_func = get_job_func
    _create_job_func = create_job_func
    _update_job_record_func = update_job_record_func
    _delete_job_func = delete_job_func
    _generate_job_title_func = generate_job_title_func


def _sanitize_decision(decision: str | None) -> str | None:
    """결정 값 정규화"""
    if not decision:
        return decision
    normalized = decision.strip()
    return normalized


def _coerce_hitl_stages(values: Optional[List[int] | List[str]]) -> Optional[List[int]]:
    """HITL 단계 값을 정수 리스트로 변환"""
    if values is None:
        return None
    coerced = []
    for item in values:
        try:
            coerced.append(int(item))
        except (TypeError, ValueError):
            continue
    return coerced


@router.get("/jobs")
async def dashboard_list(
    status: Optional[str] = None,
    decision: Optional[str] = None,
    llm_decision: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    order: str = "desc",
):
    """Job 목록 조회 (필터링, 페이징, 검색 지원)"""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    jobs = _list_jobs_func(
        limit=limit,
        offset=offset,
        status=status,
        decision=decision,
        llm_decision=llm_decision,
        search=search,
        order=order,
    )

    total = _count_jobs_func(status=status, decision=decision, llm_decision=llm_decision, search=search)

    formatted_jobs = []
    for job in jobs:
        job_copy = job.copy()
        proposal_text = (job_copy.get("proposal_content") or "")
        job_copy["proposal_preview"] = proposal_text[:200]
        formatted_jobs.append(job_copy)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "jobs": formatted_jobs,
    }


@router.get("/jobs/{job_id}")
async def dashboard_get_job_detail(job_id: int):
    """특정 Job 상세 조회"""
    job = _get_job_func(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="존재하지 않는 작업입니다.")
    return job


@router.post("/jobs")
async def dashboard_create_job(payload: JobCreateRequest):
    """새 Job 생성"""
    metadata_payload = payload.metadata.copy() if payload.metadata else {}
    hitl_stages = payload.hitl_stages
    if hitl_stages is None and "hitl_stages" in metadata_payload:
        hitl_stages = _coerce_hitl_stages(metadata_payload.pop("hitl_stages"))
    else:
        hitl_stages = _coerce_hitl_stages(hitl_stages)

    human_decision_value = _sanitize_decision(payload.human_decision) or "pending"
    llm_decision_value = _sanitize_decision(payload.llm_decision) if payload.llm_decision else "pending"
    title_value = (payload.title or "").strip()
    if not title_value:
        title_value = await _generate_job_title_func(payload.proposal_content, fallback=f"{payload.domain} 제안서")

    job_id = _create_job_func(
        payload.proposal_content,
        payload.domain,
        payload.division,
        title=title_value,
        status=payload.status,
        human_decision=human_decision_value,
        llm_decision=llm_decision_value,
        metadata=metadata_payload,
        hitl_stages=hitl_stages,
    )

    created_job = _get_job_func(job_id)
    return created_job


@router.put("/jobs/{job_id}")
async def dashboard_update_job(job_id: int, payload: JobUpdateRequest):
    """Job 업데이트"""
    existing = _get_job_func(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="존재하지 않는 작업입니다.")

    metadata_payload = None
    if payload.metadata is not None:
        base_metadata = existing.get("metadata", {}).copy()
        if payload.metadata == {}:
            base_metadata = {}
        else:
            base_metadata.update(payload.metadata)
        metadata_payload = base_metadata

    if payload.hitl_stages is not None:
        stages = _coerce_hitl_stages(payload.hitl_stages)
        if metadata_payload is None:
            metadata_payload = existing.get("metadata", {}).copy()
        metadata_payload["hitl_stages"] = stages or []

    success = _update_job_record_func(
        job_id,
        title=payload.title,
        proposal_content=payload.proposal_content,
        domain=payload.domain,
        division=payload.division,
        status=payload.status,
        human_decision=_sanitize_decision(payload.human_decision) if payload.human_decision is not None else None,
        llm_decision=_sanitize_decision(payload.llm_decision) if payload.llm_decision is not None else None,
        metadata=metadata_payload,
    )

    if not success:
        raise HTTPException(status_code=400, detail="업데이트할 필드가 없습니다.")

    return _get_job_func(job_id)


@router.delete("/jobs/{job_id}")
async def dashboard_delete_job(job_id: int):
    """Job 삭제"""
    job = _get_job_func(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="존재하지 않는 작업입니다.")

    _delete_job_func(job_id)
    return {"status": "deleted", "job_id": job_id}

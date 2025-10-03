# api/confluence.py - Confluence 페이지 처리 엔드포인트
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
import asyncio
import json
import os
from typing import Callable, Dict
from fastapi import WebSocket

router = APIRouter(prefix="/api/v1/confluence", tags=["confluence"])

# 의존성 주입을 위한 전역 변수들
_active_connections: Dict[str, WebSocket] = {}
_process_confluence_pages_sequentially_func: Callable = None
_get_page_content_func: Callable = None
_get_child_pages_func: Callable = None
_get_pages_recursively_func: Callable = None
_generate_job_title_func: Callable = None
_create_job_func: Callable = None


def init_confluence_router(
    active_connections: Dict[str, WebSocket],
    process_confluence_pages_sequentially_func: Callable,
    get_page_content_func: Callable,
    get_child_pages_func: Callable,
    get_pages_recursively_func: Callable,
    generate_job_title_func: Callable,
    create_job_func: Callable,
):
    """라우터 초기화 - 필요한 함수들을 주입"""
    global _active_connections, _process_confluence_pages_sequentially_func
    global _get_page_content_func, _get_child_pages_func, _get_pages_recursively_func
    global _generate_job_title_func, _create_job_func

    _active_connections = active_connections
    _process_confluence_pages_sequentially_func = process_confluence_pages_sequentially_func
    _get_page_content_func = get_page_content_func
    _get_child_pages_func = get_child_pages_func
    _get_pages_recursively_func = get_pages_recursively_func
    _generate_job_title_func = generate_job_title_func
    _create_job_func = create_job_func


@router.post("/fetch-pages")
async def fetch_confluence_pages(
    page_id: str = Form(...),
    include_children: bool = Form(True),
    include_current: bool = Form(True),
    max_depth: int = Form(2)
):
    """
    Confluence 페이지 가져오기
    - page_id: Confluence 페이지 ID
    - include_children: 하위 페이지 포함 여부
    - include_current: 현재 페이지 포함 여부
    - max_depth: 하위 페이지 탐색 깊이 (1-5)
    """
    try:
        if not page_id:
            return JSONResponse(
                status_code=400,
                content={"error": "page_id가 필요합니다"}
            )

        # 깊이 제한
        max_depth = max(1, min(max_depth, 5))

        if include_children:
            # 재귀적으로 페이지 가져오기
            pages = await asyncio.to_thread(
                _get_pages_recursively_func,
                page_id,
                include_current=include_current,
                max_depth=max_depth,
                current_depth=0
            )
        else:
            # 현재 페이지만 가져오기
            page = await asyncio.to_thread(_get_page_content_func, page_id)
            pages = [page] if page else []

        if not pages:
            return JSONResponse(
                status_code=404,
                content={"error": "페이지를 찾을 수 없습니다"}
            )

        # 페이지 정보 요약
        page_summaries = [
            {
                "id": p.get("id"),
                "title": p.get("title"),
                "content_length": len(p.get("content", "")),
                "space": p.get("space")
            }
            for p in pages
        ]

        return {
            "status": "success",
            "page_count": len(pages),
            "pages": page_summaries,
            "combined_content_length": sum(len(p.get("content", "")) for p in pages)
        }

    except Exception as e:
        print(f"Confluence 페이지 가져오기 실패: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"페이지 가져오기 실패: {str(e)}"}
        )


@router.post("/submit-for-review")
async def submit_confluence_for_review(
    page_id: str = Form(...),
    include_children: bool = Form(True),
    include_current: bool = Form(True),
    max_depth: int = Form(2),
    domain: str = Form("제조"),
    division: str = Form("메모리"),
    hitl_stages: str = Form("[]"),
    enable_sequential_thinking: str = Form("false")
):
    """
    Confluence 페이지를 가져와서 검토 시작
    """
    try:
        # 깊이 제한
        max_depth = max(1, min(max_depth, 5))

        # 페이지 가져오기
        if include_children:
            pages = await asyncio.to_thread(
                _get_pages_recursively_func,
                page_id,
                include_current=include_current,
                max_depth=max_depth,
                current_depth=0
            )
        else:
            page = await asyncio.to_thread(_get_page_content_func, page_id)
            pages = [page] if page else []

        if not pages:
            return JSONResponse(
                status_code=404,
                content={"error": "페이지를 찾을 수 없습니다"}
            )

        # HITL 단계 파싱
        try:
            hitl_stages_list = json.loads(hitl_stages)
        except:
            hitl_stages_list = []

        # Sequential Thinking 활성화 여부 파싱
        enable_seq_thinking = enable_sequential_thinking.lower() == "true"

        # 로그 출력
        print(f"[Confluence Job Submission] Sequential Thinking: {'활성화' if enable_seq_thinking else '비활성화'}")

        # 각 페이지별로 job 생성 및 순차 처리
        job_ids = []
        page_list = [{"id": p.get("id"), "title": p.get("title") or ""} for p in pages]

        confluence_base_url = os.getenv("CONFLUENCE_BASE_URL", "")

        for idx, page in enumerate(pages):
            raw_title = page.get('title') or ''
            page_content = f"{'='*80}\n페이지: {raw_title}\nID: {page.get('id')}\n{'='*80}\n{page.get('content')}"
            job_title = raw_title.strip() or await _generate_job_title_func(page_content, fallback=f"Confluence 페이지 {idx+1}")

            # Confluence 페이지 URL 생성
            confluence_url = f"{confluence_base_url}/pages/viewpage.action?pageId={page.get('id')}" if confluence_base_url and page.get('id') else None

            job_id = _create_job_func(
                page_content,
                domain,
                division,
                title=job_title,
                hitl_stages=hitl_stages_list,
                confluence_page_id=page.get('id'),
                confluence_page_url=confluence_url,
                enable_sequential_thinking=enable_seq_thinking,
            )
            page_list[idx]["title"] = job_title
            job_ids.append(job_id)
            print(f"Created job {job_id} for page {idx+1}/{len(pages)}: {job_title}")

        # 첫 번째 페이지부터 순차적으로 처리 시작
        print(f"Starting sequential processing for {len(job_ids)} pages")
        asyncio.create_task(_process_confluence_pages_sequentially_func(job_ids, page_list))

        return {
            "status": "submitted",
            "job_id": job_ids[0],  # 첫 번째 job_id를 메인으로 사용
            "job_ids": job_ids,
            "page_count": len(pages),
            "pages": page_list
        }

    except Exception as e:
        print(f"Confluence 검토 제출 실패: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"검토 제출 실패: {str(e)}"}
        )


@router.get("/child-pages/{page_id}")
async def get_confluence_child_pages(page_id: str):
    """특정 페이지의 하위 페이지 목록 조회"""
    try:
        children = await asyncio.to_thread(_get_child_pages_func, page_id)

        return {
            "status": "success",
            "page_id": page_id,
            "child_count": len(children),
            "children": children
        }

    except Exception as e:
        print(f"하위 페이지 조회 실패: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"하위 페이지 조회 실패: {str(e)}"}
        )

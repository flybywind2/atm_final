# main.py - FastAPI 통합 서버 구현
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
from pathlib import Path
import ollama
import os
import uuid
import json
import re
import requests
from dotenv import load_dotenv

from database.db import (
    init_database,
    create_job,
    get_job,
    list_jobs,
    update_job_status,
    update_job_record,
    update_job_feedback,
    reset_feedback_state,
    delete_job,
    count_jobs,
)
from typing import Optional
from config.settings import HOST, PORT
from confluence_api import get_page_content, get_child_pages, get_pages_recursively, combine_pages_content

# Import agent modules
from agents import (
    run_bp_scouter,
    run_objective_reviewer,
    run_data_analyzer,
    run_risk_analyzer,
    run_roi_estimator,
    run_final_generator,
    run_proposal_improver,
)

# Import API routers
from api.health import router as health_router
from api.review import init_review_router, router as review_router
from api.confluence import init_confluence_router, router as confluence_router
from api.dashboard import init_dashboard_router, router as dashboard_router
from api.pdf_export import init_pdf_export_router, router as pdf_export_router

# 환경 변수 로드
load_dotenv()

app = FastAPI(title="AI Proposal Reviewer", version="1.0.0")

# CORS 설정 (MVP: 모든 origin 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙 (프론트엔드)
static_path = Path("static")
if static_path.exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

# WebSocket 연결 관리
active_connections: dict[str, WebSocket] = {}


def _extract_json_dict(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _truncate_for_prompt(text: str, limit: int = 800) -> str:
    if not text:
        return ''
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + '...'


def _generate_title_sync(content: str, fallback: str) -> str:
    prompt_body = _truncate_for_prompt(content, 600)
    prompt = f"""
당신은 제안서 제목을 만드는 전문가입니다. 아래 제안서 내용을 보고 핵심을 표현하는 25자 이하의 한국어 제목을 작성하세요.
제목은 특수문자 없이 간결하게 작성하고, JSON 형식으로만 응답하세요.

제안서:
{prompt_body}

응답 형식:
{{"title": "여기에 제목"}}
"""
    response = call_llm(prompt)
    data = _extract_json_dict(response)
    if data and isinstance(data.get('title'), str):
        title = data['title'].strip()
        if title:
            return title[:50]
    snippet_lines = (content or '').strip().splitlines()
    for line in snippet_lines:
        line = line.strip()
        if line:
            return line[:50]
    return fallback


async def generate_job_title(content: str, fallback: str) -> str:
    return await asyncio.to_thread(_generate_title_sync, content, fallback)


@app.on_event("startup")
async def startup_event():
    """서버 시작 시 데이터베이스 및 LLM 초기화"""
    print("Server starting...")
    init_database()
    print("Database ready")
    init_llm()
    print("LLM ready")

    # Initialize API routers with dependencies
    init_review_router(
        active_connections=active_connections,
        process_review_func=process_review,
        generate_job_title_func=generate_job_title,
        create_job_func=create_job,
        update_job_feedback_func=update_job_feedback,
        update_job_status_func=update_job_status,
        get_job_func=get_job,
    )

    init_confluence_router(
        active_connections=active_connections,
        process_confluence_pages_sequentially_func=process_confluence_pages_sequentially,
        get_page_content_func=get_page_content,
        get_child_pages_func=get_child_pages,
        get_pages_recursively_func=get_pages_recursively,
        generate_job_title_func=generate_job_title,
        create_job_func=create_job,
    )

    init_dashboard_router(
        list_jobs_func=list_jobs,
        count_jobs_func=count_jobs,
        get_job_func=get_job,
        create_job_func=create_job,
        update_job_record_func=update_job_record,
        delete_job_func=delete_job,
        generate_job_title_func=generate_job_title,
    )

    init_pdf_export_router(
        get_job_func=get_job,
    )


# Register routers
app.include_router(health_router)
app.include_router(review_router)
app.include_router(confluence_router)
app.include_router(dashboard_router)
app.include_router(pdf_export_router)


# LLM 설정 및 초기화
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
llm_client = None

def init_llm():
    """환경 변수에 따라 LLM 클라이언트 초기화"""
    global llm_client

    if LLM_PROVIDER == "internal":
        # Internal LLM 설정 (lazy import to avoid pydantic version issues)
        from langchain_openai import ChatOpenAI

        base_url = os.getenv("INTERNAL_BASE_URL")
        model = os.getenv("INTERNAL_MODEL")
        credential_key = os.getenv("INTERNAL_CREDENTIAL_KEY")
        system_name = os.getenv("INTERNAL_SYSTEM_NAME")
        user_id = os.getenv("INTERNAL_USER_ID")

        llm_client = ChatOpenAI(
            base_url=base_url,
            model=model,
            default_headers={
                "x-dep-ticket": credential_key,
                "Send-System-Name": system_name,
                "User-ID": user_id,
                "User-Type": "AD",
                "Prompt-Msg-Id": str(uuid.uuid4()),
                "Completion-Msg-Id": str(uuid.uuid4()),
            },
        )
        print(f"Internal LLM initialized: {model}")
    else:
        # Ollama 설정
        llm_client = "ollama"  # Ollama는 직접 함수로 호출
        print(f"Ollama LLM initialized: {os.getenv('OLLAMA_MODEL', 'gemma2:2b')}")

def clean_unicode_for_cp949(text: str) -> str:
    """CP949 인코딩에서 문제가 되는 유니코드 문자를 안전하게 제거"""
    if not text:
        return text

    # CP949로 인코딩 가능한 문자만 유지
    try:
        # 먼저 CP949로 인코딩 시도
        text.encode('cp949')
        return text
    except UnicodeEncodeError:
        # 인코딩 실패 시 문자별로 처리
        cleaned = []
        for char in text:
            try:
                char.encode('cp949')
                cleaned.append(char)
            except UnicodeEncodeError:
                # CP949로 인코딩할 수 없는 문자는 공백 또는 ? 로 대체
                if char.isspace():
                    cleaned.append(' ')
                else:
                    cleaned.append('?')
        return ''.join(cleaned)

def call_llm(prompt: str, enable_sequential_thinking: bool = False, use_context7: bool = False) -> str:
    """통합 LLM 호출 함수

    Args:
        prompt: LLM에 전달할 프롬프트
        enable_sequential_thinking: Sequential Thinking MCP 활성화 여부
        use_context7: Context7 tool 활성화 여부

    Returns:
        LLM 응답 문자열
    """
    try:
        if LLM_PROVIDER == "internal":
            # Internal LLM 사용 (tool calling 지원)
            if enable_sequential_thinking or use_context7:
                # Tool calling 활성화
                from langchain_core.tools import tool

                @tool
                def sequential_thinking(
                    thought: str,
                    next_thought_needed: bool,
                    thought_number: int,
                    total_thoughts: int,
                    is_revision: bool = False,
                    revises_thought: int = None,
                    branch_from_thought: int = None,
                    branch_id: str = None,
                    needs_more_thoughts: bool = False
                ) -> str:
                    """Sequential Thinking tool for step-by-step reasoning.

                    This tool helps analyze problems through a flexible thinking process.
                    Each thought can build on, question, or revise previous insights.

                    Args:
                        thought: Current thinking step
                        next_thought_needed: Whether another thought step is needed
                        thought_number: Current thought number (starts at 1)
                        total_thoughts: Estimated total thoughts needed
                        is_revision: Whether this revises previous thinking
                        revises_thought: Which thought number is being reconsidered
                        branch_from_thought: Branching point thought number
                        branch_id: Branch identifier
                        needs_more_thoughts: If more thoughts are needed

                    Returns:
                        Confirmation message
                    """
                    print(f"[Sequential Thinking {thought_number}/{total_thoughts}] {thought[:100]}...")
                    return f"Thought {thought_number} recorded. Continue: {next_thought_needed}"

                @tool
                def context7_search(library_name: str, topic: str = None) -> str:
                    """Search library documentation using Context7.

                    Args:
                        library_name: Name of the library to search
                        topic: Optional topic to focus on

                    Returns:
                        Library documentation
                    """
                    print(f"[Context7] Searching {library_name} for topic: {topic}")
                    # Context7 실제 구현은 향후 추가 (현재는 placeholder)
                    return f"Documentation for {library_name} (topic: {topic})"

                tools = []
                if enable_sequential_thinking:
                    tools.append(sequential_thinking)
                if use_context7:
                    tools.append(context7_search)

                # Tool binding
                llm_with_tools = llm_client.bind_tools(tools)
                print(f"[LLM] Tool calling enabled: sequential_thinking={enable_sequential_thinking}, context7={use_context7}")

                response = llm_with_tools.invoke(prompt)

                # Tool calls 처리
                if hasattr(response, 'tool_calls') and response.tool_calls:
                    print(f"[LLM] Tool calls detected: {len(response.tool_calls)}")
                    for tool_call in response.tool_calls:
                        print(f"  - {tool_call.get('name', 'unknown')}: {str(tool_call.get('args', {}))[:100]}")

                # Clean response content to avoid encoding issues
                content = response.content
                return clean_unicode_for_cp949(content) if content else content
            else:
                # Tool 없이 일반 호출
                response = llm_client.invoke(prompt)
                # Clean response content to avoid encoding issues
                content = response.content
                return clean_unicode_for_cp949(content) if content else content
        else:
            # Ollama 사용 (tool calling 미지원, 일반 호출)
            model = os.getenv("OLLAMA_MODEL", "gemma2:2b")
            response = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}]
            )
            print(f"LLM response: {response['message']['content']}")
            return response['message']['content']
    except Exception as e:
        print(f"LLM API 호출 실패: {e}")
        import traceback
        traceback.print_exc()
        return f"AI 응답 생성 실패: {e}"

def call_ollama(prompt: str, model: str = "gemma3:1b", enable_sequential_thinking: bool = False, use_context7: bool = False) -> str:
    """Ollama를 통한 LLM 호출 (하위 호환성을 위해 유지, 내부적으로 call_llm 사용)"""
    return call_llm(prompt, enable_sequential_thinking=enable_sequential_thinking, use_context7=use_context7)

def retrieve_from_rag(query_text: str, num_result_doc: int = 5, retrieval_method: str = "rrf") -> list:
    """RAG를 통한 문서 검색

    Args:
        query_text: 검색 쿼리
        num_result_doc: 반환할 문서 수
        retrieval_method: 검색 방법 ("rrf", "bm25", "knn", "cc")

    Returns:
        검색 결과 리스트
    """
    try:
        # 환경 변수에서 RAG 설정 로드
        base_url = os.getenv("RAG_BASE_URL", "http://localhost:8000")
        credential_key = os.getenv("RAG_CREDENTIAL_KEY", "")
        rag_api_key = os.getenv("RAG_API_KEY", "")
        index_name = os.getenv("RAG_INDEX_NAME", "")
        permission_groups = os.getenv("RAG_PERMISSION_GROUPS", "user").split(",")

        # 검색 URL 설정
        retrieval_urls = {
            "rrf": f"{base_url}/retrieve-rrf",
            "bm25": f"{base_url}/retrieve-bm25",
            "knn": f"{base_url}/retrieve-knn",
            "cc": f"{base_url}/retrieve-cc"
        }

        retrieval_url = retrieval_urls.get(retrieval_method, retrieval_urls["rrf"])

        # 헤더 설정
        headers = {
            "Content-Type": "application/json",
            "x-dep-ticket": credential_key,
            "api-key": rag_api_key
        }

        # 요청 데이터 설정
        fields = {
            "index_name": index_name,
            "permission_groups": permission_groups,
            "query_text": query_text,
            "num_result_doc": num_result_doc,
            "fields_exclude": ["v_merge_title_content"]
        }

        # RAG API 호출
        response = requests.post(retrieval_url, headers=headers, json=fields, timeout=30)

        if response.status_code == 200:
            result = response.json()
            print(f"RAG 검색 완료: {len(result.get('hits', {}).get('hits', []))}건 검색됨")
            return result.get('hits', {}).get('hits', [])
        else:
            print(f"RAG API 호출 실패: {response.status_code} - {response.text}")
            return []

    except Exception as e:
        print(f"RAG 검색 실패: {e}")
        return []


async def rag_retrieve_bp_cases(domain: str, division: str, proposal_content: str = "") -> dict:
    """RAG를 통한 BP 사례 검색 (Agent 1용 래퍼 함수)

    Args:
        domain: 비즈니스 도메인
        division: 비즈니스 구역
        proposal_content: 제안서 내용 (검색 쿼리 개선용)

    Returns:
        dict: {"cases": [list of BP cases]}
    """
    # 제안서 내용에서 핵심 키워드 추출 (최대 200자)
    proposal_snippet = proposal_content[:200] if proposal_content else ""

    # 제안서 내용을 포함한 검색 쿼리 구성
    if proposal_snippet:
        query = f"{domain} {division} {proposal_snippet} BP 사례"
    else:
        query = f"{domain} {division} BP 사례"

    try:
        hits = await asyncio.to_thread(retrieve_from_rag, query, num_result_doc=5)
        cases = []
        for hit in hits:
            source = hit.get("_source", {})
            cases.append({
                "title": source.get("title", "제목 없음"),
                "tech_type": source.get("tech_type", "AI/ML"),
                "business_domain": source.get("business_domain") or source.get("domain", domain),
                "division": source.get("division", division),
                "problem_as_was": source.get("problem_as_was", source.get("content", "")[:100]),
                "solution_to_be": source.get("solution_to_be", ""),
                "summary": source.get("summary", source.get("content", "")[:200]),
                "tips": source.get("tips", ""),
                "link": source.get("link", "")  # Confluence URL
            })

        # RAG 검색 결과가 없으면 더미 데이터 반환
        if not cases:
            print(f"[DEBUG] RAG 검색 결과 없음, 더미 데이터 반환")
            cases = get_dummy_bp_cases(domain, division)

        return {"cases": cases}
    except Exception as e:
        print(f"BP 사례 검색 실패: {e}, 더미 데이터 반환")
        return {"cases": get_dummy_bp_cases(domain, division)}


def get_dummy_bp_cases(domain: str, division: str) -> list:
    """RAG 연결 전 테스트용 더미 BP 사례"""
    return [
        {
            "title": f"{domain} 분야 AI 기반 자동화 시스템 구축",
            "tech_type": "AI/ML - 자연어처리",
            "business_domain": domain,
            "division": division,
            "problem_as_was": f"{domain} 업무에서 수작업 처리로 인한 시간 소요 및 오류 발생 (하루 평균 4시간 소요)",
            "solution_to_be": "AI 기반 자동 분류 및 처리 시스템 도입으로 처리 시간 80% 단축 및 정확도 95% 달성",
            "summary": f"{domain} 분야에 AI 자동화를 도입하여 업무 효율성을 크게 향상시킨 사례. 6개월 내 ROI 200% 달성",
            "tips": "초기 데이터 품질 확보가 중요. 파일럿 프로젝트로 시작하여 점진적 확대 권장",
            "link": ""  # 더미 데이터는 링크 없음
        },
        {
            "title": f"{division} {domain} 데이터 분석 플랫폼 구축",
            "tech_type": "AI/ML - 예측 분석",
            "business_domain": domain,
            "division": division,
            "problem_as_was": "분산된 데이터로 인한 의사결정 지연 및 인사이트 부족",
            "solution_to_be": "통합 데이터 분석 플랫폼 구축으로 실시간 인사이트 제공 및 예측 정확도 향상",
            "summary": f"{division} 사업부의 {domain} 데이터를 통합 분석하여 의사결정 속도 3배 향상",
            "tips": "데이터 거버넌스 체계를 먼저 수립한 후 플랫폼 구축 시작",
            "link": ""
        },
        {
            "title": f"{domain} 최적화를 위한 머신러닝 모델 적용",
            "tech_type": "AI/ML - 최적화",
            "business_domain": domain,
            "division": division,
            "problem_as_was": "경험 기반 의사결정으로 인한 최적화 한계 및 리소스 낭비",
            "solution_to_be": "ML 기반 최적화 모델로 리소스 활용률 30% 개선 및 비용 절감",
            "summary": f"{domain} 업무 최적화를 위한 ML 모델 개발 및 적용 성공 사례",
            "tips": "도메인 전문가와 데이터 사이언티스트의 긴밀한 협업이 성공의 핵심",
            "link": ""
        }
    ]


async def process_confluence_pages_sequentially(job_ids: list, page_list: list):
    """Confluence 페이지들을 순차적으로 처리"""
    print(f"=== Sequential processing started for {len(job_ids)} pages ===")

    all_reports = []
    main_job_id = job_ids[0]  # 첫 번째 job_id를 메인 WebSocket으로 사용
    main_ws_key = str(main_job_id)  # WebSocket dict는 문자열 키를 사용

    for idx, job_id in enumerate(job_ids):
        page_info = page_list[idx]
        print(f"\n{'='*80}")
        print(f"Processing page {idx+1}/{len(job_ids)}: {page_info['title']} (Job ID: {job_id})")
        print(f"{'='*80}\n")

        # UI에 현재 처리 중인 페이지 알림
        if main_ws_key in active_connections:
            await active_connections[main_ws_key].send_json({
                "type": "page_progress",
                "current_page": idx + 1,
                "total_pages": len(job_ids),
                "page_title": page_info['title'],
                "page_id": page_info['id'],
                "job_id": job_id,
                "status": "processing",
                "message": f"📄 페이지 {idx+1}/{len(job_ids)} 분석 중: {page_info['title']}",
                "reset_agents": idx > 0
            })

        # 각 페이지 처리 (6개 에이전트 전체 플로우)
        await process_review(
            job_id,
            ws_job_key=main_ws_key,
            send_final_report=False
        )

        # 처리 완료된 job의 최종 report 가져오기
        job_data = get_job(job_id)
        if job_data and job_data.get('report'):
            page_report_data = {
                "page_title": page_info['title'],
                "page_id": page_info['id'],
                "job_id": job_id,
                "report": job_data['report'],
                "decision": job_data.get('llm_decision'),
                "decision_reason": (job_data.get('metadata') or {}).get('final_decision', {}).get('reason')
            }
            all_reports.append(page_report_data)

            # UI에 페이지별 완료 결과 즉시 전송
            if main_ws_key in active_connections:
                await active_connections[main_ws_key].send_json({
                    "status": "page_completed",
                    "current_page": idx + 1,
                    "total_pages": len(job_ids),
                    "page_title": page_info['title'],
                    "page_id": page_info['id'],
                    "page_report": job_data['report'],
                    "page_decision": job_data.get('llm_decision'),
                    "page_decision_reason": (job_data.get('metadata') or {}).get('final_decision', {}).get('reason')
                })

        # UI에 페이지 완료 알림
        if main_ws_key in active_connections:
            await active_connections[main_ws_key].send_json({
                "type": "page_progress",
                "current_page": idx + 1,
                "total_pages": len(job_ids),
                "page_title": page_info['title'],
                "page_id": page_info['id'],
                "job_id": job_id,
                "status": "completed",
                "message": f"✅ 페이지 {idx+1}/{len(job_ids)} 완료: {page_info['title']}"
            })

        print(f"\n[OK] Completed page {idx+1}/{len(job_ids)}: {page_info['title']}\n")

    # 모든 페이지 처리 완료 후 통합 리포트 생성
    print(f"\n{'='*80}")
    print(f"All {len(job_ids)} pages processed successfully")
    print(f"{'='*80}\n")

    # 첫 번째 job의 WebSocket으로 최종 완료 알림
    if job_ids and str(job_ids[0]) in active_connections:
        combined_report = "# 📚 Confluence 페이지별 검토 결과\n\n"
        combined_report += f"**총 {len(all_reports)}개 페이지 분석 완료**\n\n"
        combined_report += "---\n\n"

        for idx, report_data in enumerate(all_reports, 1):
            combined_report += f"## {idx}. {report_data['page_title']}\n\n"
            combined_report += report_data['report']
            decision_line = report_data.get('decision')
            reason = report_data.get('decision_reason')
            if decision_line:
                combined_report += f"\n\n**결정:** {decision_line}"
                if reason:
                    combined_report += f"<br>이유: {reason}"
            combined_report += "\n\n---\n\n"

        decisions_summary = [
            {
                "page_title": item.get("page_title"),
                "decision": item.get("decision"),
                "reason": item.get("decision_reason"),
            }
            for item in all_reports
        ]

        await active_connections[str(job_ids[0])].send_json({
            "status": "completed",
            "report": combined_report,
            "page_count": len(all_reports),
            "decisions": decisions_summary,
        })

async def process_review(job_id: int, ws_job_key: str | None = None, send_final_report: bool = True):
    """백그라운드 검토 프로세스 - 6개 에이전트 전체 플로우"""
    print(f"=== process_review ENTRY for job {job_id} ===")
    ws = None
    ws_key = ws_job_key or str(job_id)
    try:
        print(f"process_review started for job {job_id}")
        job = get_job(job_id)
        print(f"Job data retrieved for job {job_id}")
        if not job:
            print(f"Job {job_id} not found")
            return

        # HITL 단계 설정 가져오기
        hitl_stages = job.get("hitl_stages", [])
        print(f"HITL stages enabled: {hitl_stages}")

        # HITL 재시도 카운터 초기화 (각 에이전트당 최대 3회)
        hitl_retry_counts = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
        MAX_HITL_RETRIES = 3

        # 사용자 피드백 수집용 딕셔너리 (Agent 7에 전달)
        user_feedbacks = {}

        # Wait for WebSocket connection (up to 3 seconds)
        for i in range(30):
            ws = active_connections.get(ws_key)
            if ws:
                print(f"WebSocket connected on attempt {i+1}")
                break
            await asyncio.sleep(0.1)

        print(f"WebSocket connection: {ws}")
        print(f"Active connections: {list(active_connections.keys())}")
        domain = job.get("domain", "")
        division = job.get("division", "")
        print(f"Domain: {domain}, Division: {division}")

        # Agent 1: BP Case Scouter
        bp_cases = await run_bp_scouter(job_id, job, ws, domain, division,
                                         rag_retrieve_bp_cases, get_job, update_job_status)

        # Agent 2: Objective Reviewer
        objective_review = await run_objective_reviewer(job_id, job, ws, hitl_stages, hitl_retry_counts, bp_cases,
                                                          call_ollama, get_job, update_job_status, reset_feedback_state)
        # Agent 2 피드백 수집
        if 2 in hitl_stages:
            job_data = get_job(job_id)
            if job_data and job_data.get("metadata", {}).get("user_feedbacks", {}).get(2):
                user_feedbacks[2] = job_data["metadata"]["user_feedbacks"][2]

        # Agent 3: Data Analyzer
        data_analysis = await run_data_analyzer(job_id, job, ws, hitl_stages, hitl_retry_counts,
                                                  call_ollama, get_job, update_job_status, reset_feedback_state)
        # Agent 3 피드백 수집
        if 3 in hitl_stages:
            job_data = get_job(job_id)
            if job_data and job_data.get("metadata", {}).get("user_feedbacks", {}).get(3):
                user_feedbacks[3] = job_data["metadata"]["user_feedbacks"][3]

        # Agent 4: Risk Analyzer
        risk_analysis = await run_risk_analyzer(job_id, job, ws, hitl_stages, hitl_retry_counts,
                                                  call_ollama, get_job, update_job_status, reset_feedback_state)
        # Agent 4 피드백 수집
        if 4 in hitl_stages:
            job_data = get_job(job_id)
            if job_data and job_data.get("metadata", {}).get("user_feedbacks", {}).get(4):
                user_feedbacks[4] = job_data["metadata"]["user_feedbacks"][4]

        # Agent 5: ROI Estimator
        roi_estimation = await run_roi_estimator(job_id, job, ws, hitl_stages, hitl_retry_counts,
                                                   call_ollama, get_job, update_job_status, reset_feedback_state)
        # Agent 5 피드백 수집
        if 5 in hitl_stages:
            job_data = get_job(job_id)
            if job_data and job_data.get("metadata", {}).get("user_feedbacks", {}).get(5):
                user_feedbacks[5] = job_data["metadata"]["user_feedbacks"][5]

        # Agent 6: Final Generator
        # Don't send final report yet - wait for Agent 7
        # Agent 2~5 피드백을 Agent 6에 전달
        collected_feedbacks = {k: v for k, v in user_feedbacks.items() if k in [2, 3, 4, 5]}
        print(f"[DEBUG] Feedbacks from Agent 2~5 to pass to Agent 6: {collected_feedbacks}")

        await run_final_generator(
            job_id, job, ws, hitl_stages, hitl_retry_counts,
            objective_review, data_analysis, risk_analysis, roi_estimation, bp_cases,
            call_ollama, call_llm, get_job, update_job_status, reset_feedback_state,
            send_final_report=False,  # Agent 7 will send the final report
            ws_key=ws_key,
            active_connections=active_connections,
            user_feedbacks=collected_feedbacks
        )

        # Agent 7: Proposal Improver - Generate improved proposal
        # Get final_recommendation from Agent 6
        latest_job = get_job(job_id)
        final_recommendation = latest_job.get("metadata", {}).get("agent_results", {}).get("final_recommendation", "")

        # Agent 6 피드백 수집
        if 6 in hitl_stages:
            job_data = get_job(job_id)
            if job_data and job_data.get("metadata", {}).get("user_feedbacks", {}).get(6):
                user_feedbacks[6] = job_data["metadata"]["user_feedbacks"][6]

        print(f"[DEBUG] User feedbacks collected: {user_feedbacks}")

        improved_proposal = await run_proposal_improver(
            job_id, job, ws,
            objective_review, data_analysis, risk_analysis, roi_estimation, final_recommendation, bp_cases,
            call_ollama, get_job, update_job_status, user_feedbacks
        )

        # Update final report with improved proposal section
        # Always send final report after Agent 7
        if improved_proposal:
            latest_job_data = get_job(job_id)
            metadata = latest_job_data.get("metadata", {}).copy()
            current_report = metadata.get("report", "")

            # Add improved proposal section to report
            # Clean the improved proposal text to avoid encoding issues
            cleaned_proposal = improved_proposal.replace('\u202f', ' ').replace('\u00a0', ' ')
            improved_section = f"""
        <div class="accordion-item">
            <div class="accordion-header" onclick="toggleAccordion('section7')">
                <span>7. 개선된 지원서 제안</span>
                <span class="accordion-icon">▼</span>
            </div>
            <div id="section7" class="accordion-content" style="display: block;">
                <div style="background: #f8f9fa; padding: 15px; border-left: 4px solid #28a745;">
                    {cleaned_proposal.replace(chr(10), '<br>')}
                </div>
                <div style="margin-top: 15px; text-align: right;">
                    <button onclick="window.location.href='/api/export/improved-proposal/{job_id}'"
                            style="background-color: #28a745; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-size: 14px;">
                        📄 개선된 지원서 PDF 다운로드
                    </button>
                </div>
            </div>
        </div>
    """

            # Insert improved section before the final closing </div> tag
            # Find the last </div> and insert before it
            last_div_pos = current_report.rfind("</div>")
            if last_div_pos != -1:
                updated_report = current_report[:last_div_pos] + improved_section + current_report[last_div_pos:]
            else:
                updated_report = current_report
            metadata["report"] = updated_report

            update_job_status(job_id, "completed", metadata=metadata)

            # Send updated report via WebSocket (only if send_final_report is True)
            if send_final_report:
                target_ws = ws or (active_connections.get(ws_key) if active_connections and ws_key else None)
                if target_ws:
                    human_decision_value = latest_job_data.get("decision") or latest_job_data.get("human_decision")
                    decision_value = metadata.get("final_decision", {}).get("decision", "보류")
                    decision_reason = metadata.get("final_decision", {}).get("reason", "")

                    await target_ws.send_json({
                        "status": "completed",
                        "agent": "Proposal_Improver",
                        "message": "개선된 지원서 생성 완료",
                        "report": updated_report,
                        "decision": decision_value,
                        "decision_reason": decision_reason,
                        "human_decision": human_decision_value,
                        "current_page": 1,
                        "total_pages": 1,
                    })
                    print(f"[INFO] Sent final report for job {job_id}")
            else:
                print(f"[INFO] Skipped sending final report for job {job_id} (multi-page mode)")

    except Exception as e:
        print(f"!!! ERROR in review process: {e}")
        import traceback
        traceback.print_exc()
        if ws:
            try:
                await ws.send_json({"status": "error", "message": f"Error: {str(e)}"})
            except:
                pass
        update_job_status(job_id, "error")
    finally:
        print(f"=== process_review EXIT for job {job_id} ===")

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket 실시간 진행상황 업데이트"""
    await websocket.accept()
    active_connections[job_id] = websocket

    try:
        while True:
            # 클라이언트로부터 메시지 수신 (keep-alive)
            data = await websocket.receive_text()
            # 에코백 (연결 유지)
            await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        print(f"WebSocket 연결 종료: {job_id}")
        del active_connections[job_id]
    except Exception as e:
        print(f"WebSocket 에러: {e}")
        if job_id in active_connections:
            del active_connections[job_id]


if __name__ == "__main__":
    print(f"Server starting at http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)

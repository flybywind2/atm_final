# main.py - FastAPI 통합 서버 구현
from fastapi import FastAPI, UploadFile, File, WebSocket, Form, WebSocketDisconnect, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
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
from pydantic import BaseModel, Field
from typing import Optional, List
from config.settings import HOST, PORT
from confluence_api import get_page_content, get_child_pages, get_pages_recursively, combine_pages_content

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


def _classify_decision_sync(final_report: str, final_recommendation: str) -> dict:
    prompt = f"""
당신은 AI 프로젝트 심사위원입니다. 최종 보고서와 최종 의견을 읽고 과제를 '승인' 또는 '보류' 중 하나로 판단하세요.
결정 기준: 실행 가능성, 기대 효과, 리스크 수준, ROI 등을 종합적으로 고려합니다.
출력은 JSON 형식으로만 답변하며, 가능한 값은 "승인" 또는 "보류"입니다.

최종 보고서:
{_truncate_for_prompt(final_report, 1200)}

최종 의견:
{_truncate_for_prompt(final_recommendation, 800)}

응답 형식 예시:
{{"decision": "승인", "reason": "핵심 근거"}}
"""
    response = call_llm(prompt)
    data = _extract_json_dict(response) or {}
    decision = data.get('decision')
    if decision not in ('승인', '보류'):
        decision = '보류'
    reason = data.get('reason') or 'LLM 판단을 기준으로 자동 분류되었습니다.'
    return {'decision': decision, 'reason': reason}


async def classify_final_decision(final_report: str, final_recommendation: str) -> dict:
    return await asyncio.to_thread(_classify_decision_sync, final_report, final_recommendation)


def persist_job_metadata(job_id: int, new_status: str, agent_updates: dict | None = None, extra_updates: dict | None = None, **status_kwargs):
    job_snapshot = get_job(job_id) or {}
    metadata = job_snapshot.get("metadata", {}).copy()

    if agent_updates:
        agent_results = metadata.setdefault("agent_results", {})
        agent_results.update(agent_updates)

    if extra_updates:
        metadata.update(extra_updates)

    update_job_status(job_id, new_status, metadata=metadata, **status_kwargs)


@app.on_event("startup")
async def startup_event():
    """서버 시작 시 데이터베이스 및 LLM 초기화"""
    print("Server starting...")
    init_database()
    print("Database ready")
    init_llm()
    print("LLM ready")

@app.get("/")
async def root():
    """루트 경로에서 index.html 제공"""
    return FileResponse("static/index.html")

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy", "service": "AI Proposal Reviewer"}

@app.post("/api/v1/review/submit")
async def submit_proposal(
    domain: str = Form(...),
    division: str = Form(...),
    hitl_stages: str = Form("[]"),
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
    import json
    try:
        hitl_stages_list = json.loads(hitl_stages)
    except:
        hitl_stages_list = []  # 기본값: HITL 비활성화

    # 제목 자동 생성 (LLM)
    generated_title = await generate_job_title(proposal_content, fallback=f"{domain} 제안서")

    # DB에 저장하고 job_id 생성
    job_id = create_job(
        proposal_content,
        domain,
        division,
        title=generated_title,
        hitl_stages=hitl_stages_list,
    )

    # 백그라운드에서 검토 프로세스 시작
    print(f"Starting background task for job {job_id}")
    asyncio.create_task(process_review(job_id))

    return {"job_id": job_id, "status": "submitted"}

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

def call_llm(prompt: str) -> str:
    """통합 LLM 호출 함수"""
    try:
        if LLM_PROVIDER == "internal":
            # Internal LLM 사용
            response = llm_client.invoke(prompt)
            return response.content
        else:
            # Ollama 사용
            model = os.getenv("OLLAMA_MODEL", "gemma2:2b")
            response = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}]
            )
            return response['message']['content']
    except Exception as e:
        print(f"LLM API 호출 실패: {e}")
        return f"AI 응답 생성 실패: {e}"

def call_ollama(prompt: str, model: str = "gemma3:1b") -> str:
    """Ollama를 통한 LLM 호출 (하위 호환성을 위해 유지, 내부적으로 call_llm 사용)"""
    return call_llm(prompt)

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

def analyze_result_quality(agent_name: str, analysis_result: str, proposal_text: str) -> dict:
    """에이전트의 분석 결과 품질을 평가하여 재검토 필요 여부 판단

    Returns:
        {
            "needs_retry": bool,  # 재검토 필요 여부
            "reason": str,  # 재검토가 필요한 이유
            "additional_info_needed": list  # 필요한 추가 정보 항목들
        }
    """
    print(f"[DEBUG] Analyzing result quality for {agent_name}...")
    print(f"[DEBUG] Analysis result length: {len(analysis_result)}")

    quality_check_prompt = f"""당신은 AI 검토 프로세스의 품질 관리 orchestrator입니다.
{agent_name}가 다음과 같은 분석 결과를 제출했습니다.

제안서 내용:
{proposal_text[:500]}...

{agent_name}의 분석 결과:
{analysis_result}

위 분석 결과가 충분히 상세하고 구체적인지 평가해주세요.

**재검토가 필요한 경우 (needs_retry = true):**
- 분석 내용이 너무 짧거나 추상적인 경우 (2-3문장 미만)
- 구체적인 근거나 데이터가 부족한 경우
- 핵심 질문에 대한 답변이 불충분한 경우
- "평가 필요", "추가 검토 필요" 등 모호한 표현만 있는 경우
- 제안서 내용을 제대로 반영하지 않은 경우

**재검토가 불필요한 경우 (needs_retry = false):**
- 분석이 상세하고 구체적인 경우
- 명확한 근거와 함께 판단이 제시된 경우
- 요구사항에 맞게 충분한 정보를 제공한 경우
- 각 평가 항목이 구체적으로 설명된 경우

반드시 다음 JSON 형식으로만 응답하세요 (설명 없이 JSON만):
{{
    "needs_retry": true,
    "reason": "분석 내용이 너무 간략하고 구체적인 근거가 부족함",
    "additional_info_needed": ["구체적인 데이터", "상세한 근거", "명확한 판단 기준"]
}}

또는

{{
    "needs_retry": false,
    "reason": "분석이 충분히 상세하고 구체적임",
    "additional_info_needed": []
}}"""

    try:
        result = call_ollama(quality_check_prompt)
        print(f"[DEBUG] Raw quality check response: {result}")

        # JSON 파싱
        import json
        json_str = result.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        print(f"[DEBUG] Extracted JSON string: {json_str}")
        analysis = json.loads(json_str)
        print(f"[DEBUG] Parsed quality analysis: {analysis}")

        # needs_retry가 boolean이 아니면 변환
        if isinstance(analysis.get("needs_retry"), str):
            analysis["needs_retry"] = analysis["needs_retry"].lower() in ["true", "yes", "1"]

        return analysis
    except Exception as e:
        print(f"[DEBUG] Failed to parse quality analysis: {e}")
        print(f"[DEBUG] Raw result was: {result if 'result' in locals() else 'No result'}")

        # 파싱 실패 시 간단한 휴리스틱 판단
        # 분석 결과가 너무 짧으면 재시도
        if len(analysis_result.strip()) < 100:
            print(f"[DEBUG] Fallback: Analysis too short, enabling retry")
            return {"needs_retry": True, "reason": "분석 결과가 너무 짧음 (100자 미만)", "additional_info_needed": ["더 상세한 분석"]}

        return {"needs_retry": False, "reason": "Quality check failed - defaulting to no retry", "additional_info_needed": []}

def generate_feedback_suggestion(agent_name: str, analysis_result: str, proposal_text: str) -> str:
    """에이전트 분석 결과를 바탕으로 구체적인 피드백 제안 생성"""
    print(f"[DEBUG] Generating feedback suggestion for {agent_name}...")
    feedback_prompt = f"""당신은 AI 과제 제안서 검토 전문가입니다.
다음은 {agent_name}의 분석 결과입니다:

{analysis_result}

제안서 원문:
{proposal_text}

위 분석 결과를 바탕으로, 제안서 작성자에게 제공할 구체적이고 실행 가능한 피드백을 작성해주세요.
피드백은 다음 형식으로 작성해주세요:

1. 긍정적인 부분 (1-2가지)
2. 개선이 필요한 부분 (2-3가지, 구체적인 개선 방향 포함)
3. 추가 검토 사항 (1-2가지)

각 항목은 bullet point로 간결하게 작성해주세요."""

    result = call_ollama(feedback_prompt)
    print(f"[DEBUG] Feedback suggestion generated (length: {len(result)} chars)")
    return result

async def rag_retrieve_bp_cases(domain: str, division: str):
    """RAG를 통한 BP 사례 검색 (실패 시 fallback)"""
    try:
        # 검색 쿼리 구성
        query_text = f"{domain} {division} AI 과제 사례 Best Practice"

        # RAG 검색 수행 (비동기 함수에서 동기 함수 호출)
        rag_results = await asyncio.to_thread(retrieve_from_rag, query_text, num_result_doc=5)

        if rag_results:
            # RAG 검색 결과를 BP 사례 형식으로 변환
            cases = []
            for hit in rag_results:
                source = hit.get('_source', {})
                case = {
                    "title": source.get('title', '제목 없음'),
                    "tech_type": source.get('tech_type', 'AI/ML'),
                    "business_domain": source.get('business_domain', domain),
                    "division": source.get('division', division),
                    "problem_as_was": source.get('problem', '문제 정의'),
                    "solution_to_be": source.get('solution', '해결 방안'),
                    "summary": source.get('summary', source.get('content', '')[:200]),
                    "tips": source.get('tips', '')
                }
                cases.append(case)

            print(f"RAG 검색 성공: {len(cases)}건 반환")
            return {"success": True, "cases": cases}
        else:
            # RAG 검색 실패 시 시뮬레이션 데이터 반환
            print("RAG 검색 결과 없음, 시뮬레이션 데이터 반환")
            return {
                "success": False,
                "cases": [
                    {"title": "AI 인프라 모니터링", "tech_type": "AI/ML", "business_domain": domain, "division": division, "problem_as_was": "수동 모니터링으로 인한 장애 대응 지연", "solution_to_be": "AI 기반 실시간 이상 탐지 및 자동 알림", "summary": "AI를 활용한 인프라 모니터링 자동화", "tips": "실시간 데이터 수집 파이프라인 구축 필요"},
                    {"title": "예측 유지보수 시스템", "tech_type": "예측 분석", "business_domain": domain, "division": division, "problem_as_was": "사후 대응으로 인한 생산 중단", "solution_to_be": "ML 기반 고장 예측 및 사전 유지보수", "summary": "설비 고장을 사전에 예측하여 생산성 향상", "tips": "과거 고장 데이터 축적이 중요"},
                    {"title": "이상 감지 자동화", "tech_type": "이상 탐지", "business_domain": domain, "division": division, "problem_as_was": "품질 불량 발생 후 사후 조치", "solution_to_be": "실시간 이상 탐지 및 자동 조치", "summary": "AI 기반 품질 이상 자동 감지 시스템", "tips": "정상 데이터 패턴 학습이 선행되어야 함"}
                ]
            }
    except Exception as e:
        print(f"RAG retrieve failed (exception): {e}")
        # 예외 발생 시 시뮬레이션 데이터 반환
        return {
            "success": False,
            "cases": [
                {"title": "AI 인프라 모니터링", "tech_type": "AI/ML", "business_domain": domain, "division": division, "problem_as_was": "수동 모니터링으로 인한 장애 대응 지연", "solution_to_be": "AI 기반 실시간 이상 탐지 및 자동 알림", "summary": "AI를 활용한 인프라 모니터링 자동화", "tips": "실시간 데이터 수집 파이프라인 구축 필요"},
                {"title": "예측 유지보수 시스템", "tech_type": "예측 분석", "business_domain": domain, "division": division, "problem_as_was": "사후 대응으로 인한 생산 중단", "solution_to_be": "ML 기반 고장 예측 및 사전 유지보수", "summary": "설비 고장을 사전에 예측하여 생산성 향상", "tips": "과거 고장 데이터 축적이 중요"},
                {"title": "이상 감지 자동화", "tech_type": "이상 탐지", "business_domain": domain, "division": division, "problem_as_was": "품질 불량 발생 후 사후 조치", "solution_to_be": "실시간 이상 탐지 및 자동 조치", "summary": "AI 기반 품질 이상 자동 감지 시스템", "tips": "정상 데이터 패턴 학습이 선행되어야 함"}
            ]
        }

async def wait_for_feedback(job_id: int, timeout_seconds: int = 300):
    """HITL 피드백 대기 헬퍼 함수"""
    print(f"Job {job_id}: Waiting for user feedback...")
    update_job_status(job_id, "waiting_feedback")

    for i in range(timeout_seconds):
        job = get_job(job_id)
        if job.get("status") == "feedback_received":
            print(f"Job {job_id}: Feedback received, continuing...")
            return True
        await asyncio.sleep(1)

    print(f"Job {job_id}: Timeout waiting for feedback, continuing anyway...")
    return False

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
            all_reports.append({
                "page_title": page_info['title'],
                "page_id": page_info['id'],
                "job_id": job_id,
                "report": job_data['report'],
                "decision": job_data.get('llm_decision'),
                "decision_reason": (job_data.get('metadata') or {}).get('final_decision', {}).get('reason')
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

        print(f"\n✅ Completed page {idx+1}/{len(job_ids)}: {page_info['title']}\n")

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
        if ws:
            await ws.send_json({"status": "processing", "agent": "BP_Scouter", "message": "BP 사례 검색 중..."})

        # RAG 검색 시도 (실패해도 계속 진행)
        rag_result = await rag_retrieve_bp_cases(domain, division)
        bp_cases = rag_result.get("cases", [])

        await asyncio.sleep(2)
        if ws:
            # BP 검색 완료 메시지와 함께 결과 전송
            await ws.send_json({
                "status": "completed",
                "agent": "BP_Scouter",
                "message": f"BP 사례 {len(bp_cases)}건 검색 완료",
                "bp_cases": bp_cases  # BP 검색 결과 추가
            })

        persist_job_metadata(
            job_id,
            "bp_scouter_done",
            agent_updates={"bp_scouter": bp_cases},
            extra_updates={"bp_cases": bp_cases},
        )

        # Agent 2: Objective Reviewer
        if ws:
            await ws.send_json({"status": "processing", "agent": "Objective_Reviewer", "message": "목표 적합성 검토 중..."})

        proposal_text = job.get("content", "")
        objective_prompt = f"""당신은 기업의 AI 과제 제안서를 검토하는 전문가입니다.
다음 제안서의 목표 적합성을 검토하고 평가해주세요:

제안서 내용:
{proposal_text}

다음 항목을 평가하고 짧게 요약해주세요:
1. 목표의 명확성
2. 조직 전략과의 정렬성
3. 실현 가능성

간결하게 2-3문장으로 평가 결과를 작성해주세요."""

        objective_review = await asyncio.to_thread(call_ollama, objective_prompt)

        if ws:
            await ws.send_json({"status": "completed", "agent": "Objective_Reviewer", "message": "목표 검토 완료"})

        persist_job_metadata(
            job_id,
            "objective_done",
            agent_updates={"objective_review": objective_review},
        )

        # HITL 인터럽트: Agent 2 이후 (설정에 따라)
        if 2 in hitl_stages:
            agent_num = 2
            skip_accepted_agent2 = False
            while True:
                # LLM이 분석 결과 품질 평가
                quality_check = await asyncio.to_thread(
                    analyze_result_quality,
                    "Objective Reviewer",
                    objective_review,
                    proposal_text
                )

                print(f"[DEBUG] Quality check for Agent 2: {quality_check}")

                # 피드백 제안 생성
                feedback_suggestion = await asyncio.to_thread(
                    generate_feedback_suggestion,
                    "Objective Reviewer",
                    objective_review,
                    proposal_text
                )

                if ws:
                    await ws.send_json({
                        "status": "interrupt",
                        "job_id": job_id,
                        "message": f"검토 결과를 확인해주세요 (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}) - 품질: {quality_check.get('reason', '')}",
                        "results": {
                            "objective_review": objective_review,
                            "feedback_suggestion": feedback_suggestion,
                            "quality_check": quality_check
                        }
                    })

                # 사용자가 결과를 확인할 때까지 대기
                await wait_for_feedback(job_id)

                # 사용자 피드백 가져오기
                updated_job = get_job(job_id)
                skip_requested = updated_job.get("feedback_skip", False)
                user_feedback = (updated_job.get("feedback") or "").strip()

                print(f"[DEBUG] User feedback retrieved: '{user_feedback}' (skip={skip_requested})")

                if skip_requested:
                    skip_accepted_agent2 = True
                    retry_decision = {"needs_retry": False, "reason": "사용자가 건너뛰기를 선택"}
                    reset_feedback_state(job_id)
                    print(f"[DEBUG] HITL skip acknowledged for Agent 2 (job {job_id})")
                elif user_feedback:
                    retry_decision = {"needs_retry": False, "reason": "사용자 피드백 반영"}
                    reset_feedback_state(job_id)
                else:
                    # 피드백이 없으면 품질 검사 결과 사용
                    retry_decision = quality_check

                print(f"[DEBUG] Retry decision for Agent 2: {retry_decision}")

                if skip_accepted_agent2:
                    break

                # 재시도 필요 여부 판단
                if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                    hitl_retry_counts[agent_num] += 1
                    print(f"[DEBUG] Agent 2 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                    if ws:
                        await ws.send_json({
                            "status": "processing",
                            "agent": "Objective_Reviewer",
                            "message": f"품질 개선을 위해 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                        })

                    # 품질 검사 결과를 반영하여 재검토
                    retry_prompt = f"""당신은 기업의 AI 과제 제안서를 검토하는 전문가입니다.
이전 검토 결과가 품질 기준을 충족하지 못했습니다. 더 상세하고 구체적으로 재검토해주세요.

제안서 내용:
{proposal_text}

이전 검토 결과 (불충분):
{objective_review}

품질 검사 결과:
- 문제점: {retry_decision.get('reason', '분석이 불충분함')}
- 보완 필요 사항: {', '.join(retry_decision.get('additional_info_needed', ['더 상세한 분석', '구체적인 근거', '명확한 판단']))}

위 문제점을 해결하고 다음 항목을 **구체적이고 상세하게** 재평가해주세요:
1. 목표의 명확성 (제안서에 명시된 구체적인 목표 인용)
2. 조직 전략과의 정렬성 (어떤 전략 목표와 어떻게 연결되는지)
3. 실현 가능성 (구체적인 가능/불가능 근거)

**반드시 5-7문장 이상으로 구체적인 근거와 함께 평가 결과를 작성해주세요.**
각 항목마다 명확한 판단과 그 이유를 제시하세요."""

                    objective_review = await asyncio.to_thread(call_ollama, retry_prompt)

                    if ws:
                        await ws.send_json({
                            "status": "completed",
                            "agent": "Objective_Reviewer",
                            "message": "재검토 완료"
                        })

                    # 재검토 결과로 다시 HITL
                    continue
                else:
                    # 재시도 불필요하거나 최대 횟수 도달
                    if hitl_retry_counts[agent_num] >= MAX_HITL_RETRIES:
                        print(f"[DEBUG] Agent 2 최대 재시도 횟수 도달")
                        if ws:
                            await ws.send_json({
                                "status": "processing",
                                "agent": "Objective_Reviewer",
                                "message": "최대 재시도 횟수 도달, 다음 단계로 진행합니다"
                            })
                    break

            # 피드백 받은 후 계속 진행
            if ws:
                next_message = (
                    "사용자 건너뛰기 요청을 수락했습니다. 다음 단계로 진행합니다."
                    if skip_accepted_agent2
                    else "피드백 반영하여 분석 계속 진행..."
                )
                await ws.send_json({
                    "status": "processing",
                    "agent": "Data_Analyzer",
                    "message": next_message
                })
            await asyncio.sleep(1)

        # Agent 3: Data Analyzer
        if ws:
            await ws.send_json({"status": "processing", "agent": "Data_Analyzer", "message": "데이터 분석 중..."})

        data_prompt = f"""당신은 AI 프로젝트의 데이터 분석 전문가입니다.
다음 제안서에 대한 데이터 분석을 수행해주세요:

제안서 내용:
{proposal_text}

다음 항목을 평가하고 짧게 요약해주세요:
1. 데이터 확보 가능성
2. 데이터 품질 예상
3. 데이터 접근성

간결하게 2-3문장으로 평가 결과를 작성해주세요."""

        data_analysis = await asyncio.to_thread(call_ollama, data_prompt)

        if ws:
            await ws.send_json({"status": "completed", "agent": "Data_Analyzer", "message": "데이터 분석 완료"})

        persist_job_metadata(
            job_id,
            "data_analyzer_done",
            agent_updates={"data_analysis": data_analysis},
        )

        # HITL 인터럽트: Agent 3 이후 (설정에 따라)
        if 3 in hitl_stages:
            agent_num = 3
            skip_accepted_agent3 = False
            while True:
                # LLM이 분석 결과 품질 평가
                quality_check = await asyncio.to_thread(
                    analyze_result_quality,
                    "Data Analyzer",
                    data_analysis,
                    proposal_text
                )

                print(f"[DEBUG] Quality check for Agent 3: {quality_check}")

                feedback_suggestion = await asyncio.to_thread(
                    generate_feedback_suggestion,
                    "Data Analyzer",
                    data_analysis,
                    proposal_text
                )

                if ws:
                    await ws.send_json({
                        "status": "interrupt",
                        "job_id": job_id,
                        "message": f"데이터 분석 결과 확인 중... (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}) - {quality_check.get('reason', '')}",
                        "results": {
                            "data_analysis": data_analysis,
                            "feedback_suggestion": feedback_suggestion,
                            "quality_check": quality_check
                        }
                    })

                # 사용자가 결과를 확인할 때까지 대기
                await wait_for_feedback(job_id)

                # 사용자 피드백 가져오기
                updated_job = get_job(job_id)
                skip_requested = updated_job.get("feedback_skip", False)
                user_feedback = (updated_job.get("feedback") or "").strip()

                print(f"[DEBUG] User feedback retrieved: '{user_feedback}' (skip={skip_requested})")

                if skip_requested:
                    skip_accepted_agent3 = True
                    retry_decision = {"needs_retry": False, "reason": "사용자가 건너뛰기를 선택"}
                    reset_feedback_state(job_id)
                    print(f"[DEBUG] HITL skip acknowledged for Agent 3 (job {job_id})")
                elif user_feedback:
                    retry_decision = {"needs_retry": False, "reason": "사용자 피드백 반영"}
                    reset_feedback_state(job_id)
                else:
                    # 피드백이 없으면 품질 검사 결과 사용
                    retry_decision = quality_check

                print(f"[DEBUG] Retry decision for Agent 3: {retry_decision}")

                if skip_accepted_agent3:
                    break

                if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                    hitl_retry_counts[agent_num] += 1
                    print(f"[DEBUG] Agent 3 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                    if ws:
                        await ws.send_json({
                            "status": "processing",
                            "agent": "Data_Analyzer",
                            "message": f"품질 개선을 위해 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                        })

                    retry_prompt = f"""당신은 AI 프로젝트의 데이터 분석 전문가입니다.
이전 분석 결과가 품질 기준을 충족하지 못했습니다. 더 상세하고 구체적으로 재분석해주세요.

제안서 내용:
{proposal_text}

이전 분석 결과 (불충분):
{data_analysis}

품질 검사 결과:
- 문제점: {retry_decision.get('reason', '분석이 불충분함')}
- 보완 필요 사항: {', '.join(retry_decision.get('additional_info_needed', ['더 상세한 분석', '구체적인 근거']))}

위 문제점을 해결하고 다음 항목을 **구체적이고 상세하게** 재평가해주세요:
1. 데이터 확보 가능성 (어떤 데이터가 필요하고, 어디서 확보 가능한지)
2. 데이터 품질 예상 (품질 수준과 그 근거)
3. 데이터 접근성 (접근 방법과 제약사항)

**반드시 5-7문장 이상으로 구체적인 근거와 함께 평가 결과를 작성해주세요.**"""

                    data_analysis = await asyncio.to_thread(call_ollama, retry_prompt)

                    if ws:
                        await ws.send_json({
                            "status": "completed",
                            "agent": "Data_Analyzer",
                            "message": "재분석 완료"
                        })

                    continue
                else:
                    if hitl_retry_counts[agent_num] >= MAX_HITL_RETRIES:
                        print(f"[DEBUG] Agent 3 최대 재시도 횟수 도달")
                        if ws:
                            await ws.send_json({
                                "status": "processing",
                                "agent": "Data_Analyzer",
                                "message": "최대 재시도 횟수 도달, 다음 단계로 진행합니다"
                            })
                    break

            if ws:
                next_message = (
                    "사용자 건너뛰기 요청을 수락했습니다. 다음 단계로 진행합니다."
                    if skip_accepted_agent3
                    else "피드백 반영하여 분석 계속 진행..."
                )
                await ws.send_json({
                    "status": "processing",
                    "agent": "Risk_Analyzer",
                    "message": next_message
                })
            await asyncio.sleep(1)

        # Agent 4: Risk Analyzer
        if ws:
            await ws.send_json({"status": "processing", "agent": "Risk_Analyzer", "message": "리스크 분석 중..."})

        risk_prompt = f"""당신은 AI 프로젝트의 리스크 분석 전문가입니다.
다음 제안서에 대한 리스크 분석을 수행해주세요:

제안서 내용:
{proposal_text}

다음 리스크를 평가하고 각각 짧게 요약해주세요:
1. 기술적 리스크
2. 일정 리스크
3. 인력 리스크

각 항목마다 1-2문장으로 평가 결과를 작성해주세요."""

        risk_analysis = await asyncio.to_thread(call_ollama, risk_prompt)

        if ws:
            await ws.send_json({"status": "completed", "agent": "Risk_Analyzer", "message": "리스크 분석 완료"})

        persist_job_metadata(
            job_id,
            "risk_done",
            agent_updates={"risk_analysis": risk_analysis},
        )

        # HITL 인터럽트: Agent 4 이후 (설정에 따라)
        if 4 in hitl_stages:
            agent_num = 4
            skip_accepted_agent4 = False
            while True:
                quality_check = await asyncio.to_thread(
                    analyze_result_quality,
                    "Risk Analyzer",
                    risk_analysis,
                    proposal_text
                )
                print(f"[DEBUG] Quality check for Agent 4: {quality_check}")

                feedback_suggestion = await asyncio.to_thread(
                    generate_feedback_suggestion,
                    "Risk Analyzer",
                    risk_analysis,
                    proposal_text
                )

                if ws:
                    await ws.send_json({
                        "status": "interrupt",
                        "job_id": job_id,
                        "message": f"리스크 분석 결과 확인 중... (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}) - {quality_check.get('reason', '')}",
                        "results": {
                            "risk_analysis": risk_analysis,
                            "feedback_suggestion": feedback_suggestion,
                            "quality_check": quality_check
                        }
                    })

                # 사용자가 결과를 확인할 때까지 대기
                await wait_for_feedback(job_id)

                updated_job = get_job(job_id)
                skip_requested = updated_job.get("feedback_skip", False)
                user_feedback = (updated_job.get("feedback") or "").strip()

                print(f"[DEBUG] User feedback retrieved (Agent 4): '{user_feedback}' (skip={skip_requested})")

                if skip_requested:
                    skip_accepted_agent4 = True
                    retry_decision = {"needs_retry": False, "reason": "사용자가 건너뛰기를 선택"}
                    reset_feedback_state(job_id)
                    print(f"[DEBUG] HITL skip acknowledged for Agent 4 (job {job_id})")
                elif user_feedback:
                    retry_decision = {"needs_retry": False, "reason": "사용자 피드백 반영"}
                    reset_feedback_state(job_id)
                else:
                    retry_decision = quality_check

                print(f"[DEBUG] Retry decision for Agent 4: {retry_decision}")

                if skip_accepted_agent4:
                    break

                if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                    hitl_retry_counts[agent_num] += 1
                    print(f"[DEBUG] Agent 4 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                    if ws:
                        await ws.send_json({
                            "status": "processing",
                            "agent": "Risk_Analyzer",
                            "message": f"품질 개선을 위해 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                        })

                    retry_prompt = f"""당신은 AI 프로젝트의 리스크 분석 전문가입니다.
이전 분석 결과가 품질 기준을 충족하지 못했습니다. 더 상세하고 구체적으로 재분석해주세요.

제안서 내용:
{proposal_text}

이전 분석 결과 (불충분):
{risk_analysis}

품질 검사 결과:
- 문제점: {retry_decision.get('reason', '분석이 불충분함')}
- 보완 필요 사항: {', '.join(retry_decision.get('additional_info_needed', ['더 상세한 분석']))}

위 문제점을 해결하고 다음 리스크를 **구체적이고 상세하게** 재평가해주세요:
1. 기술적 리스크 (구체적인 기술 문제점과 영향)
2. 일정 리스크 (지연 가능성과 원인)
3. 인력 리스크 (필요 역량과 확보 가능성)

**반드시 5-7문장 이상으로 각 리스크마다 명확한 평가와 근거를 제시하세요.**"""

                    risk_analysis = await asyncio.to_thread(call_ollama, retry_prompt)

                    if ws:
                        await ws.send_json({
                            "status": "completed",
                            "agent": "Risk_Analyzer",
                            "message": "재분석 완료"
                        })

                    continue
                else:
                    if hitl_retry_counts[agent_num] >= MAX_HITL_RETRIES:
                        print(f"[DEBUG] Agent 4 최대 재시도 횟수 도달")
                        if ws:
                            await ws.send_json({
                                "status": "processing",
                                "agent": "Risk_Analyzer",
                                "message": "최대 재시도 횟수 도달, 다음 단계로 진행합니다"
                            })
                    break

            if ws:
                next_message = (
                    "사용자 건너뛰기 요청을 수락했습니다. 다음 단계로 진행합니다."
                    if skip_accepted_agent4
                    else "피드백 반영하여 분석 계속 진행..."
                )
                await ws.send_json({
                    "status": "processing",
                    "agent": "ROI_Estimator",
                    "message": next_message
                })
            await asyncio.sleep(1)

        # Agent 5: ROI Estimator
        if ws:
            await ws.send_json({"status": "processing", "agent": "ROI_Estimator", "message": "ROI 추정 중..."})

        roi_prompt = f"""당신은 AI 프로젝트의 ROI(투자 수익률) 분석 전문가입니다.
다음 제안서에 대한 ROI를 추정해주세요:

제안서 내용:
{proposal_text}

다음 항목을 평가하고 짧게 요약해주세요:
1. 예상 효과 (비용 절감, 생산성 향상 등)
2. 투자 대비 효과 (ROI 퍼센티지, 손익분기점)

간결하게 2-3문장으로 평가 결과를 작성해주세요."""

        roi_estimation = await asyncio.to_thread(call_ollama, roi_prompt)

        if ws:
            await ws.send_json({"status": "completed", "agent": "ROI_Estimator", "message": "ROI 추정 완료"})

        persist_job_metadata(
            job_id,
            "roi_done",
            agent_updates={"roi_estimation": roi_estimation},
        )

        # HITL 인터럽트: Agent 5 이후 (설정에 따라)
        if 5 in hitl_stages:
            agent_num = 5
            skip_accepted_agent5 = False
            while True:
                quality_check = await asyncio.to_thread(
                    analyze_result_quality,
                    "ROI Estimator",
                    roi_estimation,
                    proposal_text
                )
                print(f"[DEBUG] Quality check for Agent 5: {quality_check}")

                feedback_suggestion = await asyncio.to_thread(
                    generate_feedback_suggestion,
                    "ROI Estimator",
                    roi_estimation,
                    proposal_text
                )

                if ws:
                    await ws.send_json({
                        "status": "interrupt",
                        "job_id": job_id,
                        "message": f"ROI 추정 결과 확인 중... (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}) - {quality_check.get('reason', '')}",
                        "results": {
                            "roi_estimation": roi_estimation,
                            "feedback_suggestion": feedback_suggestion,
                            "quality_check": quality_check
                        }
                    })

                # 사용자가 결과를 확인할 때까지 대기
                await wait_for_feedback(job_id)

                updated_job = get_job(job_id)
                skip_requested = updated_job.get("feedback_skip", False)
                user_feedback = (updated_job.get("feedback") or "").strip()

                print(f"[DEBUG] User feedback retrieved (Agent 5): '{user_feedback}' (skip={skip_requested})")

                if skip_requested:
                    skip_accepted_agent5 = True
                    retry_decision = {"needs_retry": False, "reason": "사용자가 건너뛰기를 선택"}
                    reset_feedback_state(job_id)
                    print(f"[DEBUG] HITL skip acknowledged for Agent 5 (job {job_id})")
                elif user_feedback:
                    retry_decision = {"needs_retry": False, "reason": "사용자 피드백 반영"}
                    reset_feedback_state(job_id)
                else:
                    retry_decision = quality_check

                print(f"[DEBUG] Retry decision for Agent 5: {retry_decision}")

                if skip_accepted_agent5:
                    break

                if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                    hitl_retry_counts[agent_num] += 1
                    print(f"[DEBUG] Agent 5 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                    if ws:
                        await ws.send_json({
                            "status": "processing",
                            "agent": "ROI_Estimator",
                            "message": f"품질 개선을 위해 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                        })

                    retry_prompt = f"""당신은 AI 프로젝트의 ROI(투자 수익률) 분석 전문가입니다.
이전 분석 결과가 품질 기준을 충족하지 못했습니다. 더 상세하고 구체적으로 ROI를 재추정해주세요.

제안서 내용:
{proposal_text}

이전 분석 결과 (불충분):
{roi_estimation}

품질 검사 결과:
- 문제점: {retry_decision.get('reason', '분석이 불충분함')}
- 보완 필요 사항: {', '.join(retry_decision.get('additional_info_needed', ['더 상세한 분석']))}

위 문제점을 해결하고 다음 항목을 **구체적이고 상세하게** 재평가해주세요:
1. 예상 효과 (구체적인 수치와 근거)
2. 투자 대비 효과 (명확한 ROI 계산 근거)

**반드시 5-7문장 이상으로 수치와 계산 근거를 포함하여 작성해주세요.**"""

                    roi_estimation = await asyncio.to_thread(call_ollama, retry_prompt)

                    if ws:
                        await ws.send_json({
                            "status": "completed",
                            "agent": "ROI_Estimator",
                            "message": "재추정 완료"
                        })

                    continue
                else:
                    if hitl_retry_counts[agent_num] >= MAX_HITL_RETRIES:
                        print(f"[DEBUG] Agent 5 최대 재시도 횟수 도달")
                        if ws:
                            await ws.send_json({
                                "status": "processing",
                                "agent": "ROI_Estimator",
                                "message": "최대 재시도 횟수 도달, 다음 단계로 진행합니다"
                            })
                    break

            if ws:
                next_message = (
                    "사용자 건너뛰기 요청을 수락했습니다. 다음 단계로 진행합니다."
                    if skip_accepted_agent5
                    else "피드백 반영하여 최종 보고서 생성 중..."
                )
                await ws.send_json({
                    "status": "processing",
                    "agent": "Final_Generator",
                    "message": next_message
                })
            await asyncio.sleep(1)

        # Agent 6: Final Generator
        if ws:
            await ws.send_json({"status": "processing", "agent": "Final_Generator", "message": "최종 보고서 생성 중..."})

        final_prompt = f"""당신은 AI 프로젝트 검토 전문가입니다.
다음 제안서와 분석 결과를 바탕으로 최종 의견을 작성해주세요:

제안서 내용:
{proposal_text}

목표 검토:
{objective_review}

데이터 분석:
{data_analysis}

리스크 분석:
{risk_analysis}

ROI 추정:
{roi_estimation}

다음을 포함한 최종 의견을 작성해주세요:
1. 승인 또는 보류 권장 (명확하게)
2. 주요 근거 (3-4가지)
3. 권장사항 (2-3가지)

간결하게 5-7문장으로 작성해주세요."""

        final_recommendation = await asyncio.to_thread(call_ollama, final_prompt)

        if ws:
            await ws.send_json({"status": "completed", "agent": "Final_Generator", "message": "최종 의견 생성 완료"})
        update_job_status(job_id, "final_done")

        # HITL 인터럽트: Agent 6 이후 (설정에 따라)
        if 6 in hitl_stages:
            agent_num = 6
            skip_accepted_agent6 = False
            while True:
                quality_check = await asyncio.to_thread(
                    analyze_result_quality,
                    "Final Generator",
                    final_recommendation,
                    proposal_text
                )
                print(f"[DEBUG] Quality check for Agent 6: {quality_check}")

                feedback_suggestion = await asyncio.to_thread(
                    generate_feedback_suggestion,
                    "Final Generator",
                    final_recommendation,
                    proposal_text
                )

                if ws:
                    await ws.send_json({
                        "status": "interrupt",
                        "job_id": job_id,
                        "message": f"최종 의견 확인 중... (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}) - {quality_check.get('reason', '')}",
                        "results": {
                            "final_recommendation": final_recommendation,
                            "feedback_suggestion": feedback_suggestion,
                            "quality_check": quality_check
                        }
                    })

                # 사용자가 결과를 확인할 때까지 대기
                await wait_for_feedback(job_id)

                updated_job = get_job(job_id)
                skip_requested = updated_job.get("feedback_skip", False)
                user_feedback = (updated_job.get("feedback") or "").strip()

                print(f"[DEBUG] User feedback retrieved (Agent 6): '{user_feedback}' (skip={skip_requested})")

                if skip_requested:
                    skip_accepted_agent6 = True
                    retry_decision = {"needs_retry": False, "reason": "사용자가 건너뛰기를 선택"}
                    reset_feedback_state(job_id)
                    print(f"[DEBUG] HITL skip acknowledged for Agent 6 (job {job_id})")
                elif user_feedback:
                    retry_decision = {"needs_retry": False, "reason": "사용자 피드백 반영"}
                    reset_feedback_state(job_id)
                else:
                    retry_decision = quality_check

                print(f"[DEBUG] Retry decision for Agent 6: {retry_decision}")

                if skip_accepted_agent6:
                    break

                if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                    hitl_retry_counts[agent_num] += 1
                    print(f"[DEBUG] Agent 6 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                    if ws:
                        await ws.send_json({
                            "status": "processing",
                            "agent": "Final_Generator",
                            "message": f"품질 개선을 위해 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                        })

                    retry_prompt = f"""당신은 AI 프로젝트 검토 전문가입니다.
이전 최종 의견이 품질 기준을 충족하지 못했습니다. 더 상세하고 구체적으로 최종 의견을 재작성해주세요.

제안서 내용:
{proposal_text}

목표 검토:
{objective_review}

데이터 분석:
{data_analysis}

리스크 분석:
{risk_analysis}

ROI 추정:
{roi_estimation}

이전 최종 의견 (불충분):
{final_recommendation}

품질 검사 결과:
- 문제점: {retry_decision.get('reason', '의견이 불충분함')}
- 보완 필요 사항: {', '.join(retry_decision.get('additional_info_needed', ['더 명확한 판단', '구체적인 근거']))}

위 문제점을 해결하고 다음을 포함한 **구체적이고 명확한** 최종 의견을 작성해주세요:
1. 승인/보류 권장 (명확한 결정과 이유)
2. 주요 근거 (구체적인 데이터와 분석 결과 인용)
3. 실행 권장사항 (구체적이고 실현 가능한 제안)

**반드시 7-10문장 이상으로 명확한 판단과 상세한 근거를 포함하여 작성해주세요.**"""

                    final_recommendation = await asyncio.to_thread(call_ollama, retry_prompt)

                    if ws:
                        await ws.send_json({
                            "status": "completed",
                            "agent": "Final_Generator",
                            "message": "재검토 완료"
                        })

                    continue
                else:
                    if hitl_retry_counts[agent_num] >= MAX_HITL_RETRIES:
                        print(f"[DEBUG] Agent 6 최대 재시도 횟수 도달")
                        if ws:
                            await ws.send_json({
                                "status": "processing",
                                "agent": "Final_Generator",
                                "message": "최대 재시도 횟수 도달, 최종 보고서를 생성합니다"
                            })
                    break

            if ws:
                next_message = (
                    "사용자 건너뛰기 요청을 수락했습니다. 최종 보고서를 생성합니다."
                    if skip_accepted_agent6
                    else "피드백 반영하여 최종 보고서 생성 중..."
                )
                await ws.send_json({"status": "processing", "message": next_message})
            await asyncio.sleep(1)

        # 최종 완료
        final_report = f"""
        <div style="padding: 20px;">
            <h2>📊 AI 과제 지원서 검토 보고서</h2>
            <hr/>

            <div class="accordion-item">
                <div class="accordion-header" onclick="toggleAccordion('section1')">
                    <span>1. BP 사례 분석 ({len(bp_cases)}건)</span>
                    <span class="accordion-icon">▼</span>
                </div>
                <div id="section1" class="accordion-content" style="display: block;">
                    <p><strong>유사 사례:</strong></p>
                    <ul>
                        {''.join([f'<li>{c.get("title", "")} ({c.get("domain", "")}/{c.get("division", "")})</li>' for c in bp_cases]) if bp_cases else '<li>검색된 사례 없음</li>'}
                    </ul>
                    <p><em>총 {len(bp_cases)}건의 유사 사례가 발견되었습니다.</em></p>
                </div>
            </div>

            <div class="accordion-item">
                <div class="accordion-header" onclick="toggleAccordion('section2')">
                    <span>2. 목표 적합성</span>
                    <span class="accordion-icon">▼</span>
                </div>
                <div id="section2" class="accordion-content">
                    <p>{objective_review.replace(chr(10), '<br>')}</p>
                </div>
            </div>

            <div class="accordion-item">
                <div class="accordion-header" onclick="toggleAccordion('section3')">
                    <span>3. 데이터 분석</span>
                    <span class="accordion-icon">▼</span>
                </div>
                <div id="section3" class="accordion-content">
                    <p>{data_analysis.replace(chr(10), '<br>')}</p>
                </div>
            </div>

            <div class="accordion-item">
                <div class="accordion-header" onclick="toggleAccordion('section4')">
                    <span>4. 리스크 분석</span>
                    <span class="accordion-icon">▼</span>
                </div>
                <div id="section4" class="accordion-content">
                    <p>{risk_analysis.replace(chr(10), '<br>')}</p>
                </div>
            </div>

            <div class="accordion-item">
                <div class="accordion-header" onclick="toggleAccordion('section5')">
                    <span>5. ROI 추정</span>
                    <span class="accordion-icon">▼</span>
                </div>
                <div id="section5" class="accordion-content">
                    <p>{roi_estimation.replace(chr(10), '<br>')}</p>
                </div>
            </div>

            <div class="accordion-item">
                <div class="accordion-header" onclick="toggleAccordion('section6')">
                    <span>6. 최종 의견</span>
                    <span class="accordion-icon">▼</span>
                </div>
                <div id="section6" class="accordion-content" style="display: block;">
                    <p>{final_recommendation.replace(chr(10), '<br>')}</p>
                </div>
            </div>
        </div>
        """

        decision_result = await classify_final_decision(final_report, final_recommendation)
        decision_value = decision_result.get("decision", "보류")
        decision_reason = decision_result.get("reason", "LLM 판단을 기준으로 자동 분류되었습니다.")

        latest_job = get_job(job_id) or {}
        metadata = latest_job.get("metadata", {}).copy()
        metadata["report"] = final_report
        agent_results = metadata.setdefault("agent_results", {})
        agent_results["final_recommendation"] = final_recommendation
        metadata["final_decision"] = {
            "decision": decision_value,
            "reason": decision_reason,
        }

        update_job_status(
            job_id,
            "completed",
            metadata=metadata,
            llm_decision=decision_value,
        )

        if send_final_report:
            target_ws = ws or active_connections.get(ws_key)
            if target_ws:
                human_decision_value = latest_job.get("decision") or latest_job.get("human_decision")
                await target_ws.send_json({
                    "status": "completed",
                    "agent": "Final_Generator",
                    "message": "검토 완료",
                    "report": final_report,
                    "decision": decision_value,
                    "decision_reason": decision_reason,
                    "human_decision": human_decision_value,
                })

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

@app.post("/api/v1/review/feedback/{job_id}")
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
    update_job_feedback(job_id, feedback_text, skip=skip_requested)

    # DB 상태를 feedback_received로 업데이트
    update_job_status(job_id, "feedback_received")

    print(f"[DEBUG] Feedback saved and status updated for job {job_id}")

    return {"status": "feedback_received", "job_id": job_id, "skip": skip_requested}

@app.get("/api/v1/review/pdf/{job_id}")
async def download_pdf(job_id: int):
    """PDF 다운로드"""
    # MVP: 간단한 응답
    return {"message": "PDF 생성 기능은 추후 구현 예정", "job_id": job_id}

# ==================== Confluence API 엔드포인트 ====================

@app.post("/api/v1/confluence/fetch-pages")
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
                get_pages_recursively,
                page_id,
                include_current=include_current,
                max_depth=max_depth,
                current_depth=0
            )
        else:
            # 현재 페이지만 가져오기
            page = await asyncio.to_thread(get_page_content, page_id)
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

@app.post("/api/v1/confluence/submit-for-review")
async def submit_confluence_for_review(
    page_id: str = Form(...),
    include_children: bool = Form(True),
    include_current: bool = Form(True),
    max_depth: int = Form(2),
    domain: str = Form("제조"),
    division: str = Form("메모리"),
    hitl_stages: str = Form("[]")
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
                get_pages_recursively,
                page_id,
                include_current=include_current,
                max_depth=max_depth,
                current_depth=0
            )
        else:
            page = await asyncio.to_thread(get_page_content, page_id)
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

        # 각 페이지별로 job 생성 및 순차 처리
        job_ids = []
        page_list = [{"id": p.get("id"), "title": p.get("title") or ""} for p in pages]

        for idx, page in enumerate(pages):
            raw_title = page.get('title') or ''
            page_content = f"{'='*80}\n페이지: {raw_title}\nID: {page.get('id')}\n{'='*80}\n{page.get('content')}"
            job_title = raw_title.strip() or await generate_job_title(page_content, fallback=f"Confluence 페이지 {idx+1}")
            job_id = create_job(
                page_content,
                domain,
                division,
                title=job_title,
                hitl_stages=hitl_stages_list,
            )
            page_list[idx]["title"] = job_title
            job_ids.append(job_id)
            print(f"Created job {job_id} for page {idx+1}/{len(pages)}: {job_title}")

        # 첫 번째 페이지부터 순차적으로 처리 시작
        print(f"Starting sequential processing for {len(job_ids)} pages")
        asyncio.create_task(process_confluence_pages_sequentially(job_ids, page_list))

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

@app.get("/api/v1/confluence/child-pages/{page_id}")
async def get_confluence_child_pages(page_id: str):
    """특정 페이지의 하위 페이지 목록 조회"""
    try:
        children = await asyncio.to_thread(get_child_pages, page_id)

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


# ==================== Dashboard & CRUD API ====================


@app.get("/dashboard")
async def dashboard_page():
    """대시보드 HTML 제공"""
    return FileResponse("static/dashboard.html")


def _sanitize_decision(decision: str | None) -> str | None:
    if not decision:
        return decision
    normalized = decision.strip()
    return normalized


def _coerce_hitl_stages(values: Optional[List[int] | List[str]]) -> Optional[List[int]]:
    if values is None:
        return None
    coerced = []
    for item in values:
        try:
            coerced.append(int(item))
        except (TypeError, ValueError):
            continue
    return coerced


@app.get("/api/v1/dashboard/jobs")
async def dashboard_list(
    status: Optional[str] = None,
    decision: Optional[str] = None,
    llm_decision: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    order: str = "desc",
):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    jobs = list_jobs(
        limit=limit,
        offset=offset,
        status=status,
        decision=decision,
        llm_decision=llm_decision,
        search=search,
        order=order,
    )

    total = count_jobs(status=status, decision=decision, llm_decision=llm_decision, search=search)

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


@app.get("/api/v1/dashboard/jobs/{job_id}")
async def dashboard_get_job_detail(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="존재하지 않는 작업입니다.")
    return job


@app.post("/api/v1/dashboard/jobs")
async def dashboard_create_job(payload: JobCreateRequest):
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
        title_value = await generate_job_title(payload.proposal_content, fallback=f"{payload.domain} 제안서")

    job_id = create_job(
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

    created_job = get_job(job_id)
    return created_job


@app.put("/api/v1/dashboard/jobs/{job_id}")
async def dashboard_update_job(job_id: int, payload: JobUpdateRequest):
    existing = get_job(job_id)
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

    success = update_job_record(
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

    return get_job(job_id)


@app.delete("/api/v1/dashboard/jobs/{job_id}")
async def dashboard_delete_job(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="존재하지 않는 작업입니다.")

    delete_job(job_id)
    return {"status": "deleted", "job_id": job_id}


if __name__ == "__main__":
    print(f"Server starting at http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)

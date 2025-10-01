# main.py - FastAPI 통합 서버 구현
from fastapi import FastAPI, UploadFile, File, WebSocket, Form, WebSocketDisconnect, BackgroundTasks
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
import requests
from dotenv import load_dotenv

from database.db import init_database, create_job, get_job, update_job_status
from config.settings import HOST, PORT

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
        hitl_stages_list = [2]  # 기본값: Agent 2에서 HITL

    # DB에 저장하고 job_id 생성
    job_id = create_job(proposal_content, domain, division, hitl_stages=hitl_stages_list)

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

def analyze_feedback_for_retry(feedback: str, agent_name: str) -> dict:
    """피드백을 분석하여 재검토 필요 여부 판단

    Returns:
        {
            "needs_retry": bool,  # 재검토 필요 여부
            "reason": str,  # 재검토가 필요한 이유
            "additional_info_needed": list  # 필요한 추가 정보 항목들
        }
    """
    print(f"[DEBUG] Analyzing feedback for {agent_name}...")

    # 피드백이 비어있으면 재검토 불필요
    if not feedback or feedback.strip() == "":
        return {"needs_retry": False, "reason": "No feedback provided", "additional_info_needed": []}

    analysis_prompt = f"""당신은 AI 검토 프로세스의 orchestrator입니다.
다음은 {agent_name}의 검토 결과에 대한 사용자 피드백입니다:

피드백:
{feedback}

위 피드백을 분석하여 다음을 판단해주세요:

1. 추가 정보가 필요한가? (예: 구체적인 데이터 요청, 추가 분석 요청, 명확화 요청 등)
2. 단순히 확인/승인하는 내용인가?
3. 수정 제안만 포함하고 있는가?

다음 형식의 JSON으로만 응답해주세요 (다른 설명 없이):
{{
    "needs_retry": true/false,
    "reason": "재검토가 필요한 구체적인 이유 또는 '재검토 불필요'",
    "additional_info_needed": ["항목1", "항목2", ...]
}}

판단 기준:
- needs_retry = true: 피드백에 "추가로", "더 자세히", "구체적으로", "명확히" 등의 요청이 있거나, 새로운 분석/데이터를 요구하는 경우
- needs_retry = false: 단순 확인, 승인, 일반적인 수정 제안만 있는 경우"""

    try:
        result = call_ollama(analysis_prompt)
        print(f"[DEBUG] Feedback analysis result: {result[:200]}...")

        # JSON 파싱
        import json
        # JSON 부분만 추출 (```json ``` 제거)
        json_str = result.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        analysis = json.loads(json_str)
        return analysis
    except Exception as e:
        print(f"[DEBUG] Failed to parse feedback analysis: {e}, treating as no retry needed")
        return {"needs_retry": False, "reason": "Analysis failed", "additional_info_needed": []}

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

async def process_review(job_id: int):
    """백그라운드 검토 프로세스 - 6개 에이전트 전체 플로우"""
    print(f"=== process_review ENTRY for job {job_id} ===")
    ws = None
    try:
        print(f"process_review started for job {job_id}")
        job = get_job(job_id)
        print(f"Job data retrieved for job {job_id}")
        if not job:
            print(f"Job {job_id} not found")
            return

        # HITL 단계 설정 가져오기
        hitl_stages = job.get("hitl_stages", [2])
        print(f"HITL stages enabled: {hitl_stages}")

        # HITL 재시도 카운터 초기화 (각 에이전트당 최대 3회)
        hitl_retry_counts = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
        MAX_HITL_RETRIES = 3

        # Wait for WebSocket connection (up to 3 seconds)
        for i in range(30):
            ws = active_connections.get(str(job_id))
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
        update_job_status(job_id, "bp_scouter_done")

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
        update_job_status(job_id, "objective_done")

        # HITL 인터럽트: Agent 2 이후 (설정에 따라)
        if 2 in hitl_stages:
            agent_num = 2
            while True:
                # 피드백 제안 생성
                feedback_suggestion = await asyncio.to_thread(
                    generate_feedback_suggestion,
                    "Objective Reviewer",
                    objective_review,
                    proposal_text
                )
                print(f"[DEBUG] Sending HITL interrupt with feedback_suggestion: {len(feedback_suggestion)} chars")

                if ws:
                    await ws.send_json({
                        "status": "interrupt",
                        "message": f"검토 결과를 확인하고 피드백을 제공해주세요 (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})",
                        "results": {
                            "objective_review": objective_review,
                            "feedback_suggestion": feedback_suggestion
                        }
                    })
                    print(f"[DEBUG] HITL interrupt sent via WebSocket")

                # 피드백 대기
                await wait_for_feedback(job_id)

                # 피드백 분석
                job = get_job(job_id)
                user_feedback = job.get("feedback", "")

                retry_decision = await asyncio.to_thread(
                    analyze_feedback_for_retry,
                    user_feedback,
                    "Objective Reviewer"
                )

                print(f"[DEBUG] Retry decision for Agent 2: {retry_decision}")

                # 재시도 필요 여부 판단
                if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                    hitl_retry_counts[agent_num] += 1
                    print(f"[DEBUG] Agent 2 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                    if ws:
                        await ws.send_json({
                            "status": "processing",
                            "agent": "Objective_Reviewer",
                            "message": f"추가 정보 반영하여 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                        })

                    # 피드백을 반영하여 재검토
                    retry_prompt = f"""당신은 기업의 AI 과제 제안서를 검토하는 전문가입니다.
이전 검토에 대한 사용자 피드백을 반영하여 재검토해주세요.

제안서 내용:
{proposal_text}

이전 검토 결과:
{objective_review}

사용자 피드백:
{user_feedback}

필요한 추가 정보: {', '.join(retry_decision.get('additional_info_needed', []))}

피드백을 반영하여 다음 항목을 재평가하고 짧게 요약해주세요:
1. 목표의 명확성
2. 조직 전략과의 정렬성
3. 실현 가능성

간결하게 2-3문장으로 평가 결과를 작성해주세요."""

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
                await ws.send_json({"status": "processing", "agent": "Data_Analyzer", "message": "피드백 반영하여 분석 계속 진행..."})
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
        update_job_status(job_id, "data_analyzer_done")

        # HITL 인터럽트: Agent 3 이후 (설정에 따라)
        if 3 in hitl_stages:
            agent_num = 3
            while True:
                feedback_suggestion = await asyncio.to_thread(
                    generate_feedback_suggestion,
                    "Data Analyzer",
                    data_analysis,
                    proposal_text
                )

                if ws:
                    await ws.send_json({
                        "status": "interrupt",
                        "message": f"데이터 분석 결과를 확인하고 피드백을 제공해주세요 (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})",
                        "results": {
                            "data_analysis": data_analysis,
                            "feedback_suggestion": feedback_suggestion
                        }
                    })

                await wait_for_feedback(job_id)

                job = get_job(job_id)
                user_feedback = job.get("feedback", "")

                retry_decision = await asyncio.to_thread(
                    analyze_feedback_for_retry,
                    user_feedback,
                    "Data Analyzer"
                )

                print(f"[DEBUG] Retry decision for Agent 3: {retry_decision}")

                if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                    hitl_retry_counts[agent_num] += 1
                    print(f"[DEBUG] Agent 3 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                    if ws:
                        await ws.send_json({
                            "status": "processing",
                            "agent": "Data_Analyzer",
                            "message": f"추가 정보 반영하여 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                        })

                    retry_prompt = f"""당신은 AI 프로젝트의 데이터 분석 전문가입니다.
이전 분석에 대한 사용자 피드백을 반영하여 재분석해주세요.

제안서 내용:
{proposal_text}

이전 분석 결과:
{data_analysis}

사용자 피드백:
{user_feedback}

필요한 추가 정보: {', '.join(retry_decision.get('additional_info_needed', []))}

피드백을 반영하여 다음 항목을 재평가하고 짧게 요약해주세요:
1. 데이터 확보 가능성
2. 데이터 품질 예상
3. 데이터 접근성

간결하게 2-3문장으로 평가 결과를 작성해주세요."""

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
                await ws.send_json({"status": "processing", "agent": "Risk_Analyzer", "message": "피드백 반영하여 분석 계속 진행..."})
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
        update_job_status(job_id, "risk_done")

        # HITL 인터럽트: Agent 4 이후 (설정에 따라)
        if 4 in hitl_stages:
            agent_num = 4
            while True:
                feedback_suggestion = await asyncio.to_thread(
                    generate_feedback_suggestion,
                    "Risk Analyzer",
                    risk_analysis,
                    proposal_text
                )

                if ws:
                    await ws.send_json({
                        "status": "interrupt",
                        "message": f"리스크 분석 결과를 확인하고 피드백을 제공해주세요 (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})",
                        "results": {
                            "risk_analysis": risk_analysis,
                            "feedback_suggestion": feedback_suggestion
                        }
                    })

                await wait_for_feedback(job_id)

                job = get_job(job_id)
                user_feedback = job.get("feedback", "")

                retry_decision = await asyncio.to_thread(
                    analyze_feedback_for_retry,
                    user_feedback,
                    "Risk Analyzer"
                )

                print(f"[DEBUG] Retry decision for Agent 4: {retry_decision}")

                if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                    hitl_retry_counts[agent_num] += 1
                    print(f"[DEBUG] Agent 4 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                    if ws:
                        await ws.send_json({
                            "status": "processing",
                            "agent": "Risk_Analyzer",
                            "message": f"추가 정보 반영하여 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                        })

                    retry_prompt = f"""당신은 AI 프로젝트의 리스크 분석 전문가입니다.
이전 분석에 대한 사용자 피드백을 반영하여 재분석해주세요.

제안서 내용:
{proposal_text}

이전 분석 결과:
{risk_analysis}

사용자 피드백:
{user_feedback}

필요한 추가 정보: {', '.join(retry_decision.get('additional_info_needed', []))}

피드백을 반영하여 다음 리스크를 재평가하고 각각 짧게 요약해주세요:
1. 기술적 리스크
2. 일정 리스크
3. 인력 리스크

각 항목마다 1-2문장으로 평가 결과를 작성해주세요."""

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
                await ws.send_json({"status": "processing", "agent": "ROI_Estimator", "message": "피드백 반영하여 분석 계속 진행..."})
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
        update_job_status(job_id, "roi_done")

        # HITL 인터럽트: Agent 5 이후 (설정에 따라)
        if 5 in hitl_stages:
            agent_num = 5
            while True:
                feedback_suggestion = await asyncio.to_thread(
                    generate_feedback_suggestion,
                    "ROI Estimator",
                    roi_estimation,
                    proposal_text
                )

                if ws:
                    await ws.send_json({
                        "status": "interrupt",
                        "message": f"ROI 추정 결과를 확인하고 피드백을 제공해주세요 (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})",
                        "results": {
                            "roi_estimation": roi_estimation,
                            "feedback_suggestion": feedback_suggestion
                        }
                    })

                await wait_for_feedback(job_id)

                job = get_job(job_id)
                user_feedback = job.get("feedback", "")

                retry_decision = await asyncio.to_thread(
                    analyze_feedback_for_retry,
                    user_feedback,
                    "ROI Estimator"
                )

                print(f"[DEBUG] Retry decision for Agent 5: {retry_decision}")

                if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                    hitl_retry_counts[agent_num] += 1
                    print(f"[DEBUG] Agent 5 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                    if ws:
                        await ws.send_json({
                            "status": "processing",
                            "agent": "ROI_Estimator",
                            "message": f"추가 정보 반영하여 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                        })

                    retry_prompt = f"""당신은 AI 프로젝트의 ROI(투자 수익률) 분석 전문가입니다.
이전 분석에 대한 사용자 피드백을 반영하여 ROI를 재추정해주세요.

제안서 내용:
{proposal_text}

이전 분석 결과:
{roi_estimation}

사용자 피드백:
{user_feedback}

필요한 추가 정보: {', '.join(retry_decision.get('additional_info_needed', []))}

피드백을 반영하여 다음 항목을 재평가하고 짧게 요약해주세요:
1. 예상 효과 (비용 절감, 생산성 향상 등)
2. 투자 대비 효과 (ROI 퍼센티지, 손익분기점)

간결하게 2-3문장으로 평가 결과를 작성해주세요."""

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
                await ws.send_json({"status": "processing", "agent": "Final_Generator", "message": "피드백 반영하여 최종 보고서 생성 중..."})
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
            while True:
                feedback_suggestion = await asyncio.to_thread(
                    generate_feedback_suggestion,
                    "Final Generator",
                    final_recommendation,
                    proposal_text
                )
                print(f"[DEBUG] Sending HITL interrupt with feedback_suggestion: {len(feedback_suggestion)} chars")

                if ws:
                    await ws.send_json({
                        "status": "interrupt",
                        "message": f"최종 의견을 확인하고 피드백을 제공해주세요 (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})",
                        "results": {
                            "final_recommendation": final_recommendation,
                            "feedback_suggestion": feedback_suggestion
                        }
                    })
                    print(f"[DEBUG] HITL interrupt sent via WebSocket")

                await wait_for_feedback(job_id)

                job = get_job(job_id)
                user_feedback = job.get("feedback", "")

                retry_decision = await asyncio.to_thread(
                    analyze_feedback_for_retry,
                    user_feedback,
                    "Final Generator"
                )

                print(f"[DEBUG] Retry decision for Agent 6: {retry_decision}")

                if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                    hitl_retry_counts[agent_num] += 1
                    print(f"[DEBUG] Agent 6 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                    if ws:
                        await ws.send_json({
                            "status": "processing",
                            "agent": "Final_Generator",
                            "message": f"추가 정보 반영하여 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                        })

                    retry_prompt = f"""당신은 AI 프로젝트 검토 전문가입니다.
이전 최종 의견에 대한 사용자 피드백을 반영하여 최종 의견을 재작성해주세요.

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

이전 최종 의견:
{final_recommendation}

사용자 피드백:
{user_feedback}

필요한 추가 정보: {', '.join(retry_decision.get('additional_info_needed', []))}

피드백을 반영하여 다음을 포함한 최종 의견을 재작성해주세요:
1. 승인 또는 보류 권장 (명확하게)
2. 주요 근거 (3-4가지)
3. 권장사항 (2-3가지)

간결하게 5-7문장으로 작성해주세요."""

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
                await ws.send_json({"status": "processing", "message": "피드백 반영하여 최종 보고서 생성 중..."})
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

        if ws:
            await ws.send_json({
                "status": "completed",
                "agent": "Final_Generator",
                "message": "검토 완료",
                "report": final_report
            })
        update_job_status(job_id, "completed")

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
    print(f"Feedback received (Job {job_id}): {feedback}")

    # DB 상태를 feedback_received로 업데이트
    update_job_status(job_id, "feedback_received")

    return {"status": "feedback_received", "job_id": job_id}

@app.get("/api/v1/review/pdf/{job_id}")
async def download_pdf(job_id: int):
    """PDF 다운로드"""
    # MVP: 간단한 응답
    return {"message": "PDF 생성 기능은 추후 구현 예정", "job_id": job_id}

if __name__ == "__main__":
    print(f"Server starting at http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
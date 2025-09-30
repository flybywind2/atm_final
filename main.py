# main.py - FastAPI 통합 서버 구현
from fastapi import FastAPI, UploadFile, File, WebSocket, Form, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import uvicorn
import asyncio
from pathlib import Path
import ollama

from database.db import init_database, create_job, get_job, update_job_status
from config.settings import HOST, PORT

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
    """서버 시작 시 데이터베이스 초기화"""
    print("Server starting...")
    init_database()
    print("Database ready")

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

def call_ollama(prompt: str, model: str = "gemma3:1b") -> str:
    """Ollama를 통한 LLM 호출"""
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}]
        )
        return response['message']['content']
    except Exception as e:
        print(f"Ollama API 호출 실패: {e}")
        return f"AI 응답 생성 실패: {e}"

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
    """RAG를 통한 BP 사례 검색 (실패 시 pass)"""
    try:
        # 실제 RAG 검색 로직 (회사 내부망에서만 동작)
        # 여기서는 시뮬레이션
        return {
            "success": True,
            "cases": [
                {"title": "AI 인프라 모니터링", "domain": domain, "division": division},
                {"title": "예측 유지보수 시스템", "domain": domain, "division": division},
                {"title": "이상 감지 자동화", "domain": domain, "division": division}
            ]
        }
    except Exception as e:
        print(f"RAG retrieve failed (pass): {e}")
        return {"success": False, "cases": []}

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
            await ws.send_json({"status": "completed", "agent": "BP_Scouter", "message": f"BP 사례 {len(bp_cases)}건 검색 완료"})
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
                    "message": "검토 결과를 확인하고 피드백을 제공해주세요",
                    "results": {
                        "objective_review": objective_review,
                        "feedback_suggestion": feedback_suggestion
                    }
                })
                print(f"[DEBUG] HITL interrupt sent via WebSocket")

            # 피드백 대기
            await wait_for_feedback(job_id)

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
            # 피드백 제안 생성
            feedback_suggestion = await asyncio.to_thread(
                generate_feedback_suggestion,
                "Data Analyzer",
                data_analysis,
                proposal_text
            )

            if ws:
                await ws.send_json({
                    "status": "interrupt",
                    "message": "데이터 분석 결과를 확인하고 피드백을 제공해주세요",
                    "results": {
                        "data_analysis": data_analysis,
                        "feedback_suggestion": feedback_suggestion
                    }
                })

            # 피드백 대기
            await wait_for_feedback(job_id)

            # 피드백 받은 후 계속 진행
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
            # 피드백 제안 생성
            feedback_suggestion = await asyncio.to_thread(
                generate_feedback_suggestion,
                "Risk Analyzer",
                risk_analysis,
                proposal_text
            )

            if ws:
                await ws.send_json({
                    "status": "interrupt",
                    "message": "리스크 분석 결과를 확인하고 피드백을 제공해주세요",
                    "results": {
                        "risk_analysis": risk_analysis,
                        "feedback_suggestion": feedback_suggestion
                    }
                })

            # 피드백 대기
            await wait_for_feedback(job_id)

            # 피드백 받은 후 계속 진행
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
            # 피드백 제안 생성
            feedback_suggestion = await asyncio.to_thread(
                generate_feedback_suggestion,
                "ROI Estimator",
                roi_estimation,
                proposal_text
            )

            if ws:
                await ws.send_json({
                    "status": "interrupt",
                    "message": "ROI 추정 결과를 확인하고 피드백을 제공해주세요",
                    "results": {
                        "roi_estimation": roi_estimation,
                        "feedback_suggestion": feedback_suggestion
                    }
                })

            # 피드백 대기
            await wait_for_feedback(job_id)

            # 피드백 받은 후 계속 진행
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
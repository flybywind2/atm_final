# AI Proposal Reviewer 개발 계획서

## 1. 프로젝트 개요

본 계획서는 **대규모 반도체 IDM 회사를 위한 전사 과제 지원서 자동 검토 및 개선 제안 시스템**의 MVP 개발 로드맵을 제시합니다. 시스템은 다중 AI 에이전트 아키텍처 기반으로 Human-in-the-Loop(HITL) 프로세스를 핵심으로 하며, 반도체 제조뿐만 아니라 연구개발, 설계, IT, 경영, 품질, 영업 등 전사 모든 부서의 과제 지원서를 검토하고 Best Practice(BP) 사례를 제공합니다.

### 🎯 MVP 개발 원칙
- **단순성 우선**: 핵심 기능에만 집중, 복잡한 기능은 추후 단계로 연기
- **빠른 검증**: 사용자 피드백을 통한 조기 검증 및 개선
- **점진적 확장**: MVP 성공 후 고도화 기능 단계적 추가
- **로깅 강화**: 디버깅을 위한 로그를 출력합니다.
- **전사 도메인 특화**: 모든 업무 영역 지원
  - **제조/생산**: 반도체 fab 공정, 품질 관리, 수율 개선, 장비 유지보수
  - **연구개발**: 신기술 연구, 공정 개선, 신제품 개발
  - **설계**: 회로 설계, Layout, 설계 자동화
  - **IT/DX**: 시스템 구축, 데이터 분석, AI/ML 프로젝트
  - **경영/기획**: 전략 기획, 투자 분석, 프로세스 혁신
  - **품질**: 품질 관리, 불량 분석, 품질 시스템 개선
  - **영업/마케팅**: 고객 관리, 시장 분석, 영업 전략
  - **HR/교육**: 인력 개발, 교육 프로그램, 조직 문화
- **API 구조**: OpenAI 호환 REST API 형태로 개발하여 표준화된 인터페이스 제공
- **LLM 지원**: appendix/internal_llm.py와 ollama 지원
- **웹 인터페이스**: localhost:8080으로 접속 가능한 프론트엔드 제공 (Javascript)

## 2. 개발 단계별 계획

### Phase 1: MVP 기반 구조 설정 (1-2주)

#### 1.1 프로젝트 구조 설정
- [ ] **의존성 관리 설정**
  - `requirements.txt` 생성
  - 핵심 패키지: LangGraph, LangChain, WeasyPrint, pytest
  - API 관련: FastAPI, uvicorn, pydantic (OpenAI 호환 API)
  - LLM 통합: openai, ollama
  - 프론트엔드: javascript
  - 데이터베이스: SQLite3 (MVP용 경량 데이터베이스)
  - **MVP 제외**: Redis, Celery, 복잡한 캐싱 등은 추후 단계에서 구현
- [ ] **디렉터리 구조 정리**
  ```
  atm_claude/
  ├── api/                # FastAPI 라우터 및 OpenAI 호환 엔드포인트
  ├── agents/             # 핵심 3개 에이전트 모듈 (MVP)
  ├── orchestrator/       # 중앙 오케스트레이터 (단순 동기 처리)
  ├── hitl/              # Human-in-the-Loop 인터페이스
  ├── database/          # SQLite 데이터베이스 모델
  ├── utils/             # 유틸리티 (PDF 생성 등)
  ├── config/            # 설정 파일 (단순한 환경 설정)
  ├── static/            # 정적 파일 (FastAPI StaticFiles로 서빙)
  │   ├── index.html     # 메인 HTML 파일
  │   ├── css/           # 스타일시트
  │   │   └── style.css  # 메인 스타일
  │   ├── js/            # JavaScript 모듈
  │   │   ├── components/    # UI 컴포넌트
  │   │   │   ├── ragPreview.js  # RAG 검색 결과 미리보기
  │   │   │   ├── dashboard.js   # 대시보드
  │   │   │   └── hitl.js        # HITL 피드백
  │   │   ├── services/      # API 호출 서비스
  │   │   │   └── api.js     # 백엔드 API 통신
  │   │   ├── utils/         # 유틸리티 함수
  │   │   │   └── helpers.js
  │   │   └── app.js         # 메인 애플리케이션
  │   └── assets/        # 이미지, 아이콘 등
  ├── tests/             # 테스트 코드 (pytest)
  ├── appendix/          # 기존 RAG/LLM 유틸리티
  ├── semiconductor_bp/  # 반도체 IDM 특화 BP 사례 데이터
  ├── requirements.txt   # Python 의존성
  └── main.py           # FastAPI 메인 애플리케이션 (통합 서버)
  ```

#### 1.2 MVP 기반 인프라 설정
- [ ] **SQLite 데이터베이스 설계 및 구축**
  ```sql
  -- MVP용 단순 스키마
  -- 작업 추적 테이블
  CREATE TABLE review_jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      status TEXT NOT NULL,
      user_id TEXT,
      proposal_content TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      metadata TEXT  -- JSON 문자열로 저장
  );

  -- HITL 피드백 테이블
  CREATE TABLE hitl_feedback (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id INTEGER REFERENCES review_jobs(id),
      agent_id TEXT NOT NULL,
      feedback_data TEXT,  -- JSON 문자열로 저장
      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
  );
  ```
- [ ] **MVP 단순화 설정**
  - **캐싱 미구현**: 메모리 기반 단순 처리
  - **비동기 처리 미구현**: 동기 방식으로 단순 처리
  - **보안 미구현**: 기본 HTTP 통신 (HTTPS, 인증 등은 추후 단계)
- [ ] **FastAPI 통합 서버 구축 (Port 8080)**
  - FastAPI 기반 REST API 서버 구조
  - `/v1/chat/completions` 호환 엔드포인트
  - Pydantic 모델로 OpenAI API 스키마 정의
  - SQLite 데이터베이스 연결
  - StaticFiles로 프론트엔드 정적 파일 서빙
  - localhost:8080으로 통합 접근
- [ ] **LLM 제공자 (MVP)**
  - OpenAI API / ollama API
  - **Fallback 미구현**: 단일 LLM 장애 시 에러 반환 (추후 개선)
  - **캐싱 미구현**: 매번 실제 LLM 호출
- [ ] **Vanilla JavaScript 프론트엔드**
  - 순수 JavaScript 기반 (React/Vue 미사용)
  - HTML/CSS/JS 정적 파일로 구성
  - FastAPI StaticFiles로 서빙
  - Fetch API로 백엔드 통신
- [ ] **LangGraph 오케스트레이션 프레임워크 설정 (MVP)**
  - State 정의 및 워크플로우 기본 구조
  - SQLite 기반 상태 지속성 (단순한 체크포인트)
  - HITL interrupt 기능 구현
  - **에러 복구 미구현**: 기본적인 에러 핸들링만 (추후 개선)
- [ ] **전사 BP 사례 RAG 연동**
  - `appendix/rag_retrieve.py` 활용하여 전사 부서별 BP 사례 검색
  - BP 사례 메타데이터 구조:
    - **기술유형**: 분류, 예측, 이상 감지, 최적화, 생성형, 기타
    - **업무 도메인**: 제조, 연구개발, 설계, IT/DX, 경영/기획, 품질, 영업/마케팅, HR/교육
    - **사업부**: DS(Device Solutions), Harman, SDC 등
    - **조직**: 세부 조직 정보
    - **문제 정의(AS-WAS)**: 기존 문제 상황
    - **문제 해결 방법(TO-BE)**: 해결 방안 및 접근법
    - **상세 내용 요약**: 6줄 이내 핵심 내용
    - **기술적&운영적 TIP**: 실무 적용 노하우
    - **참고자료/링크**: 관련 문서 및 자료
  - 부서별, 기술유형별, 문제유형별 다차원 검색 지원
  - **캐싱 미구현**: 실시간 검색만 수행
- [ ] **기본 개발 환경**
  - pytest 설정 및 기본 테스트 구조
  - **복잡한 모니터링 미구현**: 단순 실행 스크립트 (Docker 없이 로컬 실행)

#### 1.3 핵심 기술 스택 구현 가이드 (MVP 중심)

##### 1.3.1 FastAPI 서버 기본 설정
```python
# main.py - FastAPI 통합 서버 구현
from fastapi import FastAPI, UploadFile, File, WebSocket, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import uvicorn

app = FastAPI(title="AI Proposal Reviewer", version="1.0.0")

# CORS 설정 (MVP: 모든 origin 허용, 프로덕션에서는 제한 필요)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙 (프론트엔드)
app.mount("/static", StaticFiles(directory="static"), name="static")

# 루트 경로에서 index.html 제공
@app.get("/")
async def root():
    return FileResponse("static/index.html")

# 제안서 제출 API (파일 업로드 또는 텍스트 입력)
@app.post("/api/v1/review/submit")
async def submit_proposal(
    domain: str = Form(...),
    division: str = Form(...),
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
        # .txt, .md는 직접 디코딩, PDF/DOCX는 추후 고도화
        if file.filename.endswith(('.txt', '.md')):
            proposal_content = contents.decode('utf-8', errors='ignore')
        else:
            # PDF/DOCX는 추후 PyPDF2, python-docx 등으로 구현
            proposal_content = contents.decode('utf-8', errors='ignore')
    elif text:
        # 텍스트 직접 입력 방식
        proposal_content = text
    else:
        return {"error": "파일 또는 텍스트를 제공해주세요"}, 400

    # DB에 저장하고 job_id 생성
    from database.db import create_job
    job_id = create_job(proposal_content, domain, division)

    return {"job_id": job_id, "status": "submitted"}

# WebSocket 실시간 진행상황 업데이트
@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # 에이전트 진행상황 전송
            await websocket.send_json({"status": "processing", "agent": "BP_Scouter"})
    except Exception as e:
        print(f"WebSocket error: {e}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

##### 1.3.2 LangGraph 기본 구조 및 HITL 구현
```python
# orchestrator/graph.py - LangGraph 기반 에이전트 오케스트레이션
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver  # MVP: 메모리 기반 체크포인트
import uuid

# 상태 정의
class ReviewState(TypedDict):
    proposal_text: str
    domain: str  # 제조/R&D/설계/IT/경영/품질/영업/HR
    division: str  # DS, Harman, SDC 등
    bp_cases: list  # BP Case Scouter 결과
    objective_review: dict  # Objective Reviewer 결과
    data_analysis: dict  # Data Analyzer 결과
    risk_analysis: dict  # Risk Analyzer 결과
    roi_analysis: dict  # ROI Estimator 결과
    final_report: str  # Final Generator 결과
    user_feedback: str  # HITL 피드백

# BP Case Scouter 에이전트
def bp_case_scouter(state: ReviewState):
    print(f"[BP Case Scouter] 도메인: {state['domain']}")
    # RAG 검색 수행 (appendix/rag_retrieve.py 활용)
    from appendix.rag_retrieve import search_bp_cases
    bp_cases = search_bp_cases(
        query=state['proposal_text'],
        domain=state['domain'],
        division=state['division']
    )
    return {"bp_cases": bp_cases}

# Objective Reviewer 에이전트
def objective_reviewer(state: ReviewState):
    print(f"[Objective Reviewer] BP 사례 {len(state['bp_cases'])}개 참조")
    # LLM 호출하여 목표 검토
    from appendix.internal_llm import call_llm
    objective_review = call_llm(
        prompt=f"제안서: {state['proposal_text']}\nBP 사례: {state['bp_cases']}",
        model="gpt-oss:20b"
    )
    return {"objective_review": objective_review}

# HITL 노드 - interrupt 활용
def human_feedback_node(state: ReviewState):
    print("[HITL] 사용자 피드백 대기...")
    # interrupt()로 실행 중단 및 피드백 요청
    feedback = interrupt({
        "message": "검토 결과를 확인하고 피드백을 제공해주세요",
        "bp_cases": state['bp_cases'],
        "objective_review": state['objective_review'],
        "data_analysis": state['data_analysis']
    })
    return {"user_feedback": feedback}

# 그래프 구축
def build_review_graph():
    builder = StateGraph(ReviewState)

    # 노드 추가
    builder.add_node("bp_scouter", bp_case_scouter)
    builder.add_node("objective_reviewer", objective_reviewer)
    builder.add_node("hitl", human_feedback_node)
    # ... 추가 에이전트 노드

    # 엣지 정의
    builder.add_edge(START, "bp_scouter")
    builder.add_edge("bp_scouter", "objective_reviewer")
    builder.add_edge("objective_reviewer", "hitl")
    # ... 추가 엣지

    # MVP: MemorySaver로 간단한 체크포인트 (프로덕션에서는 DB 기반 사용)
    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    return graph

# 그래프 실행
def run_review(proposal_text: str, domain: str, division: str):
    graph = build_review_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    # 첫 실행 (interrupt까지)
    result = graph.invoke({
        "proposal_text": proposal_text,
        "domain": domain,
        "division": division
    }, config=config)

    print("Interrupt 발생:", result.get("__interrupt__"))
    return result, config

# 피드백으로 재개
def resume_with_feedback(config: dict, feedback: str):
    graph = build_review_graph()
    result = graph.invoke(Command(resume=feedback), config=config)
    return result
```

##### 1.3.3 SQLite 연동 (MVP 간단 구현)
```python
# database/db.py - SQLite 연동 (ORM 없이 순수 SQL)
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/review.db")

def init_database():
    """데이터베이스 초기화"""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 테이블 생성
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS review_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            user_id TEXT,
            proposal_content TEXT,
            domain TEXT,
            division TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hitl_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER REFERENCES review_jobs(id),
            agent_id TEXT NOT NULL,
            feedback_data TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

def create_job(proposal_content: str, domain: str, division: str):
    """새 검토 작업 생성"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO review_jobs (status, proposal_content, domain, division, metadata)
        VALUES (?, ?, ?, ?, ?)
    """, ("pending", proposal_content, domain, division, "{}"))

    job_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return job_id

def save_feedback(job_id: int, agent_id: str, feedback_data: dict):
    """HITL 피드백 저장"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO hitl_feedback (job_id, agent_id, feedback_data)
        VALUES (?, ?, ?)
    """, (job_id, agent_id, json.dumps(feedback_data)))

    conn.commit()
    conn.close()

# MVP: 복잡한 쿼리 최적화, 인덱싱, 트랜잭션 관리 등은 추후 구현
```

##### 1.3.4 WeasyPrint PDF 생성 (MVP)
```python
# utils/pdf_generator.py - WeasyPrint 기반 PDF 생성
from weasyprint import HTML, CSS
from pathlib import Path

def generate_report_pdf(report_data: dict, output_path: str):
    """검토 결과를 PDF로 생성"""

    # 간단한 HTML 템플릿 (MVP: 복잡한 템플릿 엔진 제외)
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>AI 과제 검토 보고서</title>
        <style>
            body {{ font-family: 'Malgun Gothic', sans-serif; margin: 40px; }}
            h1 {{ color: #003366; }}
            .section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; }}
        </style>
    </head>
    <body>
        <h1>AI 과제 지원서 검토 보고서</h1>
        <div class="section">
            <h2>1. BP 사례 검색 결과</h2>
            <p>{report_data.get('bp_cases', 'N/A')}</p>
        </div>
        <div class="section">
            <h2>2. 목표 및 효과 검토</h2>
            <p>{report_data.get('objective_review', 'N/A')}</p>
        </div>
        <!-- 추가 섹션 -->
    </body>
    </html>
    """

    HTML(string=html_content).write_pdf(output_path)
    return output_path

# MVP: 복잡한 차트, 이미지 삽입, 다국어 지원 등은 추후 구현
```

##### 1.3.5 MVP 제외 사항 (명확화)
- ❌ **보안/인증**: JWT, OAuth, API Key 검증 등 (추후 구현)
- ❌ **Fallback 메커니즘**: LLM API 실패 시 대체 모델 전환 (추후 구현)
- ❌ **캐싱**: Redis, 메모리 캐시 등 (추후 구현)
- ❌ **비동기 큐**: Celery, RabbitMQ 등 (추후 구현)
- ❌ **ORM**: SQLAlchemy, Tortoise-ORM 등 (순수 SQL 사용)
- ❌ **복잡한 에러 복구**: 재시도, 서킷 브레이커 등 (기본 예외 처리만)
- ❌ **모니터링**: Prometheus, Grafana 등 (기본 로깅만)
- ❌ **로드 밸런싱**: Nginx, HAProxy 등 (단일 서버)
- ❌ **컨테이너화**: Docker, Kubernetes 등 (로컬 실행)

##### 1.3.6 Vanilla JavaScript 프론트엔드 기본 구조
```html
<!-- static/index.html - 메인 HTML -->
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 과제 지원서 검토 시스템</title>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div id="app">
        <header>
            <h1>AI 과제 지원서 검토 시스템</h1>
        </header>

        <main>
            <!-- 제안서 입력 -->
            <section id="upload-section">
                <h2>제안서 입력</h2>
                <div>
                    <label>업무 도메인:</label>
                    <select id="domain-select">
                        <option value="제조">제조/생산</option>
                        <option value="연구개발">연구개발</option>
                        <option value="설계">설계</option>
                        <option value="IT/DX">IT/DX</option>
                        <option value="경영">경영/기획</option>
                        <option value="품질">품질</option>
                        <option value="영업">영업/마케팅</option>
                        <option value="HR">HR/교육</option>
                    </select>
                </div>
                <div>
                    <label>사업부:</label>
                    <select id="division-select">
                        <option value="메모리">메모리</option>
                        <option value="S.LSI">S.LSI</option>
                        <option value="Foundry">Foundry</option>
                    </select>
                </div>

                <!-- 입력 방식 선택 -->
                <div>
                    <label>
                        <input type="radio" name="input-type" value="file" checked>
                        파일 업로드
                    </label>
                    <label>
                        <input type="radio" name="input-type" value="text">
                        직접 작성
                    </label>
                </div>

                <!-- 파일 업로드 -->
                <div id="file-upload-container">
                    <input type="file" id="file-input" accept=".txt,.md,.pdf,.docx">
                </div>

                <!-- 텍스트 직접 입력 -->
                <div id="text-input-container" style="display: none;">
                    <textarea id="text-input" rows="15" placeholder="제안서 내용을 입력하세요..."></textarea>
                </div>

                <button id="submit-btn">검토 시작</button>
            </section>

            <!-- 진행 상황 -->
            <section id="progress-section" style="display: none;">
                <h2>검토 진행 상황</h2>
                <div id="agent-status">
                    <div class="agent-item">
                        <span>BP Case Scouter</span>
                        <span id="agent-1-status">대기중</span>
                    </div>
                    <div class="agent-item">
                        <span>Objective Reviewer</span>
                        <span id="agent-2-status">대기중</span>
                    </div>
                    <!-- 추가 에이전트 -->
                </div>
            </section>

            <!-- HITL 피드백 -->
            <section id="hitl-section" style="display: none;">
                <h2>검토 결과 확인</h2>
                <div id="review-results"></div>
                <textarea id="feedback-input" placeholder="피드백 입력..."></textarea>
                <button id="submit-feedback-btn">승인 및 계속</button>
            </section>

            <!-- 최종 결과 -->
            <section id="result-section" style="display: none;">
                <h2>최종 검토 보고서</h2>
                <div id="final-report"></div>
                <button id="download-pdf-btn">PDF 다운로드</button>
            </section>
        </main>
    </div>

    <script type="module" src="/static/js/app.js"></script>
</body>
</html>
```

```javascript
// static/js/app.js - 메인 애플리케이션 로직
let currentJobId = null;
let wsConnection = null;

// 입력 방식 전환
document.querySelectorAll('input[name="input-type"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
        const inputType = e.target.value;
        if (inputType === 'file') {
            document.getElementById('file-upload-container').style.display = 'block';
            document.getElementById('text-input-container').style.display = 'none';
        } else {
            document.getElementById('file-upload-container').style.display = 'none';
            document.getElementById('text-input-container').style.display = 'block';
        }
    });
});

// 제안서 제출 및 검토 시작
document.getElementById('submit-btn').addEventListener('click', async () => {
    const domain = document.getElementById('domain-select').value;
    const division = document.getElementById('division-select').value;
    const inputType = document.querySelector('input[name="input-type"]:checked').value;

    let proposalContent = '';
    let formData = new FormData();
    formData.append('domain', domain);
    formData.append('division', division);

    if (inputType === 'file') {
        // 파일 업로드
        const fileInput = document.getElementById('file-input');
        const file = fileInput.files[0];

        if (!file) {
            alert('파일을 선택해주세요');
            return;
        }

        formData.append('file', file);
    } else {
        // 텍스트 직접 입력
        const textInput = document.getElementById('text-input').value.trim();

        if (!textInput) {
            alert('제안서 내용을 입력해주세요');
            return;
        }

        formData.append('text', textInput);
    }

    try {
        const response = await fetch('/api/v1/review/submit', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();
        currentJobId = result.job_id;

        // 진행 상황 섹션 표시
        document.getElementById('upload-section').style.display = 'none';
        document.getElementById('progress-section').style.display = 'block';

        // WebSocket 연결
        connectWebSocket(currentJobId);
    } catch (error) {
        console.error('Submit error:', error);
        alert('제출 중 오류 발생');
    }
});

// WebSocket 연결 및 실시간 업데이트
function connectWebSocket(jobId) {
    wsConnection = new WebSocket(`ws://localhost:8080/ws/${jobId}`);

    wsConnection.onmessage = (event) => {
        const data = JSON.parse(event.data);

        // 에이전트 상태 업데이트
        if (data.agent) {
            updateAgentStatus(data.agent, data.status);
        }

        // HITL 인터럽트 처리
        if (data.status === 'interrupt') {
            showHITLSection(data.results);
        }

        // 최종 완료
        if (data.status === 'completed') {
            showFinalResults(data.report);
        }
    };

    wsConnection.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

// 에이전트 상태 업데이트
function updateAgentStatus(agent, status) {
    const statusElement = document.getElementById(`agent-${agent}-status`);
    if (statusElement) {
        statusElement.textContent = status;
    }
}

// HITL 섹션 표시
function showHITLSection(results) {
    document.getElementById('progress-section').style.display = 'none';
    document.getElementById('hitl-section').style.display = 'block';

    // 검토 결과 표시
    const resultsDiv = document.getElementById('review-results');
    resultsDiv.innerHTML = `
        <h3>BP 사례 검색 결과</h3>
        <p>${JSON.stringify(results.bp_cases, null, 2)}</p>
        <h3>목표 검토</h3>
        <p>${JSON.stringify(results.objective_review, null, 2)}</p>
    `;
}

// 피드백 제출
document.getElementById('submit-feedback-btn').addEventListener('click', async () => {
    const feedback = document.getElementById('feedback-input').value;

    try {
        await fetch(`/api/v1/review/feedback/${currentJobId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feedback })
        });

        // 다시 진행 상황으로 전환
        document.getElementById('hitl-section').style.display = 'none';
        document.getElementById('progress-section').style.display = 'block';
    } catch (error) {
        console.error('Feedback error:', error);
    }
});

// 최종 결과 표시
function showFinalResults(report) {
    document.getElementById('progress-section').style.display = 'none';
    document.getElementById('result-section').style.display = 'block';

    document.getElementById('final-report').innerHTML = report;
}

// PDF 다운로드
document.getElementById('download-pdf-btn').addEventListener('click', async () => {
    window.location.href = `/api/v1/review/pdf/${currentJobId}`;
});
```

##### 1.3.7 requirements.txt (MVP 최소 의존성)
```text
# 핵심 프레임워크
fastapi==0.115.0
uvicorn[standard]==0.30.0
python-multipart==0.0.9  # 파일 업로드

# LangGraph & LangChain
langgraph==0.2.50
langchain==0.3.0
langchain-core==0.3.0

# LLM 연동
openai==1.50.0  # OpenAI API (선택)
# ollama는 별도 설치 필요: curl -fsSL https://ollama.com/install.sh | sh

# PDF 생성
weasyprint==62.3

# 데이터베이스
# SQLite3은 Python 표준 라이브러리에 포함

# 유틸리티
python-dotenv==1.0.0  # 환경 변수 관리
pydantic==2.9.0  # 데이터 검증

# 테스트
pytest==8.3.0
pytest-asyncio==0.24.0

# MVP 제외 (추후 추가)
# redis==5.0.0  # 캐싱
# celery==5.4.0  # 비동기 작업
# sqlalchemy==2.0.0  # ORM
```

##### 1.3.8 개발 시작 가이드
```bash
# 1. 환경 설정
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. Ollama 설치 (로컬 LLM 사용 시)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma3:1b
ollama pull gpt-oss:20b

# 4. 데이터베이스 초기화
python -c "from database.db import init_database; init_database()"

# 5. 환경 변수 설정 (.env 파일)
cat > .env << EOF
OPENAI_API_KEY=your_key_here  # 선택
OLLAMA_BASE_URL=http://localhost:11434
LOG_LEVEL=INFO
EOF

# 6. 서버 실행
python main.py
# 또는: uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# 7. 브라우저에서 접속
# http://localhost:8080
```

### Phase 2: 전체 에이전트 개발 (3-4주)

#### **전체 6개 에이전트 구현**: 전사 업무 영역 특화 완전한 검토 시스템

#### 2.1 BP Case Scouter (AGT-01) 구현 [Priority: High]
- [ ] **기능 구현 (MVP 단순화)**
  - 지원서 내용 기반 전사 부서별 BP 사례 3-5개 검색
  - 제조, 연구개발, 설계, IT/DX, 경영, 품질, 영업, HR 등 모든 도메인 지원
  - 동기 처리 방식 (Celery 미사용)
- [ ] **입출력 정의**
  - 입력: 지원서 전문 (텍스트) + 업무 도메인 키워드 + 사업부/조직 정보
  - 출력: JSON 형식 전사 BP 사례 목록 (관련성 점수, 유사 문제/해결법 포함)
- [ ] **RAG 검색 (MVP 단순화)**
  - `appendix/rag_retrieve.py` 활용하여 전사 도메인 특화 검색
  - 업무 영역별(제조/R&D/설계/IT/경영/품질/영업/HR) 검색 지원
  - **캐싱 미구현**: 매번 실시간 검색
  - 검색 정확도 우선, 속도는 2차 목표
  - 실시간 결과 전송 (WebSocket을 통한 즉시 UI 반영)
- [ ] **에러 처리 (MVP 단순화)**
  - **Fallback 미구현**: 검색 실패 시 에러 반환
  - 기본적인 재시도 로직 (최대 3회)
  - 로그 기반 오류 추적

#### 2.2 Objective & Impact Reviewer (AGT-02) 구현 [Priority: High]
- [ ] **전사 업무 영역별 목표 검토 로직**
  - **제조/생산**: 불량률, 수율, 다운타임, 처리량, 생산성 지표
  - **연구개발**: 개발 기간, 성공률, 특허 출원, 기술 이전
  - **설계**: 설계 기간, 검증 시간, 설계 품질, 재사용률
  - **IT/DX**: 시스템 성능, 데이터 정확도, 사용자 만족도, 자동화율
  - **경영/기획**: ROI, 비용 절감, 프로세스 효율, 의사결정 속도
  - **품질**: 품질 지표, 불량률, 고객 만족도, 규제 준수
  - **영업/마케팅**: 매출 증가, 고객 확보, 시장 점유율, 고객 만족도
  - **HR/교육**: 교육 효과, 직원 만족도, 역량 향상, 이직률
  - 기본 LLM 응답 품질 검증 (복잡한 RAGAS 메트릭은 추후 단계)
- [ ] **전사 BP 사례 기반 개선 제안**
  - 유사 부서, 유사 문제 유형의 BP 사례 참조
  - 해당 업무 도메인에 맞는 구체적 예시와 수정 제안 생성
  - MVP에서는 단일 프롬프트 사용 (A/B 테스트 제외)
- [ ] **성능 (MVP 단순화)**
  - **캐싱 미구현**: 매번 실제 LLM 호출
  - 업무 도메인별 특화 프롬프트로 정확도 향상

#### 2.3 **HITL 프로토타입 우선 개발** [Priority: Critical]
- [ ] **기본 HITL 워크플로우 구현**
  ```python
  # LangGraph HITL 구현 예시
  def human_feedback_node(state, config):
      feedback = interrupt(value="사용자 피드백 대기 중...")
      return Command(
          update={"messages": [HumanMessage(content=feedback)]},
          goto=state["last_active_agent"]
      )
  ```
  - LangGraph interrupt 기능을 활용한 HITL 구현
  - 피드백 데이터 저장 및 검색
  - 세션 관리 및 재개 로직
- [ ] **WebSocket 실시간 통신**
  - 진행상황 실시간 업데이트
  - 피드백 요청 및 응답 처리
  - 연결 끊김 시 자동 재연결

#### 2.4 Data & Constraint Analyzer (AGT-03) 구현 [Priority: Medium]
- [ ] **전사 업무별 데이터 특화 진단**
  - **제조**: 웨이퍼 이미지, SEM 데이터, 센서 로그, 생산 데이터
  - **연구개발**: 실험 데이터, 시뮬레이션 결과, 측정 데이터
  - **설계**: 설계 도면, 검증 결과, 시뮬레이션 데이터
  - **IT/DX**: 시스템 로그, 트랜잭션 데이터, 사용자 데이터
  - **경영/기획**: 경영 지표, 재무 데이터, 프로세스 데이터
  - **품질**: 검사 데이터, 불량 분석, 품질 이력
  - **영업/마케팅**: 고객 데이터, 매출 데이터, 시장 데이터
  - **HR/교육**: 인사 데이터, 교육 이력, 역량 평가
  - 데이터 양, 라벨링 상태, I/O 형식 적합성 검토
- [ ] **전사 기술적 제약 조건 분석**
  - 인프라 환경 (온프레미스/클라우드), 보안 요구사항
  - 부서별 정확도 요구사항 및 성능 제약

#### 2.5 **조기 부하 테스트 및 성능 검증**
- [ ] **기본 성능 벤치마킹**
  - 개별 에이전트 응답시간 측정
  - 동시 요청 처리 능력 테스트 (10명)
  - RAG 검색 성능 프로파일링
- [ ] **병목점 식별 및 최적화**
  - 느린 구간 분석 및 개선
  - 캐싱 효과 측정
  - LLM API 응답시간 모니터링

#### 2.4 Risk & Failure Analyzer (AGT-04) 구현
- [ ] **전사 업무별 실패 사례 기반 리스크 예측**
  - **제조**: 컨태미네이션, 장비 다운타임, 공정 변동, 수율 저하
  - **연구개발**: 개발 지연, 기술 검증 실패, 예산 초과
  - **설계**: 설계 오류, 검증 미흡, 표준 미준수
  - **IT/DX**: 시스템 장애, 데이터 품질, 보안 취약점, 통합 문제
  - **경영/기획**: 전략 실패, ROI 미달, 이해관계자 반발
  - **품질**: 품질 이슈, 규제 위반, 고객 불만
  - **영업/마케팅**: 시장 예측 실패, 고객 이탈, 경쟁 심화
  - **HR/교육**: 교육 효과 미흡, 직원 저항, 역량 부족
- [ ] **전사 완화 전략 제안**
  - BP 사례 기반 업무별 리스크 대응 방안
  - 부서별 특화된 리스크 관리 방안

#### 2.5 ROI & Roadmap Estimator (AGT-05) 구현
- [ ] **전사 업무별 ROI 산정 로직**
  - 초기 투자: 하드웨어, 소프트웨어, 교육, 인력 비용
  - **제조**: 수율 향상, 다운타임 감소, 품질 비용 절감
  - **연구개발**: 개발 기간 단축, 성공률 향상, 특허 수익
  - **설계**: 설계 기간 단축, 재작업 감소, 품질 향상
  - **IT/DX**: 시스템 효율화, 자동화 효과, 운영 비용 절감
  - **경영/기획**: 의사결정 속도, 프로세스 효율, 전략 성과
  - **품질**: 품질 비용 절감, 클레임 감소, 고객 만족
  - **영업/마케팅**: 매출 증가, 고객 확보, 시장 점유율
  - **HR/교육**: 교육 효과, 생산성 향상, 이직률 감소
  - 7만명 규모 조직 ROI 계산 (인건비 절감, 생산성 향상)
  - BP 사례 기반 업계 표준 ROI 수치 검증
- [ ] **전사 3단계 실행 로드맵 생성**
  - **PoC 단계** (3-6개월): 단일 부서/팀에서 소규모 검증
  - **Pilot 단계** (6-12개월): 부서 전체 또는 다중 팀으로 확장
  - **Full Scale** (12-24개월): 전사 확산, 다중 사업부/조직 적용
  - 각 단계별 부서 특화 자원, 기간, 성과 지표 정의

#### 2.6 Final Review & PDF Generator (AGT-99) 구현 [Priority: High]
- [ ] **전체 6개 에이전트 출력 통합**
  - BP Case Scouter + Objective Reviewer + Data Analyzer + Risk Analyzer + ROI Estimator 결과 종합
  - 표준 템플릿 기반 일관성 검토 및 상호 검증
  - 에이전트 간 결과 일치성 검증 (예: ROI 추정치와 Risk 평가 간 논리적 일관성)
  - HITL 승인 후 최종 검증
- [ ] **전사 종합 PDF/Markdown 생성**
  - WeasyPrint 기반 전문적 PDF 생성 (6개 섹션 구조화)
  - 표준 제안서 양식 적용 (회사 로고, 표준 포맷)
  - 부서별 특화 보고서 양식 (기술적 리스크, ROI, 실행 로드맵 포함)
  - 경영진 보고용 요약 페이지 + 실무팀용 상세 분석 섹션
  - 부서별 맞춤형 산출물 (제조/R&D/설계/IT/경영/품질/영업/HR)

### Phase 3: MVP 시스템 통합 및 웹 인터페이스 개발 (2-3주)

#### 3.1 Review Orchestrator 개발
- [ ] **6개 에이전트 워크플로우 관리**
  - LangGraph State Machine 기반 6개 에이전트 순차 실행 내 일부 병렬 처리
  - 기본적인 에러 처리 및 에이전트별 재시도 로직
  - SQLite 기반 상태 저장 및 다단계 체크포인트
  - 에이전트 간 의존성 관리 (BP Scouter → 나머지 에이전트)
- [ ] **OpenAI 호환 API 엔드포인트 (전체 시스템)**
  - `/v1/semiconductor/review/proposal` - 반도체 IDM 제안서 검토 시작
  - `/v1/semiconductor/review/status/{job_id}` - 6개 에이전트 검토 상태 확인
  - `/v1/semiconductor/review/feedback/{job_id}` - HITL 피드백 제출
  - `/v1/semiconductor/rag-results/{job_id}` - 반도체 BP 검색 결과 조회
  - `/v1/semiconductor/agents/{agent_id}/results/{job_id}` - 개별 에이전트 결과 조회
  - WebSocket 지원 (6개 에이전트 진행상황 + 결과 실시간 전송)
- [ ] **성능 목표 (전체 시스템)**
  - 순차+일부병렬 처리로 8-12분 목표 (6개 에이전트)
  - Risk + ROI 에이전트 추가로 고품질 검토 보장

#### 3.1.1 전사 Vanilla JS 프론트엔드 UI/UX 개발
- [ ] **메인 대시보드 (localhost:8080/)**
  - 순수 JavaScript/HTML/CSS로 구현
  - 전사 과제 제안서 업로드 인터페이스 (File API)
  - **업무 도메인 선택**: 제조, 연구개발, 설계, IT/DX, 경영/기획, 품질, 영업/마케팅, HR/교육
  - **사업부/조직 선택**: 메모리, S.LSI, Foundry 등 + 세부 조직
  - **6개 에이전트 진행 상황** 실시간 표시 (진행률, 단계별 상태)
  - 에이전트별 검토 결과 상세 시각화 (BP/Objective/Data/Risk/ROI/Final)
  - **에이전트 간 연관성 표시**: ROI-Risk 상관관계, Objective-Data 일치성 등
- [ ] **전사 BP 검색 결과 미리보기 패널**
  - BP 사례 검색 완료 후 즉시 표시
  - 검색된 전사 BP 사례 목록 (부서별, 기술유형별, 문제유형별)
  - 성공/실패 사례 구분 표시 및 관련성 점수
  - 상세 내용 펼침/접힘 (Vanilla JS 토글)
  - AS-WAS/TO-BE, TIP, 참고자료 표시
  - ROI/Risk 분석에 활용될 사례 하이라이트
- [ ] **향상된 HITL 피드백 인터페이스**
  - **6개 에이전트별 피드백** 수집 폼 (Objective/Data/Risk/ROI 각각)
  - 에이전트별 Before/After 비교 화면 + 연관성 영향 표시
  - 수정 제안 승인/거부/수정 버튼 (세분화된 피드백 옵션)
  - 전사 BP 사례 참조 정보 연동 표시
  - Fetch API로 피드백 전송
- [ ] **종합 결과 다운로드 페이지**
  - 전사 부서별 특화 PDF 생성 (6개 섹션 구조)
  - **경영진용 요약** + **실무팀용 상세 분석** 도구 제공
  - 부서별 맞춤형 보고서 (제조/R&D/설계/IT/경영/품질/영업/HR)
  - 전체 6개 에이전트 검토 히스토리 SQLite 저장 및 추적
  - 검토 진행 상황 실시간 표시
  - 에이전트별 검토 결과 시각화
  - PDF 다운로드 (Blob API 활용)
- [ ] **RAG 검색 결과 미리보기 패널**
  - BP 사례 검색 완료 후 즉시 표시
  - 검색된 BP 사례 목록 (제목, 배경, 성공요인)
  - 관련성 점수 및 유사도 표시
  - 상세 내용 펼침/접힘 기능
  - 사용자 검토 대기 시간 동안 참고 자료 제공
- [ ] **HITL 피드백 인터페이스**
  - 인터랙티브 피드백 수집 폼
  - Before/After 비교 화면
  - 수정 제안 승인/거부 버튼
  - BP 사례 참조 정보 연동 표시
- [ ] **결과 다운로드 페이지**
  - PDF 생성 및 다운로드
  - 검토 요약 보고서 표시
  - 검토 히스토리 관리

#### 3.2 HITL 인터페이스 구현
- [ ] **피드백 수집 시스템**
  - 구조화된 JSON 형식 피드백 처리
  - 명확한 예시 제시 및 간단한 수정 입력 유도
- [ ] **반복 제어 로직**
  - 최대 3회 반복 제한
  - 무한 루프 방지 메커니즘

### Phase 4: 전체 시스템 테스트 및 품질 보증 (3주)

#### 4.1 6개 에이전트 단위 테스트 및 LLM 테스트 전략
- [ ] **전체 6개 에이전트 기능 테스트**
  - 각 에이전트의 입출력 검증 (BP/Objective/Data/Risk/ROI/Final)
  - 에이전트 간 상호작용 및 의존성 테스트
  - 반도체 도메인 특화 예외 상황 처리 테스트
- [ ] **LLM 비결정성 대응 테스트**
  ```python
  # LLM Mock 테스트 전략
  @patch('llm_providers.get_llm_response')
  def test_agent_with_mock_llm(mock_llm):
      mock_llm.return_value = "예상된 응답"
      result = agent.process(test_input)
      assert result.status == "success"

  # 실제 LLM 응답 품질 테스트
  def test_agent_response_quality():
      results = [agent.process(test_case) for _ in range(10)]
      quality_scores = [ragas_evaluate(r) for r in results]
      assert np.mean(quality_scores) >= 0.85
  ```
- [ ] **RAG 검색 정확도 테스트**
  - BP 사례 검색 성능 평가
  - False positive/negative 최소화
  - 다양한 쿼리 타입별 성능 검증

#### 4.2 통합 테스트
- [ ] **6개 에이전트 전체 워크플로우 테스트**
  - ollama LLM을 통한 6개 에이전트 end-to-end 테스트
  - 반도체 IDM 시나리오별 통합 테스트
  - LangGraph Test Harness 활용 6개 에이전트 상태 관리
- [ ] **6개 에이전트 HITL 시나리오 테스트**
  - Playwright 기반 다중 에이전트 사용자 상호작용 테스트
  - 에이전트별 피드백 반영 → 재생성 검증
  - 반도체 IDM 비즈니스 시나리오 기반 HITL 상호작용

#### 4.3 프론트엔드 테스트
- [ ] **UI/UX 테스트**
  - Playwright 또는 Cypress 기반 E2E 테스트
- [ ] **API 통신 테스트**
  - Frontend-Backend 통신 검증 (Fetch API)
  - WebSocket 연결 안정성 테스트
  - 파일 업로드/다운로드 기능 테스트
  - RAG 검색 결과 실시간 업데이트 테스트

#### 4.4 성능 테스트 (향상된 목표)
- [ ] **응답 시간 측정**
  - **수정된 목표**: 평균 4-6분 (현실적 조정, HITL 제외)
  - 개별 에이전트별 성능 프로파일링

### Phase 5: 전체 시스템 문서화 및 배포 준비 (1-2주)

#### 5.1 API 문서화
- [ ] **에이전트 API 명세서**
  - 각 에이전트의 입출력 스키마
  - 에러 코드 및 처리 방안
- [ ] **HITL 인터페이스 가이드**
  - 사용자 피드백 입력 방법
  - 최적 실행 가이드라인
- [ ] **프론트엔드 사용자 매뉴얼**
  - localhost:8080 접속 및 사용법
  - UI 구성요소 설명 및 사용 시나리오

#### 5.2 배포 설정
- [ ] **환경 설정 파일**
  - Development/Production 환경 분리
  - 보안 키 및 인증 정보 관리
- [ ] **통합 실행 스크립트**
  - `python main.py` 또는 `uvicorn main:app --host 0.0.0.0 --port 8080`
  - FastAPI로 API + 정적 파일 통합 서빙
- [ ] **헬스 체크 엔드포인트**
  - LLM, PDF Generator 상태 모니터링
  - Frontend 정적 파일 서빙 상태 확인
  - `/health` 엔드포인트로 시스템 상태 체크

## 3. 기술적 고려사항

### 3.1 API 아키텍처
- **OpenAI 호환성**: 표준 REST API 패턴 준수
  - Request/Response 모델: OpenAI API 스키마 호환
  - Authentication: Bearer token 및 API key 지원
  - Error handling: HTTP 상태 코드 및 에러 메시지 표준화
  - appendix/internal_llm.py 참고하여 default_header 사용
- **다중 LLM 지원**:
  - OpenAI GPT 시리즈 (llama4 scout, llama4 maverick, gpt-oss:120b 등)
  - Ollama 로컬 모델 (gemma3:1b, gpt-oss:20b 등)
-  **환경 변수**
  - dotenv를 활용한 환경 변수 관리

### 3.2 웹 인터페이스 아키텍처
- **프론트엔드 구조**: Vanilla JavaScript 기반
  - localhost:8080 접속으로 index.html 실행
  - FastAPI StaticFiles로 정적 파일 서빙
  - 백엔드 API와 동일 포트로 통합 서빙
  - Fetch API를 통한 백엔드 통신
  - WebSocket을 통한 실시간 진행상황 업데이트
- **사용자 경험**: 직관적이고 반응형 UI/UX
  - 제안서 업로드: 드래그 앤 드롭 지원 (File API)
  - 진행 상태: 프로그레스 바 및 로딩 애니메이션 (Vanilla JS)
  - RAG 검색 결과: 대기 시간 동안 참고할 수 있는 BP 사례 미리보기
  - HITL 피드백: 인터랙티브 폼 및 실시간 미리보기

### 3.3 성능 목표 (수정된 현실적 목표)
- **응답 시간**: 평균 4-6분 (HITL 제외, 현실적으로 조정)
- **정확도**: RAG Faithfulness ≥ 0.85, 생성 오류율 < 5%
- **가용성**: HITL 승인률 ≥ 90%, 사용자 만족도 ≥ 4.5/5
- **동시성**: 비동기 처리로 다중 요청 동시 처리 (최대 30명)
- **프론트엔드 성능**: 초기 로드 시간 < 3초, 인터랙션 응답 < 200ms
- **캐싱 효율성**: RAG 검색 캐시 히트율 ≥ 70%

### 3.4 확장성 설계
- 에이전트 추가/삭제 용이성
- 산업별 BP 사례 분리 관리 가능
- 멀티 도메인 확장 준비
- 수평 확장 가능한 stateless API 설계
- 프론트엔드 컴포넌트 기반 모듈화

### 3.5 보안 고려사항
- 추후 별도 적용 예정 (개발 단계에서는 제외)
- 인증 정보 안전한 관리
- API 접근 제어 기본 구조

## 4. 향후 발전 계획

### 4.1 MVP 이후 고도화 방안 (반도체 IDM 전용)
- **반도체 특화 RLHF**: HITL 피드백을 통한 fab 환경 에이전트 자동 개선
- **반도체 자가 진단**: 웨이퍼/SEM/AOI 데이터 품질 저하 감지 및 재학습
- **IDM 전체 확장**: Design → Fab → Test → Assembly 전 공정 단계 특화
- **지능형 캐싱 추가**: 7만명 조직 내 사용 패턴 학습 기반 예측적 캐싱

### 4.2 반도체 IDM 전용 통합 확장
- **반도체 MES/ERP 연동**: SAP, Oracle 등 기업 시스템 통합
- **fab 생산성 API**: OpenAI 호환 API로 생산부서 내부 도구 연돐
- **반도체 특화 LLM**: Samsung/TSMC 등 반도체 전용 모델 지원
- **K8s 배포**: 7만명 규모 온프레미스 인프라에 맞는 확장
- **fab 전용 모바일**: 클린룸/fab 환경에서 사용 가능한 전용 인터페이스
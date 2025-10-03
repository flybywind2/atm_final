# 에이전트 모듈

AI 과제 지원서 검토 시스템의 모듈화된 에이전트 구현체들입니다.

## 파일 구조

```
agents/
├── __init__.py                    # 모듈 export (19줄)
├── utils.py                       # 공통 유틸리티 함수 (334줄)
├── agent1_bp_scouter.py          # BP Case Scouter (53줄)
├── agent2_objective_reviewer.py  # Objective Reviewer (236줄)
├── agent3_data_analyzer.py       # Data Analyzer (228줄)
├── agent4_risk_analyzer.py       # Risk Analyzer (224줄)
├── agent5_roi_estimator.py       # ROI Estimator (222줄)
├── agent6_final_generator.py     # Final Generator (402줄)
├── agent7_proposal_improver.py   # Proposal Improver (166줄)
├── INTEGRATION_GUIDE.md          # main.py 통합 가이드
└── README.md                      # 이 파일
```

**전체 라인 수: 1,884줄** (main.py에서 모듈화)

## 모듈 설명

### utils.py
모든 에이전트가 공통으로 사용하는 유틸리티 함수:
- `_extract_json_dict()` - LLM 응답에서 JSON 추출
- `_truncate_for_prompt()` - 프롬프트용 텍스트 자르기
- `analyze_result_quality()` - 에이전트 결과 품질 검사
- `generate_feedback_suggestion()` - HITL 피드백 예시 생성 (에이전트별 특화)
- `wait_for_feedback()` - HITL 루프에서 사용자 피드백 대기
- `persist_job_metadata()` - 에이전트 결과를 데이터베이스에 저장
- `classify_final_decision()` - 최종 의사결정 분류 (승인/보류)

### agent1_bp_scouter.py
**목적**: RAG에서 Best Practice 사례 검색 및 조회

**입력**:
- 도메인 및 사업부 정보
- 제안서 내용 (RAG 검색 쿼리에 활용)
- RAG 검색 함수

**출력**:
- BP 사례 리스트 (title, tech_type, business_domain 등)

**특징**:
- RAG 시스템과 통합
- RAG 실패 시 시뮬레이션 데이터로 폴백
- WebSocket 진행 상황 업데이트

### agent2_objective_reviewer.py
**목적**: 제안서 목표와 전략 정렬성 검토

**입력**:
- 제안서 내용
- HITL 설정
- BP 사례 (참고용)

**출력**:
- 목표 검토 텍스트 (목표 적합성 평가)

**특징**:
- LLM 기반 품질 평가
- HITL 피드백 루프 및 재시도 메커니즘 (최대 3회)
- 평가 항목: 목표 명확성, 전략 정렬성, 실현 가능성
- 에이전트 특화 피드백 예시 제공 (목표, KPI, 측정 방법 등)

### agent3_data_analyzer.py
**목적**: 데이터 가용성 및 품질 분석

**입력**:
- 제안서 내용
- HITL 설정

**출력**:
- 데이터 분석 텍스트 (데이터 분석 결과)

**특징**:
- HITL 피드백 루프 및 품질 검사
- 평가 항목: 데이터 확보 가능성, 품질 예상, 접근성
- 에이전트 특화 피드백 예시 제공 (데이터 규모, 소스, 품질 관리, 보안 등)

### agent4_risk_analyzer.py
**목적**: 기술적, 일정, 인력 리스크 식별

**입력**:
- 제안서 내용
- HITL 설정

**출력**:
- 리스크 분석 텍스트 (리스크 분석 결과)

**특징**:
- HITL 피드백 루프
- 평가 항목: 기술적 리스크, 일정 리스크, 인력 리스크
- 에이전트 특화 피드백 예시 제공 (리스크 완화 방안, 대응 계획 등)

### agent5_roi_estimator.py
**목적**: 투자 대비 효과(ROI) 추정

**입력**:
- 제안서 내용
- HITL 설정

**출력**:
- ROI 추정 텍스트 (ROI 추정 결과)

**특징**:
- HITL 피드백 루프
- 평가 항목: 예상 효과, 투자 대비 효과
- 에이전트 특화 피드백 예시 제공 (투자 비용 상세, 기대 효과 산출, ROI 계산 등)

### agent6_final_generator.py
**목적**: 모든 분석 결과를 종합하여 최종 보고서 생성

**입력**:
- Agent 2-5의 결과
- Agent 1의 BP 사례
- HITL 설정

**출력**:
- 최종 HTML 보고서
- LLM 의사결정 (승인/보류)
- PDF 다운로드 버튼 포함
- Job 상태를 "completed"로 업데이트

**특징**:
- HITL 피드백 루프
- 아코디언 스타일 HTML 보고서 생성
- 자동 의사결정 분류
- WebSocket 최종 보고서 전송
- 에이전트 특화 피드백 예시 제공 (모든 영역을 포괄하는 통합 피드백)

### agent7_proposal_improver.py
**목적**: Agent 6의 피드백을 기반으로 제안서 개선안 생성

**입력**:
- 원본 제안서 내용
- Agent 6의 최종 보고서
- Agent 2-5의 분석 결과

**출력**:
- 개선된 제안서 HTML

**특징**:
- LLM 기반 제안서 개선안 생성
- 개선 전/후 비교 섹션 포함
- 개선 요약 제공

## 사용 예시

```python
from agents import (
    run_bp_scouter,
    run_objective_reviewer,
    run_data_analyzer,
    run_risk_analyzer,
    run_roi_estimator,
    run_final_generator,
    run_proposal_improver,
)

# process_review() 함수 내에서:

# Agent 1: BP 사례 검색
bp_cases = await run_bp_scouter(
    job_id, job, ws, domain, division,
    rag_retrieve_bp_cases, get_job, update_job_status
)

# Agent 2: 목표 검토
objective_review = await run_objective_reviewer(
    job_id, job, ws, hitl_stages, hitl_retry_counts,
    bp_cases, call_ollama, get_job, update_job_status, reset_feedback_state
)

# Agent 3: 데이터 분석
data_analysis = await run_data_analyzer(
    job_id, job, ws, hitl_stages, hitl_retry_counts,
    call_ollama, get_job, update_job_status, reset_feedback_state
)

# Agent 4: 리스크 분석
risk_analysis = await run_risk_analyzer(
    job_id, job, ws, hitl_stages, hitl_retry_counts,
    call_ollama, get_job, update_job_status, reset_feedback_state
)

# Agent 5: ROI 추정
roi_estimation = await run_roi_estimator(
    job_id, job, ws, hitl_stages, hitl_retry_counts,
    call_ollama, get_job, update_job_status, reset_feedback_state
)

# Agent 6: 최종 보고서 생성
await run_final_generator(
    job_id, job, ws, hitl_stages, hitl_retry_counts,
    objective_review, data_analysis, risk_analysis, roi_estimation,
    bp_cases, call_ollama, call_llm, get_job, update_job_status, reset_feedback_state,
    send_final_report=True, ws_key=ws_key, active_connections=active_connections
)

# Agent 7: 제안서 개선안 생성 (선택적)
if 7 in hitl_stages:
    await run_proposal_improver(
        job_id, job, ws, hitl_stages, hitl_retry_counts,
        final_report, objective_review, data_analysis, risk_analysis, roi_estimation,
        call_ollama, get_job, update_job_status, reset_feedback_state
    )
```

## 주요 기능

### Human-in-the-Loop (HITL)
- 각 에이전트(2-7)는 HITL 중단 지점 지원
- `hitl_stages` 리스트로 설정 가능 (예: [2, 3, 4, 5, 6, 7])
- 피드백 요청 전 품질 평가 수행
- 에이전트당 최대 3회 재시도
- 사용자는 건너뛰기 또는 피드백 제공 가능

### 품질 검사
- 각 에이전트 결과에 대한 LLM 기반 품질 평가
- 검사 항목: 상세도, 구체성, 완전성
- 품질이 불충분하면 자동 재시도
- 품질 검사 실패 시 휴리스틱으로 폴백

### 에이전트별 특화 피드백
- 각 에이전트(2-6)는 전문 분야에 맞는 피드백 예시 제공
- Agent 2: 목표, KPI, 측정 방법, 전략 연계
- Agent 3: 데이터 규모, 소스, 품질 관리, 보안
- Agent 4: 리스크 완화 방안, 대응 계획
- Agent 5: 투자 비용, 기대 효과, ROI 계산
- Agent 6: 종합 피드백 (모든 영역 포괄)
- []로 감싼 값만 수정하면 바로 사용 가능한 템플릿 형식

### WebSocket 통신
- 실시간 진행 상황 업데이트
- HITL 중단 알림
- 품질 검사 결과
- 피드백 제안

### 데이터베이스 통합
- 각 에이전트 후 메타데이터 저장
- Job 상태 업데이트
- Job 메타데이터에 에이전트 결과 저장
- 최종 보고서 및 의사결정 저장

## 의존성

각 에이전트가 필요로 하는 것:
- `call_ollama` 또는 `call_llm` - main.py의 LLM 함수
- `get_job`, `update_job_status`, `reset_feedback_state` - 데이터베이스 함수
- `rag_retrieve_bp_cases` - RAG 함수 (Agent 1만 해당)
- WebSocket 연결 (선택사항, UI 업데이트용)

## 통합 방법

`main.py`에 이 모듈들을 통합하는 자세한 단계는 **INTEGRATION_GUIDE.md**를 참고하세요.

## 장점

1. **모듈성**: 각 에이전트가 독립적이고 테스트 가능
2. **유지보수성**: 개별 에이전트 수정이 용이
3. **재사용성**: 공통 유틸리티가 한 곳에 집중
4. **확장성**: 새로운 에이전트 추가가 쉬움
5. **깨끗한 코드**: 관심사의 분리
6. **타입 안전성**: docstring이 포함된 명확한 함수 시그니처
7. **에이전트별 특화**: 각 에이전트의 전문 분야에 맞는 피드백 제공

## 참고 사항

- 모든 원래 기능이 보존됨
- 모든 프롬프트는 원본과 동일하게 유지됨
- HITL 로직이 각 에이전트에 완전히 구현됨
- WebSocket 통신이 투명하게 처리됨
- 에러 핸들링이 에이전트와 오케스트레이터 레벨 모두에서 유지됨
- Agent 2-6은 각각의 전문 분야에 맞는 구체적인 피드백 예시를 제공함
- 피드백 예시는 []로 감싼 값만 수정하면 바로 사용 가능한 템플릿 형식

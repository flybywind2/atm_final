# 에이전트 모듈 통합 가이드 (최신 버전)

이 문서는 `agents/` 디렉터리에 구현된 모듈형 에이전트들을 `main.py`에 연동하는 절차와
최신 동작 방식을 정리한 가이드입니다. 현재 코드베이스는 에이전트별 모듈을 활용하도록
구조화되어 있으며, LLM이 자동으로 제목과 승인/보류 판단을 생성하고, 각 에이전트의
산출물을 데이터베이스 및 대시보드에 기록하도록 확장되어 있습니다.

## 1. 에이전트 파일 구성

```
agents/
├── __init__.py                    # 모듈 export
├── utils.py                       # 공통 유틸리티 (JSON 추출, HITL 유틸 등)
├── agent1_bp_scouter.py           # BP Case Scouter
├── agent2_objective_reviewer.py   # Objective Reviewer
├── agent3_data_analyzer.py        # Data Analyzer
├── agent4_risk_analyzer.py        # Risk Analyzer
├── agent5_roi_estimator.py        # ROI Estimator
├── agent6_final_generator.py      # Final Generator
├── agent7_proposal_improver.py    # Proposal Improver (선택형 개선안)
└── INTEGRATION_GUIDE.md           # 본 가이드
```

### 새롭게 반영된 핵심 기능
- **LLM 자동 제목 생성**: 새 작업 등록 시 `generate_job_title()`이 호출되어 25자 이하의 제목이 자동 작성됩니다.
- **자동/최종 승인 분리**: `review_jobs` 테이블은 `decision`(사람 결정)과 `llm_decision`(자동 판정)을 별도 컬럼으로 유지합니다.
- **에이전트 결과 저장**: 각 에이전트가 생성한 텍스트는 `metadata.agent_results`에 누적되어 대시보드에서 확인할 수 있습니다.
- **최종 판정 근거 기록**: `metadata.final_decision`에 LLM 판정 및 근거가 JSON으로 저장되며, WebSocket과 대시보드에 함께 제공됩니다.

## 2. `main.py`에서 필요한 준비

### 2.1 모듈 import
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
from agents.utils import generate_job_title, classify_final_decision, persist_job_metadata
```
> 기존 `main.py`에는 이미 `generate_job_title`, `classify_final_decision`, `persist_job_metadata`
> 가 정의되어 있다면 중복을 피하고 모듈 버전으로 교체합니다.

### 2.2 주요 유틸리티 설명
- `generate_job_title(content, fallback)` : 제안서 전문을 요약해 LLM 기반 제목 생성.
- `persist_job_metadata(job_id, status, agent_updates=..., extra_updates=..., **kwargs)` :
  에이전트 결과를 `metadata.agent_results`에 병합하고 상태/결정을 원자적으로 업데이트.
- `classify_final_decision(report, recommendation)` : 최종 보고서를 기반으로 LLM이 승인/보류 판정 및 근거 생성.

## 3. `process_review()` 통합 예시

```python
async def process_review(job_id: int, ws_job_key: str | None = None, send_final_report: bool = True):
    job = get_job(job_id)
    ws = await acquire_websocket(ws_job_key or str(job_id))
    hitl_stages = job.get("hitl_stages", [])
    hitl_retry_counts = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0}

    # 1) BP 사례 탐색
    bp_cases = await run_bp_scouter(
        job_id, job, ws, job.get("domain", ""), job.get("division", ""),
        rag_retrieve_bp_cases, get_job, lambda *args, **kwargs: persist_job_metadata(job_id, *args, **kwargs)
    )

    # 2) 목표 적합성 검토
    objective_review = await run_objective_reviewer(
        job_id, job, ws, hitl_stages, hitl_retry_counts,
        bp_cases, call_ollama, get_job, persist_job_metadata, reset_feedback_state
    )

    # 3) 데이터 분석
    data_analysis = await run_data_analyzer(
        job_id, job, ws, hitl_stages, hitl_retry_counts,
        call_ollama, get_job, persist_job_metadata, reset_feedback_state
    )

    # 4) 리스크 분석
    risk_analysis = await run_risk_analyzer(
        job_id, job, ws, hitl_stages, hitl_retry_counts,
        call_ollama, get_job, persist_job_metadata, reset_feedback_state
    )

    # 5) ROI 추정
    roi_estimation = await run_roi_estimator(
        job_id, job, ws, hitl_stages, hitl_retry_counts,
        call_ollama, get_job, persist_job_metadata, reset_feedback_state
    )

    # 6) 최종 보고서 및 자동 판정
    await run_final_generator(
        job_id, job, ws, hitl_stages, hitl_retry_counts,
        objective_review, data_analysis, risk_analysis, roi_estimation,
        bp_cases, call_ollama, call_llm, get_job, persist_job_metadata, reset_feedback_state,
        classify_final_decision=classify_final_decision,
        send_final_report=send_final_report,
        ws_key=ws_job_key or str(job_id),
        active_connections=active_connections,
    )

    # 7) (선택) 제안서 개선안
    if 7 in hitl_stages:
        await run_proposal_improver(
            job_id, job, ws, hitl_stages, hitl_retry_counts,
            call_ollama, get_job, persist_job_metadata, reset_feedback_state
        )
```

> 각 에이전트 함수는 `persist_job_metadata`를 통해 자신이 만든 텍스트를
> `metadata.agent_results`에 저장하고, 상태 레이블(예: `"objective_done"`)도 함께 갱신합니다.

## 4. 데이터베이스 및 대시보드 동작
- `review_jobs` 테이블 구조는 `decision`(사람), `llm_decision`(자동) 컬럼을 모두 사용합니다.
- `persist_job_metadata`는 다음 정보를 자동으로 병합합니다:
  - `metadata.agent_results.bp_scouter` 등 에이전트별 결과
  - `metadata.final_decision` : `{"decision": "승인", "reason": "..."}`
  - 최종 보고서는 `metadata.report` 필드에 저장
- `/dashboard`에서
  - 목록 테이블: LLM 결정/사람 결정이 별도 칼럼에 표시
  - 모달 상세창: 에이전트 결과, LLM 근거, HITL 단계, 원문 등 모두 확인 가능
  - “승인/보류로 표시” 버튼은 사람 결정(`decision`)을 업데이트하며 자동 결정을 덮어쓰지 않음

## 5. 통합 시 제거할 구 코드
아래 로직은 모듈화 이후 `agents/`가 담당하므로 `main.py`에서 제거 가능합니다.
- 기존 에이전트 구현(약 900줄) 및 HITL 루프 중복 코드
- 결과 JSON 추출/품질 평가/HITL 보조 함수 중 `agents.utils`로 이동한 부분

## 6. 모듈 사용 시 주의사항
1. **LLM 호출**: 모듈은 `call_llm`, `call_ollama`를 주입받습니다. API 키나 모델 변경 시 `config.settings`를 조정하세요.
2. **HITL 설정**: 클라이언트 요청에서 `hitl_stages` 리스트를 전달하면 각 에이전트가 중간에 사용자 피드백을 기다립니다.
3. **WebSocket**: 에이전트는 필요한 경우 `ws.send_json()`으로 진행 상황을 알립니다. WebSocket이 없으면 `None`으로 호출해도 안전하게 동작합니다.
4. **병렬 처리**: 현재 파이프라인은 순차 실행을 전제로 합니다. 병렬화가 필요하면 각 모듈 파라미터를 조정하고 메타데이터 병합 방식(`persist_job_metadata`)을 주의하세요.
5. **에러 처리**: 에이전트 내부에서 발생하는 예외는 상위 `process_review()`에서 잡혀 로그 및 상태 업데이트로 이어집니다.

## 7. 요약
- 에이전트 모듈은 LLM 기반 검토 파이프라인을 기능별로 분리하여 유지보수가 쉽습니다.
- LLM이 자동으로 **제목**과 **승인/보류 판정**을 생성하며, 사람 검토자는 대시보드에서 최종 결정을 따로 수정할 수 있습니다.
- 모든 에이전트 결과는 메타데이터에 기록되어 UI와 HITL 평가에 활용됩니다.
- 새로운 에이전트를 추가하려면 `agents/agentX_*.py`에 구현 후 `__init__.py`와 `process_review()`에서 불러오면 됩니다.

필요 시 `agents/utils.py`의 공통 함수와 이 가이드를 참고하여 새로운 기능을 안전하게 확장하세요.

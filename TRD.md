## 1. 문서 개요

본 문서는 **AI Proposal Reviewer** 시스템의 기술적 아키텍처, 구성 요소, 데이터 흐름, 인터페이스, 보안 및 운영 요구사항을 명세화한다.  
시스템은 **다중 LLM 기반 에이전트 오케스트레이션** 구조를 채택하며, **RAG**(Retrieval-Augmented Generation) 기반 BP(Best Practice) 사례 활용과 **Human-in-the-Loop**(HITL) 프로세스를 핵심으로 한다.

---

## 2. 시스템 아키텍처

### 2.1 전체 아키텍처 다이어그램 (개념적)

```
[사용자 입력]  
      ↓  
[API Gateway]  
      ↓  
[Review Orchestrator Agent] ←→ [HITL Interface]  
      ↓  
[RAG Engine] ←→ [Vector DB + BP Case DB]
      ↓  
┌───────────────────────────────────────┐  
│           Agent Pool (병렬 실행 가능)   │  
├───────────────────┬───────────────────┤  
│ BP Case Scouter   │ Objective Reviewer│  
│ Data & Constraint │ Risk Analyzer     │  
│ ROI & Roadmap     │ ...               │  
└───────────────────┴───────────────────┘  
      ↓  
[RAG Engine] ←→ [Vector DB + BP Case DB]  
      ↓  
[PDF Generator] → [최종 출력: PDF]  
```

### 2.2 아키텍처 스타일
- **패턴**: Centralized Orchestration with Agent Pool
- **통신**: 동기/비동기 혼합 (Orchestrator → Agent: 비동기 병렬 호출)
- **상태 관리**: LangGraph 기반 State Machine (HITL 인터럽트 지원)
- **확장성**: 에이전트는 독립 모듈로 설계 → 동적 로딩/언로딩 가능

---

## 3. 주요 구성 요소 명세

### 3.1 에이전트 정의

| 에이전트 ID | 이름 | 책임 | 입력 | 출력 | 실행 조건 |
|------------|------|------|------|------|----------|
| AGT-01 | BP Case Scouter | 성공/실패 BP 사례 검색 | 지원서 텍스트 | JSON: `[{title, background, data, results, risks, roi, url}]` | 항상 최초 실행 |
| AGT-02 | Objective & Impact Reviewer | 목표/기대 효과 정량화 평가 | 지원서 + BP 사례 | Markdown: 수정 제안 + 예시 | AGT-01 완료 후 |
| AGT-03 | Data & Constraint Analyzer | 데이터/I/O/제약 진단 | 지원서 + BP 사례 | JSON: `{data_status, issues, recommendations}` | AGT-01 완료 후 |
| AGT-04 | Risk & Failure Analyzer | 리스크 예측 및 완화 전략 | 지원서 + 실패 사례 | Markdown: 리스크 목록 + 대응 방안 | 선택적 (고도화 모드) |
| AGT-05 | ROI & Roadmap Estimator | ROI 산정 + 3단계 로드맵 | 지원서 + BP 사례 | JSON: `{initial_cost, annual_benefit, payback_period, roadmap}` | 선택적 (고도화 모드) |
| AGT-99 | Final Review & PDF Generator | 종합, HITL 조율, PDF 생성 | 모든 에이전트 출력 | PDF 바이트 스트림 + HITL 요청 플래그 | 모든 에이전트 완료 후 |

> **공통 프롬프트 구조**:  
> ```text
> 당신은 [에이전트 이름]입니다. 다음 BP 사례와 사용자 입력을 바탕으로 사실 기반(fact-based)으로 응답하세요.
> BP 사례: {{retrieved_cases}}
> 사용자 입력: {{user_proposal}}
> ```

### 3.2 BP 사례 데이터베이스

| 필드 | 타입 | 설명 | 필수 여부 |
|------|------|------|----------|
| `doc_id` | string | 고유 ID (e.g., BP-MFG-001) | ✅ |
| `title` | string | 사례 제목 | ✅ |
| `category` | string | 도메인 분류 | ✅ |
| `background` | string | 도입 배경 및 목표 | ✅ |
| `data_status` | object | `{type, volume, labeling_status}` | ✅ |
| `results` | object | `{quantitative_impact, qualitative_impact}` | ✅ |
| `constraints` | array | `[“5분 내 처리”, “On-prem only”]` | ✅ |
| `url` | string | 출처 링크 | ✅ |

- **저장소**: RAGaaS
- **업데이트 주기**: 수동 (주 1회) + 자동 (외부 API 연동 시)

---

## 4. 데이터 흐름

### 4.1 주요 워크플로우 (LangGraph 기반)

```python
# 상태 정의
State = {
    "user_proposal": str,
    "bp_cases": list,
    "agent_outputs": dict,
    "hitl_feedback": dict,
    "final_pdf": bytes
}

# 노드 정의
def bp_scouter_node(state):
    cases = rag_search(state["user_proposal"])
    return {"bp_cases": cases}

def objective_reviewer_node(state):
    output = llm_generate(prompt_template.format(...))
    return {"agent_outputs": {"objective": output}}

# HITL 인터럽트
workflow.add_node("final_review", final_review_node)
workflow.add_edge("all_agents_done", "final_review")
workflow.add_conditional_edges(
    "final_review",
    lambda state: "await_hitl" if needs_human_review(state) else "generate_pdf",
    {"await_hitl": "human_feedback", "generate_pdf": END}
)
```

### 4.2 HITL 인터페이스

- **프로토콜**: HTTP REST API + WebSocket (실시간 피드백)
- **요청 형식**:
  ```json
  {
    "agent_id": "AGT-02",
    "original_proposal": "비용 절감",
    "suggested_revision": "연간 1.2억 원 비용 절감",
    "example_from_bp": "BP 사례 #3: 연간 1.2억 원 절감"
  }
  ```
- **응답 형식**:
  ```json
  {
    "is_correct": false,
    "corrected_value": "연간 8천만 원 비용 절감",
    "comment": "실제 예산 규모를 반영함"
  }
  ```

---

## 5. 기술 스택

| 계층 | 기술 |
|------|------|
| **오케스트레이션** | LangGraph (Stateful Workflow) |
| **LLM** | gpt-oss (대규모 모델) |
| **RAG 프레임워크** | RAGaaS |
| **평가** | RAGAS (Faithfulness, Answer Relevancy), Langfuse (Observability) |
| **PDF 생성** | WeasyPrint (Python) |
---

## 6. 보안 및 컴플라이언스

추후 별도 구현 예정

---

## 7. 성능 및 확장성

| 지표 | 목표 |
|------|------|
| **평균 응답 시간** | ≤ 300초 (HITL 제외) |
| **병렬 에이전트 실행** | 최대 6개 동시 실행 |
| **LLM 요청 지연** | P95 ≤ 8초 |
| **RAG 검색 지연** | P95 ≤ 2초 |
| **확장성** | 에이전트 수 증가 시 수평 확장 (K8s HPA) |

---

## 8. 운영 및 모니터링

- **헬스 체크**: `/health` 엔드포인트 (LLM, Vector DB, PDF Generator 상태)

---

## 9. 테스트 전략

| 테스트 유형 | 방법 | 도구 |
|------------|------|------|
| **유닛 테스트** | 각 에이전트 함수별 테스트 | pytest |
| **통합 테스트** | 전체 워크플로우 실행 (Mock LLM) | LangGraph Test Harness |
| **RAG 평가** | Faithfulness, Context Recall | RAGAS |
| **HITL 시나리오 테스트** | 피드백 반영 → 재생성 검증 | Playwright (E2E) |
| **성능 테스트** | 동시 사용자 50명 부하 테스트 | Locust |

---

## 10. 의존성 및 외부 인터페이스

| 의존성 | 유형 | 설명 |
|--------|------|------|
| **LLM Provider** | 외부 API | appendix/internal_llm.py 참조 |
| **PDF Generator** | 오픈소스 라이브러리 | WeasyPrint (MIT) |
| **평가 도구** | 오픈소스 | RAGAS, Langfuse |

---
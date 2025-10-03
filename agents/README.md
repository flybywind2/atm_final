# Agent Modules

This directory contains modularized agent implementations for the AI Proposal Reviewer system.

## File Structure

```
agents/
├── __init__.py                    # Module exports (17 lines)
├── utils.py                       # Shared utility functions (210 lines)
├── agent1_bp_scouter.py          # BP Case Scouter (50 lines)
├── agent2_objective_reviewer.py  # Objective Reviewer (198 lines)
├── agent3_data_analyzer.py       # Data Analyzer (190 lines)
├── agent4_risk_analyzer.py       # Risk Analyzer (186 lines)
├── agent5_roi_estimator.py       # ROI Estimator (184 lines)
├── agent6_final_generator.py     # Final Generator (315 lines)
├── INTEGRATION_GUIDE.md          # How to integrate into main.py
└── README.md                      # This file
```

**Total: 1,561 lines** (modularized from ~900 lines in main.py)

## Module Descriptions

### utils.py
Shared utility functions used by all agents:
- `_extract_json_dict()` - Extract JSON from LLM responses
- `_truncate_for_prompt()` - Truncate text for prompts
- `analyze_result_quality()` - Quality check for agent results
- `generate_feedback_suggestion()` - Generate feedback for HITL
- `wait_for_feedback()` - Wait for user feedback in HITL loops
- `persist_job_metadata()` - Save agent results to database
- `classify_final_decision()` - Classify final decision (승인/보류)

### agent1_bp_scouter.py
**Purpose**: Search and retrieve Best Practice cases from RAG

**Input**:
- Domain and division information
- RAG retrieval function

**Output**:
- List of BP cases (dict with title, tech_type, business_domain, etc.)

**Features**:
- Integrates with RAG system
- Fallback to simulation data if RAG fails
- WebSocket progress updates

### agent2_objective_reviewer.py
**Purpose**: Review proposal objectives and strategic alignment

**Input**:
- Proposal content
- HITL configuration

**Output**:
- Objective review text (목표 적합성 평가)

**Features**:
- LLM-based quality assessment
- HITL feedback loop with retry mechanism (max 3 retries)
- Evaluates: 목표 명확성, 전략 정렬성, 실현 가능성

### agent3_data_analyzer.py
**Purpose**: Analyze data availability and quality

**Input**:
- Proposal content
- HITL configuration

**Output**:
- Data analysis text (데이터 분석 결과)

**Features**:
- HITL feedback loop with quality checks
- Evaluates: 데이터 확보 가능성, 품질 예상, 접근성

### agent4_risk_analyzer.py
**Purpose**: Identify technical, schedule, and personnel risks

**Input**:
- Proposal content
- HITL configuration

**Output**:
- Risk analysis text (리스크 분석 결과)

**Features**:
- HITL feedback loop
- Evaluates: 기술적 리스크, 일정 리스크, 인력 리스크

### agent5_roi_estimator.py
**Purpose**: Estimate return on investment and benefits

**Input**:
- Proposal content
- HITL configuration

**Output**:
- ROI estimation text (ROI 추정 결과)

**Features**:
- HITL feedback loop
- Evaluates: 예상 효과, 투자 대비 효과

### agent6_final_generator.py
**Purpose**: Synthesize all analyses into final recommendation

**Input**:
- Results from agents 2-5
- BP cases from agent 1
- HITL configuration

**Output**:
- Final HTML report
- LLM decision (승인/보류)
- Updates job status to "completed"

**Features**:
- HITL feedback loop
- Generates accordion-style HTML report
- Automatic decision classification
- WebSocket final report delivery

## Usage Example

```python
from agents import (
    run_bp_scouter,
    run_objective_reviewer,
    run_data_analyzer,
    run_risk_analyzer,
    run_roi_estimator,
    run_final_generator,
)

# In your process_review() function:

# Agent 1: Search BP cases
bp_cases = await run_bp_scouter(
    job_id, job, ws, domain, division,
    rag_retrieve_bp_cases, get_job, update_job_status
)

# Agent 2: Review objectives
objective_review = await run_objective_reviewer(
    job_id, job, ws, hitl_stages, hitl_retry_counts,
    bp_cases, call_ollama, get_job, update_job_status, reset_feedback_state
)

# Agent 3: Analyze data
data_analysis = await run_data_analyzer(
    job_id, job, ws, hitl_stages, hitl_retry_counts,
    call_ollama, get_job, update_job_status, reset_feedback_state
)

# Agent 4: Analyze risks
risk_analysis = await run_risk_analyzer(
    job_id, job, ws, hitl_stages, hitl_retry_counts,
    call_ollama, get_job, update_job_status, reset_feedback_state
)

# Agent 5: Estimate ROI
roi_estimation = await run_roi_estimator(
    job_id, job, ws, hitl_stages, hitl_retry_counts,
    call_ollama, get_job, update_job_status, reset_feedback_state
)

# Agent 6: Generate final report
await run_final_generator(
    job_id, job, ws, hitl_stages, hitl_retry_counts,
    objective_review, data_analysis, risk_analysis, roi_estimation,
    bp_cases, call_ollama, call_llm, get_job, update_job_status, reset_feedback_state,
    send_final_report=True, ws_key=ws_key, active_connections=active_connections
)
```

## Key Features

### Human-in-the-Loop (HITL)
- Each agent (2-6) supports HITL interrupts
- Configurable via `hitl_stages` list (e.g., [2, 3, 4, 5, 6])
- Quality assessment before requesting feedback
- Maximum 3 retries per agent
- User can skip or provide feedback

### Quality Checks
- LLM-based quality assessment for each agent result
- Checks for: detail level, specificity, completeness
- Automatic retry if quality is insufficient
- Fallback to heuristics if quality check fails

### WebSocket Communication
- Real-time progress updates
- HITL interrupt notifications
- Quality check results
- Feedback suggestions

### Database Integration
- Metadata persistence after each agent
- Job status updates
- Agent results stored in job metadata
- Final report and decision saved

## Dependencies

Each agent requires:
- `call_ollama` or `call_llm` - LLM function from main.py
- `get_job`, `update_job_status`, `reset_feedback_state` - Database functions
- `rag_retrieve_bp_cases` - RAG function (Agent 1 only)
- WebSocket connection (optional, for UI updates)

## Integration

See **INTEGRATION_GUIDE.md** for detailed steps on integrating these modules into `main.py`.

## Benefits

1. **Modularity**: Each agent is independent and testable
2. **Maintainability**: Easy to modify individual agents
3. **Reusability**: Shared utilities in one place
4. **Scalability**: Easy to add new agents
5. **Clean Code**: Separation of concerns
6. **Type Safety**: Clear function signatures with docstrings

## Notes

- All original functionality is preserved
- All prompts remain identical to the original
- HITL logic is fully implemented in each agent
- WebSocket communication is handled transparently
- Error handling is maintained at both agent and orchestrator level

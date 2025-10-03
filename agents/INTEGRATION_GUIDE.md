# Agent Module Integration Guide

This guide shows how to integrate the newly created agent modules into `main.py`.

## Files Created

1. **agents/utils.py** - Shared utility functions
2. **agents/agent1_bp_scouter.py** - BP Case Scouter
3. **agents/agent2_objective_reviewer.py** - Objective Reviewer
4. **agents/agent3_data_analyzer.py** - Data Analyzer
5. **agents/agent4_risk_analyzer.py** - Risk Analyzer
6. **agents/agent5_roi_estimator.py** - ROI Estimator
7. **agents/agent6_final_generator.py** - Final Generator
8. **agents/__init__.py** - Module exports

## Integration Steps

### 1. Add Import to main.py

Replace the old agent code sections (lines 694-1603) with imports at the top of main.py:

```python
# Add to imports section (around line 32)
from agents import (
    run_bp_scouter,
    run_objective_reviewer,
    run_data_analyzer,
    run_risk_analyzer,
    run_roi_estimator,
    run_final_generator,
)
```

### 2. Update process_review() function

Replace the agent execution sections in `process_review()` with the following:

```python
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
        bp_cases = await run_bp_scouter(
            job_id, job, ws, domain, division,
            rag_retrieve_bp_cases, get_job, update_job_status
        )

        # Agent 2: Objective Reviewer
        objective_review = await run_objective_reviewer(
            job_id, job, ws, hitl_stages, hitl_retry_counts,
            bp_cases, call_ollama, get_job, update_job_status, reset_feedback_state
        )

        # Agent 3: Data Analyzer
        data_analysis = await run_data_analyzer(
            job_id, job, ws, hitl_stages, hitl_retry_counts,
            call_ollama, get_job, update_job_status, reset_feedback_state
        )

        # Agent 4: Risk Analyzer
        risk_analysis = await run_risk_analyzer(
            job_id, job, ws, hitl_stages, hitl_retry_counts,
            call_ollama, get_job, update_job_status, reset_feedback_state
        )

        # Agent 5: ROI Estimator
        roi_estimation = await run_roi_estimator(
            job_id, job, ws, hitl_stages, hitl_retry_counts,
            call_ollama, get_job, update_job_status, reset_feedback_state
        )

        # Agent 6: Final Generator
        await run_final_generator(
            job_id, job, ws, hitl_stages, hitl_retry_counts,
            objective_review, data_analysis, risk_analysis, roi_estimation,
            bp_cases, call_ollama, call_llm, get_job, update_job_status, reset_feedback_state,
            send_final_report=send_final_report, ws_key=ws_key, active_connections=active_connections
        )

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
```

### 3. Remove Old Code from main.py

After integrating the new agent modules, you can **safely remove** the following sections from main.py:

- Lines 80-108: Helper functions (_extract_json_dict, _truncate_for_prompt)
- Lines 140-165: Decision classification functions
- Lines 168-179: persist_job_metadata function
- Lines 384-491: Quality analysis and feedback functions
- Lines 544-557: wait_for_feedback function
- Lines 694-1603: All 6 agent implementations

These have all been moved to the agent modules.

### 4. Keep in main.py

The following functions should **remain in main.py** as they are used by multiple parts of the application:

- `call_llm()` - LLM calling function (line 301-318)
- `call_ollama()` - Ollama wrapper (line 320-322)
- `rag_retrieve_bp_cases()` - RAG retrieval (line 493-542)
- `generate_job_title()` - Title generation (line 136-137)

## Function Signatures

Each agent function has a clear signature:

### Agent 1: BP Scouter
```python
async def run_bp_scouter(job_id, job, ws, domain, division,
                         rag_retrieve_bp_cases, get_job, update_job_status)
    -> list[dict]  # Returns BP cases
```

### Agent 2: Objective Reviewer
```python
async def run_objective_reviewer(job_id, job, ws, hitl_stages, hitl_retry_counts,
                                  bp_cases, call_ollama, get_job, update_job_status, reset_feedback_state)
    -> str  # Returns objective review text
```

### Agent 3: Data Analyzer
```python
async def run_data_analyzer(job_id, job, ws, hitl_stages, hitl_retry_counts,
                             call_ollama, get_job, update_job_status, reset_feedback_state)
    -> str  # Returns data analysis text
```

### Agent 4: Risk Analyzer
```python
async def run_risk_analyzer(job_id, job, ws, hitl_stages, hitl_retry_counts,
                             call_ollama, get_job, update_job_status, reset_feedback_state)
    -> str  # Returns risk analysis text
```

### Agent 5: ROI Estimator
```python
async def run_roi_estimator(job_id, job, ws, hitl_stages, hitl_retry_counts,
                             call_ollama, get_job, update_job_status, reset_feedback_state)
    -> str  # Returns ROI estimation text
```

### Agent 6: Final Generator
```python
async def run_final_generator(job_id, job, ws, hitl_stages, hitl_retry_counts,
                               objective_review, data_analysis, risk_analysis, roi_estimation,
                               bp_cases, call_ollama, call_llm, get_job, update_job_status, reset_feedback_state,
                               send_final_report=True, ws_key=None, active_connections=None)
    -> None  # Updates job with final report
```

## Benefits of This Structure

1. **Modularity**: Each agent is in its own file, making it easier to maintain and test
2. **Reusability**: Shared utilities are in one place (utils.py)
3. **Clear Dependencies**: Each agent function explicitly lists its dependencies as parameters
4. **Easier Testing**: Each agent can be tested independently
5. **Better Organization**: Code is organized by functionality, not mixed in one large file
6. **Scalability**: Easy to add new agents or modify existing ones

## Notes

- All HITL logic, quality checks, and retry mechanisms are preserved in each agent module
- All prompts remain exactly as they were in the original code
- WebSocket communication is handled by each agent independently
- Database operations are passed as function parameters for flexibility
- The integration maintains backward compatibility with the existing system

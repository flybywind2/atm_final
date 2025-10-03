# agents/agent4_risk_analyzer.py - Risk Analyzer Agent

import asyncio
from .utils import (
    persist_job_metadata,
    analyze_result_quality,
    generate_feedback_suggestion,
    wait_for_feedback
)


async def run_risk_analyzer(job_id: int, job: dict, ws, hitl_stages: list, hitl_retry_counts: dict,
                             call_ollama, get_job, update_job_status, reset_feedback_state):
    """Risk Analyzer - Identify technical, schedule, and personnel risks

    Args:
        job_id: Job ID
        job: Job data dictionary
        ws: WebSocket connection
        hitl_stages: HITL stage configuration
        hitl_retry_counts: HITL retry counter dictionary
        call_ollama: LLM call function
        get_job: Database get_job function
        update_job_status: Database update_job_status function
        reset_feedback_state: Database reset_feedback_state function

    Returns:
        str: Risk analysis text
    """
    MAX_HITL_RETRIES = 3

    if ws:
        await ws.send_json({"status": "processing", "agent": "Risk_Analyzer", "message": "리스크 분석 중..."})

    proposal_text = job.get("content", "")
    enable_seq_thinking = job.get("enable_sequential_thinking", False)

    if enable_seq_thinking:
        print(f"[Agent 4] Sequential Thinking 활성화됨")

    risk_prompt = f"""당신은 AI 프로젝트의 리스크 분석 전문가입니다.
다음 제안서에 대한 리스크 분석을 수행해주세요:

제안서 내용:
{proposal_text}

다음 리스크를 평가하고 각각 짧게 요약해주세요:
1. 기술적 리스크
2. 일정 리스크
3. 인력 리스크

각 항목마다 1-2문장으로 평가 결과를 작성해주세요."""

    risk_analysis = await asyncio.to_thread(call_ollama, risk_prompt, enable_sequential_thinking=enable_seq_thinking)

    if ws:
        await ws.send_json({"status": "completed", "agent": "Risk_Analyzer", "message": "리스크 분석 완료"})

    persist_job_metadata(
        job_id,
        "risk_done",
        get_job,
        update_job_status,
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
                proposal_text,
                call_ollama
            )
            print(f"[DEBUG] Quality check for Agent 4: {quality_check}")

            feedback_suggestion = await asyncio.to_thread(
                generate_feedback_suggestion,
                "Risk Analyzer",
                risk_analysis,
                proposal_text,
                call_ollama
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
            await wait_for_feedback(job_id, update_job_status, get_job)

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
                # 사용자 피드백이 있으면 재분석 필요
                retry_decision = {"needs_retry": True, "reason": "사용자 피드백 반영", "user_feedback": user_feedback}
                # 사용자 피드백을 DB에 저장 (Agent 7에서 사용)
                job_data = get_job(job_id)
                if job_data:
                    metadata = job_data.get("metadata", {}).copy()
                    user_feedbacks_dict = metadata.get("user_feedbacks", {})
                    user_feedbacks_dict[agent_num] = user_feedback
                    metadata["user_feedbacks"] = user_feedbacks_dict
                    update_job_status(job_id, job_data.get("status"), metadata=metadata)
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

                # 사용자 피드백이 있으면 프롬프트를 완전히 다르게 구성
                if retry_decision.get("user_feedback"):
                    retry_prompt = f"""당신은 AI 프로젝트의 리스크 분석 전문가입니다.
사용자가 중요한 피드백을 제공했습니다. 이 피드백을 **반드시 반영**하여 리스크 분석을 다시 수행해주세요.

제안서 내용:
{proposal_text}

이전 분석 결과:
{risk_analysis}

**사용자 피드백 (필수 반영):**
{retry_decision.get('user_feedback')}

**중요:** 위 사용자 피드백의 내용을 리스크 분석에 **구체적으로 반영**해주세요.
사용자가 제공한 정보(예: 기술 역량, 일정, 예산 제약 등)를 명시적으로 언급하고,
이를 바탕으로 다음 리스크를 재평가해주세요:

1. 기술적 리스크 (사용자 피드백의 정보를 포함하여 평가)
2. 일정 리스크 (사용자 피드백을 고려한 평가)
3. 인력 리스크 (사용자가 제공한 구체적인 정보를 바탕으로 평가)

**반드시 사용자 피드백의 내용을 분석 결과에 직접 언급하면서 5-7문장 이상으로 작성해주세요.**"""
                else:
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

                risk_analysis = await asyncio.to_thread(call_ollama, retry_prompt, enable_sequential_thinking=enable_seq_thinking)

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

    return risk_analysis

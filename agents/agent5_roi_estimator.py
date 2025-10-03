# agents/agent5_roi_estimator.py - ROI Estimator Agent

import asyncio
from .utils import (
    persist_job_metadata,
    analyze_result_quality,
    generate_feedback_suggestion,
    wait_for_feedback
)


async def run_roi_estimator(job_id: int, job: dict, ws, hitl_stages: list, hitl_retry_counts: dict,
                             call_ollama, get_job, update_job_status, reset_feedback_state):
    """ROI Estimator - Estimate return on investment and benefits

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
        str: ROI estimation text
    """
    MAX_HITL_RETRIES = 3

    if ws:
        await ws.send_json({"status": "processing", "agent": "ROI_Estimator", "message": "ROI 추정 중..."})

    proposal_text = job.get("content", "")
    enable_seq_thinking = job.get("enable_sequential_thinking", False)

    if enable_seq_thinking:
        print(f"[Agent 5] Sequential Thinking 활성화됨")

    roi_prompt = f"""당신은 AI 프로젝트의 ROI(투자 수익률) 분석 전문가입니다.
다음 제안서에 대한 ROI를 추정해주세요:

제안서 내용:
{proposal_text}

다음 항목을 평가하고 짧게 요약해주세요:
1. 예상 효과 (비용 절감, 생산성 향상 등)
2. 투자 대비 효과 (ROI 퍼센티지, 손익분기점)

간결하게 2-3문장으로 평가 결과를 작성해주세요."""

    roi_estimation = await asyncio.to_thread(call_ollama, roi_prompt, enable_sequential_thinking=enable_seq_thinking)

    if ws:
        await ws.send_json({"status": "completed", "agent": "ROI_Estimator", "message": "ROI 추정 완료"})

    persist_job_metadata(
        job_id,
        "roi_done",
        get_job,
        update_job_status,
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
                proposal_text,
                call_ollama
            )
            print(f"[DEBUG] Quality check for Agent 5: {quality_check}")

            feedback_suggestion = await asyncio.to_thread(
                generate_feedback_suggestion,
                "ROI Estimator",
                roi_estimation,
                proposal_text,
                call_ollama
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
            await wait_for_feedback(job_id, update_job_status, get_job)

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

                # 사용자 피드백이 있으면 프롬프트를 완전히 다르게 구성
                if retry_decision.get("user_feedback"):
                    retry_prompt = f"""당신은 AI 프로젝트의 ROI(투자 수익률) 분석 전문가입니다.
사용자가 중요한 피드백을 제공했습니다. 이 피드백을 **반드시 반영**하여 ROI 추정을 다시 수행해주세요.

제안서 내용:
{proposal_text}

이전 분석 결과:
{roi_estimation}

**사용자 피드백 (필수 반영):**
{retry_decision.get('user_feedback')}

**중요:** 위 사용자 피드백의 내용을 ROI 추정에 **구체적으로 반영**해주세요.
사용자가 제공한 정보(예: 예산, 기대 효과, 투자 기간 등)를 명시적으로 언급하고,
이를 바탕으로 다음 항목을 재평가해주세요:

1. 예상 효과 (사용자 피드백의 정보를 포함하여 구체적인 수치로 평가)
2. 투자 대비 효과 (사용자가 제공한 예산 정보를 바탕으로 ROI 계산)

**반드시 사용자 피드백의 내용(특히 예산, 투자액 등)을 ROI 계산에 직접 사용하고,
이를 명시적으로 언급하면서 5-7문장 이상으로 작성해주세요.**"""
                else:
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

                roi_estimation = await asyncio.to_thread(call_ollama, retry_prompt, enable_sequential_thinking=enable_seq_thinking)

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

    return roi_estimation

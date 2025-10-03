# agents/agent2_objective_reviewer.py - Objective Reviewer Agent

import asyncio
from .utils import (
    persist_job_metadata,
    analyze_result_quality,
    generate_feedback_suggestion,
    wait_for_feedback
)


async def run_objective_reviewer(job_id: int, job: dict, ws, hitl_stages: list, hitl_retry_counts: dict,
                                  bp_cases: list, call_ollama, get_job, update_job_status, reset_feedback_state):
    """Objective Reviewer - Review proposal objectives and strategic alignment

    Args:
        job_id: Job ID
        job: Job data dictionary
        ws: WebSocket connection
        hitl_stages: HITL stage configuration
        hitl_retry_counts: HITL retry counter dictionary
        bp_cases: BP cases from Agent 1
        call_ollama: LLM call function
        get_job: Database get_job function
        update_job_status: Database update_job_status function
        reset_feedback_state: Database reset_feedback_state function

    Returns:
        str: Objective review text
    """
    MAX_HITL_RETRIES = 3

    if ws:
        await ws.send_json({"status": "processing", "agent": "Objective_Reviewer", "message": "목표 적합성 검토 중..."})

    proposal_text = job.get("content", "")
    enable_seq_thinking = job.get("enable_sequential_thinking", False)

    if enable_seq_thinking:
        print(f"[Agent 2] Sequential Thinking 활성화됨")

    objective_prompt = f"""당신은 기업의 AI 과제 제안서를 검토하는 전문가입니다.
다음 제안서의 목표 적합성을 검토하고 평가해주세요:

제안서 내용:
{proposal_text}

다음 항목을 평가하고 짧게 요약해주세요:
1. 목표의 명확성
2. 조직 전략과의 정렬성
3. 실현 가능성

간결하게 2-3문장으로 평가 결과를 작성해주세요."""

    objective_review = await asyncio.to_thread(call_ollama, objective_prompt, enable_sequential_thinking=enable_seq_thinking)

    if ws:
        await ws.send_json({"status": "completed", "agent": "Objective_Reviewer", "message": "목표 검토 완료"})

    persist_job_metadata(
        job_id,
        "objective_done",
        get_job,
        update_job_status,
        agent_updates={"objective_review": objective_review},
    )

    # HITL 인터럽트: Agent 2 이후 (설정에 따라)
    if 2 in hitl_stages:
        agent_num = 2
        skip_accepted_agent2 = False
        while True:
            # LLM이 분석 결과 품질 평가
            quality_check = await asyncio.to_thread(
                analyze_result_quality,
                "Objective Reviewer",
                objective_review,
                proposal_text,
                call_ollama
            )

            print(f"[DEBUG] Quality check for Agent 2: {quality_check}")

            # 피드백 제안 생성
            feedback_suggestion = await asyncio.to_thread(
                generate_feedback_suggestion,
                "Objective Reviewer",
                objective_review,
                proposal_text,
                call_ollama
            )

            if ws:
                await ws.send_json({
                    "status": "interrupt",
                    "job_id": job_id,
                    "message": f"검토 결과를 확인해주세요 (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}) - 품질: {quality_check.get('reason', '')}",
                    "results": {
                        "objective_review": objective_review,
                        "feedback_suggestion": feedback_suggestion,
                        "quality_check": quality_check
                    }
                })

            # 사용자가 결과를 확인할 때까지 대기
            await wait_for_feedback(job_id, update_job_status, get_job)

            # 사용자 피드백 가져오기
            updated_job = get_job(job_id)
            skip_requested = updated_job.get("feedback_skip", False)
            user_feedback = (updated_job.get("feedback") or "").strip()

            print(f"[DEBUG] User feedback retrieved: '{user_feedback}' (skip={skip_requested})")

            if skip_requested:
                skip_accepted_agent2 = True
                retry_decision = {"needs_retry": False, "reason": "사용자가 건너뛰기를 선택"}
                reset_feedback_state(job_id)
                print(f"[DEBUG] HITL skip acknowledged for Agent 2 (job {job_id})")
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
                # 피드백이 없으면 품질 검사 결과 사용
                retry_decision = quality_check

            print(f"[DEBUG] Retry decision for Agent 2: {retry_decision}")

            if skip_accepted_agent2:
                break

            # 재시도 필요 여부 판단
            if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                hitl_retry_counts[agent_num] += 1
                print(f"[DEBUG] Agent 2 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                if ws:
                    await ws.send_json({
                        "status": "processing",
                        "agent": "Objective_Reviewer",
                        "message": f"품질 개선을 위해 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                    })

                # 사용자 피드백이 있으면 프롬프트를 완전히 다르게 구성
                if retry_decision.get("user_feedback"):
                    retry_prompt = f"""당신은 기업의 AI 과제 제안서를 검토하는 전문가입니다.
사용자가 중요한 피드백을 제공했습니다. 이 피드백을 **반드시 반영**하여 검토 결과를 다시 작성해주세요.

제안서 내용:
{proposal_text}

이전 검토 결과:
{objective_review}

**사용자 피드백 (필수 반영):**
{retry_decision.get('user_feedback')}

**중요:** 위 사용자 피드백의 내용을 검토 결과에 **구체적으로 반영**해주세요.
사용자가 제공한 정보(예: 예산, 인력, 기간 등)를 명시적으로 언급하고,
이를 바탕으로 다음 항목을 재평가해주세요:

1. 목표의 명확성 (사용자 피드백의 정보를 포함하여 평가)
2. 조직 전략과의 정렬성 (사용자 피드백을 고려한 평가)
3. 실현 가능성 (사용자가 제공한 구체적인 정보를 바탕으로 평가)

**반드시 사용자 피드백의 내용을 검토 결과에 직접 언급하면서 5-7문장 이상으로 작성해주세요.**"""
                else:
                    # 품질 검사 결과를 반영하여 재검토
                    retry_prompt = f"""당신은 기업의 AI 과제 제안서를 검토하는 전문가입니다.
이전 검토 결과가 품질 기준을 충족하지 못했습니다. 더 상세하고 구체적으로 재검토해주세요.

제안서 내용:
{proposal_text}

이전 검토 결과 (불충분):
{objective_review}

품질 검사 결과:
- 문제점: {retry_decision.get('reason', '분석이 불충분함')}
- 보완 필요 사항: {', '.join(retry_decision.get('additional_info_needed', ['더 상세한 분석', '구체적인 근거', '명확한 판단']))}

위 문제점을 해결하고 다음 항목을 **구체적이고 상세하게** 재평가해주세요:
1. 목표의 명확성 (제안서에 명시된 구체적인 목표 인용)
2. 조직 전략과의 정렬성 (어떤 전략 목표와 어떻게 연결되는지)
3. 실현 가능성 (구체적인 가능/불가능 근거)

**반드시 5-7문장 이상으로 구체적인 근거와 함께 평가 결과를 작성해주세요.**
각 항목마다 명확한 판단과 그 이유를 제시하세요."""

                objective_review = await asyncio.to_thread(call_ollama, retry_prompt, enable_sequential_thinking=enable_seq_thinking)

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
            next_message = (
                "사용자 건너뛰기 요청을 수락했습니다. 다음 단계로 진행합니다."
                if skip_accepted_agent2
                else "피드백 반영하여 분석 계속 진행..."
            )
            await ws.send_json({
                "status": "processing",
                "agent": "Data_Analyzer",
                "message": next_message
            })
        await asyncio.sleep(1)

    return objective_review

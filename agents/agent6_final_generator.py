# agents/agent6_final_generator.py - Final Generator Agent

import asyncio
from .utils import (
    classify_final_decision,
    analyze_result_quality,
    generate_feedback_suggestion,
    wait_for_feedback
)


async def run_final_generator(job_id: int, job: dict, ws, hitl_stages: list, hitl_retry_counts: dict,
                               objective_review: str, data_analysis: str, risk_analysis: str, roi_estimation: str,
                               bp_cases: list, call_ollama, call_llm, get_job, update_job_status, reset_feedback_state,
                               send_final_report: bool = True, ws_key: str = None, active_connections: dict = None,
                               user_feedbacks: dict = None):
    """Final Generator - Synthesize all analyses into final recommendation

    Args:
        job_id: Job ID
        job: Job data dictionary
        ws: WebSocket connection
        hitl_stages: HITL stage configuration
        hitl_retry_counts: HITL retry counter dictionary
        objective_review: Result from Agent 2
        data_analysis: Result from Agent 3
        risk_analysis: Result from Agent 4
        roi_estimation: Result from Agent 5
        bp_cases: Result from Agent 1
        call_ollama: LLM call function (ollama)
        call_llm: LLM call function (unified)
        get_job: Database get_job function
        update_job_status: Database update_job_status function
        reset_feedback_state: Database reset_feedback_state function
        send_final_report: Whether to send final report to WebSocket
        ws_key: WebSocket key for active connections
        active_connections: Active WebSocket connections dictionary
        user_feedbacks: Dictionary of user feedbacks from agents 2-5

    Returns:
        None (updates job with final report and decision)
    """
    MAX_HITL_RETRIES = 3

    if ws:
        await ws.send_json({"status": "processing", "agent": "Final_Generator", "message": "최종 보고서 생성 중..."})

    proposal_text = job.get("content", "")
    enable_seq_thinking = job.get("enable_sequential_thinking", False)

    if enable_seq_thinking:
        print(f"[Agent 6] Sequential Thinking 활성화됨")

    # Agent 2~5의 사용자 피드백을 수집하여 프롬프트에 추가
    user_feedback_section = ""
    if user_feedbacks:
        feedback_list = []
        agent_names = {2: "목표 검토", 3: "데이터 분석", 4: "리스크 분석", 5: "ROI 추정"}
        for agent_num, feedback in user_feedbacks.items():
            if feedback:
                agent_name = agent_names.get(agent_num, f"Agent {agent_num}")
                feedback_list.append(f"- {agent_name}: {feedback}")

        if feedback_list:
            user_feedback_section = f"""

**사용자가 제공한 중요 정보 (필수 반영):**
{''.join([f + chr(10) for f in feedback_list])}

**중요:** 위 사용자 피드백의 모든 내용을 최종 의견에 **구체적으로 반영**해주세요.
특히 예산, 인력, 기간, 기술 역량 등 구체적인 정보가 있다면 최종 의견에 명시적으로 포함해주세요."""

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
{roi_estimation}{user_feedback_section}

다음을 포함한 최종 의견을 작성해주세요:
1. 승인 또는 보류 권장 (명확하게)
2. 주요 근거 (3-4가지)
3. 권장사항 (2-3가지)

간결하게 5-7문장으로 작성해주세요."""

    final_recommendation = await asyncio.to_thread(call_ollama, final_prompt, enable_sequential_thinking=enable_seq_thinking)

    if ws:
        await ws.send_json({"status": "completed", "agent": "Final_Generator", "message": "최종 의견 생성 완료"})
    update_job_status(job_id, "final_done")

    # HITL 인터럽트: Agent 6 이후 (설정에 따라)
    if 6 in hitl_stages:
        agent_num = 6
        skip_accepted_agent6 = False
        while True:
            quality_check = await asyncio.to_thread(
                analyze_result_quality,
                "Final Generator",
                final_recommendation,
                proposal_text,
                call_ollama
            )
            print(f"[DEBUG] Quality check for Agent 6: {quality_check}")

            feedback_suggestion = await asyncio.to_thread(
                generate_feedback_suggestion,
                "Final Generator",
                final_recommendation,
                proposal_text,
                call_ollama
            )

            if ws:
                await ws.send_json({
                    "status": "interrupt",
                    "job_id": job_id,
                    "message": f"최종 의견 확인 중... (재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}) - {quality_check.get('reason', '')}",
                    "results": {
                        "final_recommendation": final_recommendation,
                        "feedback_suggestion": feedback_suggestion,
                        "quality_check": quality_check
                    }
                })

            # 사용자가 결과를 확인할 때까지 대기
            await wait_for_feedback(job_id, update_job_status, get_job)

            updated_job = get_job(job_id)
            skip_requested = updated_job.get("feedback_skip", False)
            user_feedback = (updated_job.get("feedback") or "").strip()

            print(f"[DEBUG] User feedback retrieved (Agent 6): '{user_feedback}' (skip={skip_requested})")

            if skip_requested:
                skip_accepted_agent6 = True
                retry_decision = {"needs_retry": False, "reason": "사용자가 건너뛰기를 선택"}
                reset_feedback_state(job_id)
                print(f"[DEBUG] HITL skip acknowledged for Agent 6 (job {job_id})")
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

            print(f"[DEBUG] Retry decision for Agent 6: {retry_decision}")

            if skip_accepted_agent6:
                break

            if retry_decision.get("needs_retry") and hitl_retry_counts[agent_num] < MAX_HITL_RETRIES:
                hitl_retry_counts[agent_num] += 1
                print(f"[DEBUG] Agent 6 재시도 {hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES}")

                if ws:
                    await ws.send_json({
                        "status": "processing",
                        "agent": "Final_Generator",
                        "message": f"품질 개선을 위해 재검토 중... ({hitl_retry_counts[agent_num]}/{MAX_HITL_RETRIES})"
                    })

                # 사용자 피드백이 있으면 프롬프트를 완전히 다르게 구성
                if retry_decision.get("user_feedback"):
                    retry_prompt = f"""당신은 AI 프로젝트 검토 전문가입니다.
사용자가 중요한 피드백을 제공했습니다. 이 피드백을 **반드시 반영**하여 최종 의견을 다시 작성해주세요.

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

이전 최종 의견:
{final_recommendation}

**사용자 피드백 (필수 반영):**
{retry_decision.get('user_feedback')}

**중요:** 위 사용자 피드백의 내용을 최종 의견에 **구체적으로 반영**해주세요.
사용자가 제공한 모든 정보(예: 예산, 인력, 기간, 기술 역량 등)를 명시적으로 언급하고,
이를 바탕으로 다음을 포함한 최종 의견을 작성해주세요:

1. 승인/보류 권장 (사용자 피드백을 고려한 명확한 결정)
2. 주요 근거 (사용자 피드백의 정보를 구체적으로 인용하여 3-4가지)
3. 실행 권장사항 (사용자가 제공한 정보를 반영한 구체적인 제안 2-3가지)

**반드시 사용자 피드백의 내용을 최종 의견에 직접 언급하면서 7-10문장 이상으로 작성해주세요.**
예: "사용자가 언급한 예산 3억원을 고려할 때..." 또는 "제공된 인력 정보에 따르면..." 등"""
                else:
                    retry_prompt = f"""당신은 AI 프로젝트 검토 전문가입니다.
이전 최종 의견이 품질 기준을 충족하지 못했습니다. 더 상세하고 구체적으로 최종 의견을 재작성해주세요.

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

이전 최종 의견 (불충분):
{final_recommendation}

품질 검사 결과:
- 문제점: {retry_decision.get('reason', '의견이 불충분함')}
- 보완 필요 사항: {', '.join(retry_decision.get('additional_info_needed', ['더 명확한 판단', '구체적인 근거']))}

위 문제점을 해결하고 다음을 포함한 **구체적이고 명확한** 최종 의견을 작성해주세요:
1. 승인/보류 권장 (명확한 결정과 이유)
2. 주요 근거 (구체적인 데이터와 분석 결과 인용)
3. 실행 권장사항 (구체적이고 실현 가능한 제안)

**반드시 7-10문장 이상으로 명확한 판단과 상세한 근거를 포함하여 작성해주세요.**"""

                final_recommendation = await asyncio.to_thread(call_ollama, retry_prompt, enable_sequential_thinking=enable_seq_thinking)

                if ws:
                    await ws.send_json({
                        "status": "completed",
                        "agent": "Final_Generator",
                        "message": "재검토 완료"
                    })

                continue
            else:
                if hitl_retry_counts[agent_num] >= MAX_HITL_RETRIES:
                    print(f"[DEBUG] Agent 6 최대 재시도 횟수 도달")
                    if ws:
                        await ws.send_json({
                            "status": "processing",
                            "agent": "Final_Generator",
                            "message": "최대 재시도 횟수 도달, 최종 보고서를 생성합니다"
                        })
                break

        if ws:
            next_message = (
                "사용자 건너뛰기 요청을 수락했습니다. 최종 보고서를 생성합니다."
                if skip_accepted_agent6
                else "피드백 반영하여 최종 보고서 생성 중..."
            )
            await ws.send_json({"status": "processing", "message": next_message})
        await asyncio.sleep(1)

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
            <div id="section1" class="accordion-content">
                <p><strong>유사 사례:</strong></p>
                {''.join([f'''
                <div style="background: #f8f9fa; padding: 12px; margin: 10px 0; border-left: 3px solid #007bff; border-radius: 4px;">
                    <h4 style="margin: 0 0 8px 0; color: #007bff;">{idx+1}. {f'<a href="{c.get("link")}" target="_blank" style="color: #007bff; text-decoration: none;">{c.get("title", "제목 없음")} 🔗</a>' if c.get("link") else c.get("title", "제목 없음")}</h4>
                    <p style="margin: 4px 0;"><strong>기술 유형:</strong> {c.get("tech_type", "N/A")}</p>
                    <p style="margin: 4px 0;"><strong>도메인:</strong> {c.get("business_domain", c.get("domain", "N/A"))} | <strong>사업부:</strong> {c.get("division", "N/A")}</p>
                    <p style="margin: 4px 0;"><strong>문제 (AS-IS):</strong> {c.get("problem_as_was", "N/A")}</p>
                    <p style="margin: 4px 0;"><strong>솔루션 (TO-BE):</strong> {c.get("solution_to_be", "N/A")}</p>
                    <p style="margin: 4px 0; background: #fff3cd; padding: 8px; border-radius: 3px;"><strong>💎 핵심 요약:</strong> {c.get("summary", "N/A")}</p>
                    {f'<p style="margin: 4px 0; background: #d1ecf1; padding: 8px; border-radius: 3px;"><strong>💡 팁:</strong> {c.get("tips")}</p>' if c.get("tips") else ''}
                    {f'<p style="margin: 8px 0 0 0;"><a href="{c.get("link")}" target="_blank" style="color: #007bff; text-decoration: none; font-size: 0.9em;">📄 원본 문서 보기 →</a></p>' if c.get("link") else ''}
                </div>
                ''' for idx, c in enumerate(bp_cases)]) if bp_cases else '<p>검색된 사례 없음</p>'}
                <p style="margin-top: 15px;"><em>총 {len(bp_cases)}건의 유사 사례가 발견되었습니다.</em></p>
            </div>
        </div>

        <div class="accordion-item">
            <div class="accordion-header" onclick="toggleAccordion('section2')">
                <span>2. 목표 적합성</span>
                <span class="accordion-icon">▼</span>
            </div>
            <div id="section2" class="accordion-content">
                <div class="markdown-content" data-markdown>{objective_review}</div>
            </div>
        </div>

        <div class="accordion-item">
            <div class="accordion-header" onclick="toggleAccordion('section3')">
                <span>3. 데이터 분석</span>
                <span class="accordion-icon">▼</span>
            </div>
            <div id="section3" class="accordion-content">
                <div class="markdown-content" data-markdown>{data_analysis}</div>
            </div>
        </div>

        <div class="accordion-item">
            <div class="accordion-header" onclick="toggleAccordion('section4')">
                <span>4. 리스크 분석</span>
                <span class="accordion-icon">▼</span>
            </div>
            <div id="section4" class="accordion-content">
                <div class="markdown-content" data-markdown>{risk_analysis}</div>
            </div>
        </div>

        <div class="accordion-item">
            <div class="accordion-header" onclick="toggleAccordion('section5')">
                <span>5. ROI 추정</span>
                <span class="accordion-icon">▼</span>
            </div>
            <div id="section5" class="accordion-content">
                <div class="markdown-content" data-markdown>{roi_estimation}</div>
            </div>
        </div>

        <div class="accordion-item">
            <div class="accordion-header" onclick="toggleAccordion('section6')">
                <span>6. 최종 의견</span>
                <span class="accordion-icon">▼</span>
            </div>
            <div id="section6" class="accordion-content" style="display: block;">
                <div class="markdown-content" data-markdown>{final_recommendation}</div>
                <div style="margin-top: 15px; text-align: right;">
                    <button onclick="window.location.href='/api/export/final-recommendation/{job_id}'"
                            style="background-color: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-size: 14px;">
                        📄 최종 의견 PDF 다운로드
                    </button>
                </div>
            </div>
        </div>
    </div>
    """

    decision_result = await classify_final_decision(final_report, final_recommendation, call_llm)
    decision_value = decision_result.get("decision", "보류")
    decision_reason = decision_result.get("reason", "LLM 판단을 기준으로 자동 분류되었습니다.")

    latest_job = get_job(job_id) or {}
    metadata = latest_job.get("metadata", {}).copy()
    metadata["report"] = final_report
    agent_results = metadata.setdefault("agent_results", {})
    agent_results["final_recommendation"] = final_recommendation
    metadata["final_decision"] = {
        "decision": decision_value,
        "reason": decision_reason,
    }

    update_job_status(
        job_id,
        "completed",
        metadata=metadata,
        llm_decision=decision_value,
    )

    if send_final_report:
        target_ws = ws or (active_connections.get(ws_key) if active_connections and ws_key else None)
        if target_ws:
            human_decision_value = latest_job.get("decision") or latest_job.get("human_decision")
            await target_ws.send_json({
                "status": "completed",
                "agent": "Final_Generator",
                "message": "검토 완료",
                "report": final_report,
                "decision": decision_value,
                "decision_reason": decision_reason,
                "human_decision": human_decision_value,
            })

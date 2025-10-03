# agents/agent7_proposal_improver.py - Proposal Improver Agent

import asyncio
from .utils import persist_job_metadata


async def run_proposal_improver(job_id: int, job: dict, ws,
                                  objective_review: str, data_analysis: str, risk_analysis: str,
                                  roi_estimation: str, final_recommendation: str, bp_cases: list,
                                  call_ollama, get_job, update_job_status, user_feedbacks: dict = None):
    """Proposal Improver - Generate improved proposal based on all analyses

    Args:
        job_id: Job ID
        job: Job data dictionary
        ws: WebSocket connection
        objective_review: Result from Agent 2
        data_analysis: Result from Agent 3
        risk_analysis: Result from Agent 4
        roi_estimation: Result from Agent 5
        final_recommendation: Result from Agent 6
        bp_cases: BP cases from Agent 1
        call_ollama: LLM call function
        get_job: Database get_job function
        update_job_status: Database update_job_status function

    Returns:
        str: Improved proposal text
    """
    # WebSocket이 이미 닫혔을 수 있으므로 try-except로 처리
    if ws:
        try:
            await ws.send_json({
                "status": "processing",
                "agent": "Proposal_Improver",
                "message": "개선된 지원서 작성 중..."
            })
        except Exception as e:
            print(f"[Agent 7] WebSocket send failed (already closed): {e}")

    proposal_text = job.get("content", "")
    enable_seq_thinking = job.get("enable_sequential_thinking", False)

    if enable_seq_thinking:
        print(f"[Agent 7] Sequential Thinking 활성화됨")

    # BP 사례 요약
    bp_summary = ""
    if bp_cases:
        bp_summary = "참고 가능한 유사 사례:\n"
        for idx, case in enumerate(bp_cases[:3], 1):
            bp_summary += f"{idx}. {case.get('title', '제목 없음')} ({case.get('domain', '')}/{case.get('division', '')})\n"

    # 사용자 피드백 수집 및 정리
    user_feedback_section = ""
    if user_feedbacks:
        feedback_list = []
        for agent_num, feedback in user_feedbacks.items():
            if feedback:
                feedback_list.append(f"- Agent {agent_num}: {feedback}")

        if feedback_list:
            user_feedback_section = f"""

**사용자가 제공한 중요 정보 (필수 반영):**
{''.join([f + chr(10) for f in feedback_list])}

**중요:** 위 사용자 피드백의 모든 내용을 개선된 지원서에 **구체적으로 반영**해주세요.
특히 예산, 인력, 기간, 기술 역량 등 구체적인 정보가 있다면 해당 섹션에 명시적으로 포함해주세요."""

    improvement_prompt = f"""당신은 AI 과제 지원서 작성 전문가입니다.
다음 원본 지원서와 검토 결과를 바탕으로 개선된 지원서를 작성해주세요.

**원본 지원서:**
{proposal_text}

**검토 결과:**

1. 목표 적합성 검토:
{objective_review}

2. 데이터 분석:
{data_analysis}

3. 리스크 분석:
{risk_analysis}

4. ROI 추정:
{roi_estimation}

5. 최종 의견:
{final_recommendation}

{bp_summary}
{user_feedback_section}

**개선 방향:**
위 검토 결과에서 지적된 문제점들을 보완하고, 강점은 더욱 강화하여 개선된 지원서를 작성해주세요.
사용자 피드백에 포함된 구체적인 정보(예산, 인력, 기간 등)는 반드시 해당 섹션에 포함해주세요.

다음 구조로 개선된 지원서를 작성해주세요:

# 개선된 AI 과제 지원서

## 1. 과제 개요 및 목표
- 과제 명칭:
- 추진 배경:
- 주요 목표: (구체적이고 측정 가능한 목표로 작성)

## 2. 기술적 접근 방법
- 적용 기술:
- 기술 선정 이유:
- 구현 계획:

## 3. 데이터 확보 및 활용 계획
- 필요 데이터:
- 데이터 확보 방안:
- 데이터 품질 관리 방안:

## 4. 리스크 관리 계획
- 주요 리스크: (기술적/일정/인력)
- 완화 방안:
- 비상 대응 계획:

## 5. 기대 효과 및 ROI
- 정량적 효과: (구체적인 수치 포함)
- 정성적 효과:
- 투자 대비 효과:

## 6. 추진 일정 및 체계
- 단계별 일정:
- 추진 조직:
- 필요 자원:

**주의사항:**
- 검토에서 지적된 약점을 명확히 보완할 것
- 구체적인 수치와 근거를 포함할 것
- 실현 가능성을 높이는 방향으로 작성할 것
- 마크다운 형식으로 작성할 것
- 전체 분량은 800-1200자 정도로 작성할 것"""

    improved_proposal = await asyncio.to_thread(
        call_ollama,
        improvement_prompt,
        enable_sequential_thinking=enable_seq_thinking
    )

    if ws:
        try:
            await ws.send_json({
                "status": "completed",
                "agent": "Proposal_Improver",
                "message": "개선된 지원서 작성 완료"
            })
        except Exception as e:
            print(f"[Agent 7] WebSocket send failed (already closed): {e}")

    persist_job_metadata(
        job_id,
        "proposal_improver_done",
        get_job,
        update_job_status,
        agent_updates={"improved_proposal": improved_proposal},
    )

    return improved_proposal

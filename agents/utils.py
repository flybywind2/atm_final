# agents/utils.py - Shared utility functions for all agents

import json
import re
import asyncio
from typing import Optional


def _extract_json_dict(text: str) -> Optional[dict]:
    """Extract JSON dictionary from text response"""
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _truncate_for_prompt(text: str, limit: int = 800) -> str:
    """Truncate text for prompt with limit"""
    if not text:
        return ''
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + '...'


def _classify_decision_sync(final_report: str, final_recommendation: str, call_llm) -> dict:
    """Classify final decision as 승인 or 보류"""
    prompt = f"""
당신은 AI 프로젝트 심사위원입니다. 최종 보고서와 최종 의견을 읽고 과제를 '승인' 또는 '보류' 중 하나로 판단하세요.
결정 기준: 실행 가능성, 기대 효과, 리스크 수준, ROI 등을 종합적으로 고려합니다.
출력은 JSON 형식으로만 답변하며, 가능한 값은 "승인" 또는 "보류"입니다.

최종 보고서:
{_truncate_for_prompt(final_report, 1200)}

최종 의견:
{_truncate_for_prompt(final_recommendation, 800)}

응답 형식 예시:
{{"decision": "승인", "reason": "핵심 근거"}}
"""
    response = call_llm(prompt)
    data = _extract_json_dict(response) or {}
    decision = data.get('decision')
    if decision not in ('승인', '보류'):
        decision = '보류'
    reason = data.get('reason') or 'LLM 판단을 기준으로 자동 분류되었습니다.'
    return {'decision': decision, 'reason': reason}


async def classify_final_decision(final_report: str, final_recommendation: str, call_llm) -> dict:
    """Async wrapper for classify_final_decision"""
    return await asyncio.to_thread(_classify_decision_sync, final_report, final_recommendation, call_llm)


def analyze_result_quality(agent_name: str, analysis_result: str, proposal_text: str, call_ollama) -> dict:
    """Analyze agent result quality to determine if retry is needed

    Returns:
        {
            "needs_retry": bool,
            "reason": str,
            "additional_info_needed": list
        }
    """
    print(f"[DEBUG] Analyzing result quality for {agent_name}...")
    print(f"[DEBUG] Analysis result length: {len(analysis_result)}")

    quality_check_prompt = f"""당신은 AI 검토 프로세스의 품질 관리 orchestrator입니다.
{agent_name}가 다음과 같은 분석 결과를 제출했습니다.

제안서 내용:
{proposal_text[:500]}...

{agent_name}의 분석 결과:
{analysis_result}

위 분석 결과가 충분히 상세하고 구체적인지 평가해주세요.

**재검토가 필요한 경우 (needs_retry = true):**
- 분석 내용이 너무 짧거나 추상적인 경우 (2-3문장 미만)
- 구체적인 근거나 데이터가 부족한 경우
- 핵심 질문에 대한 답변이 불충분한 경우
- "평가 필요", "추가 검토 필요" 등 모호한 표현만 있는 경우
- 제안서 내용을 제대로 반영하지 않은 경우

**재검토가 불필요한 경우 (needs_retry = false):**
- 분석이 상세하고 구체적인 경우
- 명확한 근거와 함께 판단이 제시된 경우
- 요구사항에 맞게 충분한 정보를 제공한 경우
- 각 평가 항목이 구체적으로 설명된 경우

반드시 다음 JSON 형식으로만 응답하세요 (설명 없이 JSON만):
{{
    "needs_retry": true,
    "reason": "분석 내용이 너무 간략하고 구체적인 근거가 부족함",
    "additional_info_needed": ["구체적인 데이터", "상세한 근거", "명확한 판단 기준"]
}}

또는

{{
    "needs_retry": false,
    "reason": "분석이 충분히 상세하고 구체적임",
    "additional_info_needed": []
}}"""

    try:
        result = call_ollama(quality_check_prompt)
        print(f"[DEBUG] Raw quality check response: {result}")

        # JSON 파싱
        json_str = result.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        print(f"[DEBUG] Extracted JSON string: {json_str}")
        analysis = json.loads(json_str)
        print(f"[DEBUG] Parsed quality analysis: {analysis}")

        # needs_retry가 boolean이 아니면 변환
        if isinstance(analysis.get("needs_retry"), str):
            analysis["needs_retry"] = analysis["needs_retry"].lower() in ["true", "yes", "1"]

        return analysis
    except Exception as e:
        print(f"[DEBUG] Failed to parse quality analysis: {e}")
        print(f"[DEBUG] Raw result was: {result if 'result' in locals() else 'No result'}")

        # 파싱 실패 시 간단한 휴리스틱 판단
        # 분석 결과가 너무 짧으면 재시도
        if len(analysis_result.strip()) < 100:
            print(f"[DEBUG] Fallback: Analysis too short, enabling retry")
            return {"needs_retry": True, "reason": "분석 결과가 너무 짧음 (100자 미만)", "additional_info_needed": ["더 상세한 분석"]}

        return {"needs_retry": False, "reason": "Quality check failed - defaulting to no retry", "additional_info_needed": []}


def generate_feedback_suggestion(agent_name: str, analysis_result: str, proposal_text: str, call_ollama) -> str:
    """Generate concrete feedback suggestion based on agent analysis result"""
    print(f"[DEBUG] Generating feedback suggestion for {agent_name}...")

    # Agent별 특화된 피드백 가이드
    agent_specific_guides = {
        "Objective_Reviewer": """
**Agent 2 (Objective Reviewer) 특화 피드백**
- 프로젝트 목표의 명확성과 구체성 평가
- 업무 목적과의 정렬도 분석
- 성공 기준 및 측정 방법의 타당성

피드백 예시 형식:
**[목표 명확화]**
- 프로젝트 목표: [고객 문의 응답 시간을 현재 [10]분에서 [2]분으로 단축]
- 핵심 성과 지표(KPI): [응답 시간 [80]% 단축, 고객 만족도 [95]점 이상 달성]
- 성공 측정 방법: [매월 [응답 시간 통계] 및 [고객 만족도 설문] 분석]

**[목적 정렬성]**
- 업무 목적: [고객 서비스 품질 향상]을 통한 [고객 이탈률 [20]% 감소]
- 조직 전략과의 연계: [디지털 전환 전략]의 일환으로 [고객 경험 개선] 목표 달성

**[개선 제안]**
- 목표 구체화: "[AI 챗봇 도입]"을 "[자연어처리 기반 자동응답 시스템으로 [일반 문의의 [70]%] 자동 처리]"로 명확히 기술""",

        "Data_Analyst": """
**Agent 3 (Data Analyst) 특화 피드백**
- 데이터 소스, 품질, 규모의 적절성 평가
- 데이터 전처리 및 관리 계획 검토
- 데이터 기반 의사결정 프로세스 분석

피드백 예시 형식:
**[데이터 규모 및 소스]**
- 학습 데이터: [고객 문의 [10만]건, [2020-2024]년 [5]개년 데이터]
- 데이터 소스: [고객센터 CRM 시스템], [이메일 문의 [5만]건], [챗봇 로그 [5만]건]
- 레이블링: [전문가 검수 완료 데이터 [8만]건], [추가 레이블링 필요 [2만]건]

**[데이터 품질 관리]**
- 품질 기준: 정확도 [95]% 이상, 결측치 [5]% 미만, 중복 제거율 [100]%
- 전처리 계획: [개인정보 마스킹], [특수문자 정규화], [불용어 제거]
- 품질 검증: [샘플 [1000]건 수작업 검수] 후 전체 적용

**[데이터 보안]**
- 개인정보 처리: [고객명, 연락처 등 [7]개 항목 암호화 저장]
- 접근 권한: [개발팀 [5]명만 접근 가능], [감사 로그 [3]년 보관]""",

        "Risk_Analyzer": """
**Agent 4 (Risk Analyzer) 특화 피드백**
- 기술적, 운영적, 법적 리스크 식별
- 리스크 발생 가능성 및 영향도 평가
- 구체적인 완화 전략 및 대응 방안

피드백 예시 형식:
**[기술 리스크 대응]**
- 리스크: [AI 모델 정확도가 목표 [90]%에 미달할 가능성 [30]%]
- 완화 방안: [사전 학습 모델(BERT) 활용으로 기본 정확도 [85]% 확보]
- 대응 계획: [정확도 [85]% 미만 시 [외부 전문가 컨설팅] 및 [추가 데이터 [5만]건 확보]]

**[운영 리스크 대응]**
- 리스크: [기존 시스템과의 통합 실패 가능성 [20]%]
- 완화 방안: [API 연동 테스트 [3]개월 전 완료], [레거시 시스템 [CRM v2.1] 호환성 검증]
- 대응 계획: [연동 실패 시 [중간 데이터 레이어] 구축으로 [2]주 내 해결]

**[일정 리스크]**
- 리스크: [핵심 개발자 [2]명 이탈 시 일정 [3]개월 지연]
- 완화 방안: [기술 문서화 [100]%], [백업 인력 [3]명 사전 교육]
- 대응 계획: [외부 개발사와 [긴급 지원 계약] 체결 ([1]개월 내 투입 가능)]""",

        "ROI_Estimator": """
**Agent 5 (ROI Estimator) 특화 피드백**
- 투자 비용 및 기대 효과의 정량적 산출
- ROI 계산 근거 및 회수 기간 분석
- 비용 대비 효과의 타당성 검토

피드백 예시 형식:
**[투자 비용 상세]**
- 개발 비용: [인건비 [5]명 × [6]개월 × [월 [800]만원] = [2.4]억원]
- 인프라 비용: [GPU 서버 [2]대 × [월 [300]만원] × [12]개월 = [0.72]억원]
- 라이선스 비용: [ML 프레임워크 라이선스 [0.3]억원], [데이터 레이블링 툴 [0.2]억원]
- 총 투자액: [3.62]억원 ([개발 2.4억] + [인프라 0.72억] + [기타 0.5억])

**[기대 효과 산출]**
- 인건비 절감: [상담사 [3]명 × [연봉 [4000]만원] = 연 [1.2]억원 절감]
- 처리 시간 단축: [건당 [10]분 → [2]분], [일 처리량 [50]% 증가로 매출 [0.8]억원 증대]
- 고객 만족도 향상: [이탈률 [20]% → [15]%], [재구매율 [5]%p 상승으로 연 [0.5]억원 증대]
- 연간 총 효과: [2.5]억원

**[ROI 계산]**
- ROI: ([연간 효과 2.5억] - [연간 운영비 0.5억]) / [투자액 3.62억] × 100 = [55]%
- 투자 회수 기간: [3.62]억 / [연간 순효과 2억] = [1.8]년
- [3]년 누적 효과: [6]억원 ([3]년 × [2]억원) - [투자액 3.62억] = 순이익 [2.38]억원""",

        "Final_Generator": """
**Agent 6 (Final Generator) 특화 피드백**
- 전체 검토 결과를 종합한 통합 피드백
- 모든 영역(목표, 데이터, 리스크, ROI)을 포괄

피드백 예시 형식:
**[프로젝트 목표 및 범위]**
- 목표: [고객 문의 자동응답률 [70]%] 달성으로 [응답 시간 [80]% 단축]
- 범위: [일반 문의 [10]개 카테고리] 대상, [복잡 문의는 상담사 연계]
- 기간: [6]개월 ([기획 1개월] + [개발 4개월] + [안정화 1개월])

**[데이터 및 기술]**
- 데이터: [5개년 문의 데이터 [10만]건], [레이블링 완료율 [80]%]
- 기술 스택: [BERT 기반 NLP 모델], [정확도 목표 [90]%]
- 인프라: [GPU 서버 [2]대], [클라우드 [AWS/GCP]]

**[리스크 관리]**
- 기술 리스크: [정확도 미달 시 외부 전문가 투입], [예비 예산 [0.5]억원]
- 일정 리스크: [핵심 인력 이탈 대비 백업 [3]명 확보]
- 데이터 리스크: [품질 저하 시 외부 데이터 구매], [예산 [0.2]억원]

**[투자 대비 효과]**
- 총 투자: [3.62]억원 ([개발 2.4억] + [인프라 0.72억] + [기타 0.5억])
- 연간 효과: [2.5]억원 ([인건비 절감 1.2억] + [매출 증대 1.3억])
- ROI: [55]%, 회수 기간 [1.8]년, [3]년 순이익 [2.38]억원"""
    }

    # agent_name에서 Agent 번호 제거 후 키 매칭
    agent_key = agent_name.replace("Agent_", "").replace("Agent ", "").strip()
    specific_guide = agent_specific_guides.get(agent_key, "")

    feedback_prompt = f"""당신은 AI 과제 제안서 검토 전문가입니다.
다음은 {agent_name}의 분석 결과입니다:

{analysis_result}

제안서 원문:
{proposal_text[:1000]}...

위 분석 결과를 바탕으로, 제안서 작성자가 **그대로 복사해서 피드백 입력란에 붙여넣고, 숫자나 단어만 약간 수정**하여 바로 제출할 수 있는 구체적인 피드백 예시를 작성해주세요.

**중요**: 피드백 예시는 다음 요구사항을 모두 충족해야 합니다:
1. **구체적인 수치 포함**: 예산, 기간, 목표치 등 구체적인 숫자를 반드시 포함
2. **즉시 사용 가능**: "예산은 [XX]억 원입니다", "예상 ROI는 [YY]%입니다" 같이 []로 표시된 부분만 수정하면 바로 사용 가능하도록 작성
3. **실행 가능한 제안**: "~를 추가하세요", "~를 구체화하세요"가 아닌, 구체적인 내용 예시를 직접 제공
4. **Agent 특화 내용**: {agent_name}의 전문 분야에 맞는 피드백 제공

{specific_guide}

위 가이드를 참고하여, 현재 {agent_name}의 분석 결과와 제안서에 맞는 구체적인 피드백 예시를 생성해주세요.
반드시 []로 감싼 수정 가능한 값들을 포함하여 작성하세요."""

    result = call_ollama(feedback_prompt)
    print(f"[DEBUG] Feedback suggestion generated (length: {len(result)} chars)")
    return result


async def wait_for_feedback(job_id: int, update_job_status, get_job, timeout_seconds: int = 300):
    """Wait for HITL feedback helper function"""
    print(f"Job {job_id}: Waiting for user feedback...")
    update_job_status(job_id, "waiting_feedback")

    for i in range(timeout_seconds):
        job = get_job(job_id)
        if job.get("status") == "feedback_received":
            print(f"Job {job_id}: Feedback received, continuing...")
            return True
        await asyncio.sleep(1)

    print(f"Job {job_id}: Timeout waiting for feedback, continuing anyway...")
    return False


def persist_job_metadata(job_id: int, new_status: str, get_job, update_job_status,
                         agent_updates: dict | None = None, extra_updates: dict | None = None, **status_kwargs):
    """Persist job metadata and update status"""
    job_snapshot = get_job(job_id) or {}
    metadata = job_snapshot.get("metadata", {}).copy()

    if agent_updates:
        agent_results = metadata.setdefault("agent_results", {})
        agent_results.update(agent_updates)

    if extra_updates:
        metadata.update(extra_updates)

    update_job_status(job_id, new_status, metadata=metadata, **status_kwargs)

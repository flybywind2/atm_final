# agents/agent1_bp_scouter.py - BP Case Scouter Agent

import asyncio
from .utils import persist_job_metadata


async def run_bp_scouter(job_id: int, job: dict, ws, domain: str, division: str,
                         rag_retrieve_bp_cases, get_job, update_job_status):
    """BP Case Scouter - Search and retrieve Best Practice cases

    Args:
        job_id: Job ID
        job: Job data dictionary
        ws: WebSocket connection
        domain: Business domain
        division: Business division
        rag_retrieve_bp_cases: RAG retrieval function
        get_job: Database get_job function
        update_job_status: Database update_job_status function

    Returns:
        list: BP cases found
    """
    if ws:
        await ws.send_json({"status": "processing", "agent": "BP_Scouter", "message": "BP 사례 검색 중..."})

    # 제안서 내용 추출
    proposal_content = job.get("content", "")

    # RAG 검색 시도 (제안서 내용 포함)
    rag_result = await rag_retrieve_bp_cases(domain, division, proposal_content)
    bp_cases = rag_result.get("cases", [])

    await asyncio.sleep(2)
    if ws:
        # BP 검색 완료 메시지와 함께 결과 전송
        await ws.send_json({
            "status": "completed",
            "agent": "BP_Scouter",
            "message": f"BP 사례 {len(bp_cases)}건 검색 완료",
            "bp_cases": bp_cases  # BP 검색 결과 추가
        })

    persist_job_metadata(
        job_id,
        "bp_scouter_done",
        get_job,
        update_job_status,
        agent_updates={"bp_scouter": bp_cases},
        extra_updates={"bp_cases": bp_cases},
    )

    return bp_cases

"""RAG (Retrieval Augmented Generation) functions"""
import os
import asyncio
import requests


def retrieve_from_rag(query_text: str, num_result_doc: int = 5, retrieval_method: str = "rrf") -> list:
    """RAG를 통한 문서 검색

    Args:
        query_text: 검색 쿼리
        num_result_doc: 반환할 문서 수
        retrieval_method: 검색 방법 ("rrf", "bm25", "knn", "cc")

    Returns:
        검색 결과 리스트
    """
    try:
        # 환경 변수에서 RAG 설정 로드
        base_url = os.getenv("RAG_BASE_URL", "http://localhost:8000")
        credential_key = os.getenv("RAG_CREDENTIAL_KEY", "")
        rag_api_key = os.getenv("RAG_API_KEY", "")
        index_name = os.getenv("RAG_INDEX_NAME", "")
        permission_groups = os.getenv("RAG_PERMISSION_GROUPS", "user").split(",")

        # 검색 URL 설정
        retrieval_urls = {
            "rrf": f"{base_url}/retrieve-rrf",
            "bm25": f"{base_url}/retrieve-bm25",
            "knn": f"{base_url}/retrieve-knn",
            "cc": f"{base_url}/retrieve-cc"
        }

        retrieval_url = retrieval_urls.get(retrieval_method, retrieval_urls["rrf"])

        # 헤더 설정
        headers = {
            "Content-Type": "application/json",
            "x-dep-ticket": credential_key,
            "api-key": rag_api_key
        }

        # 요청 데이터 설정
        fields = {
            "index_name": index_name,
            "permission_groups": permission_groups,
            "query_text": query_text,
            "num_result_doc": num_result_doc,
            "fields_exclude": ["v_merge_title_content"]
        }

        # RAG API 호출
        response = requests.post(retrieval_url, headers=headers, json=fields, timeout=30)

        if response.status_code == 200:
            result = response.json()
            print(f"RAG 검색 완료: {len(result.get('hits', {}).get('hits', []))}건 검색됨")
            return result.get('hits', {}).get('hits', [])
        else:
            print(f"RAG API 호출 실패: {response.status_code} - {response.text}")
            return []

    except Exception as e:
        print(f"RAG 검색 실패: {e}")
        return []


async def rag_retrieve_bp_cases(domain: str, division: str, proposal_content: str = "") -> dict:
    """RAG를 통한 BP 사례 검색 (Agent 1용 래퍼 함수)

    Args:
        domain: 비즈니스 도메인
        division: 비즈니스 구역
        proposal_content: 제안서 내용 (검색 쿼리 개선용)

    Returns:
        dict: {"cases": [list of BP cases]}
    """
    # 제안서 내용에서 핵심 키워드 추출 (최대 200자)
    proposal_snippet = proposal_content[:200] if proposal_content else ""

    # 제안서 내용을 포함한 검색 쿼리 구성
    if proposal_snippet:
        query = f"{domain} {division} {proposal_snippet} BP 사례"
    else:
        query = f"{domain} {division} BP 사례"

    try:
        hits = await asyncio.to_thread(retrieve_from_rag, query, num_result_doc=5)
        cases = []
        for hit in hits:
            source = hit.get("_source", {})
            cases.append({
                "title": source.get("title", "제목 없음"),
                "tech_type": source.get("tech_type", "AI/ML"),
                "business_domain": source.get("business_domain") or source.get("domain", domain),
                "division": source.get("division", division),
                "problem_as_was": source.get("problem_as_was", source.get("content", "")[:100]),
                "solution_to_be": source.get("solution_to_be", ""),
                "summary": source.get("summary", source.get("content", "")[:200]),
                "tips": source.get("tips", ""),
                "link": source.get("link", "")  # Confluence URL
            })

        # RAG 검색 결과가 없으면 더미 데이터 반환
        if not cases:
            print(f"[DEBUG] RAG 검색 결과 없음, 더미 데이터 반환")
            cases = get_dummy_bp_cases(domain, division)

        return {"cases": cases}
    except Exception as e:
        print(f"BP 사례 검색 실패: {e}, 더미 데이터 반환")
        return {"cases": get_dummy_bp_cases(domain, division)}


def get_dummy_bp_cases(domain: str, division: str) -> list:
    """RAG 연결 전 테스트용 더미 BP 사례"""
    return [
        {
            "title": f"{domain} 분야 AI 기반 자동화 시스템 구축",
            "tech_type": "AI/ML - 자연어처리",
            "business_domain": domain,
            "division": division,
            "problem_as_was": f"{domain} 업무에서 수작업 처리로 인한 시간 소요 및 오류 발생 (하루 평균 4시간 소요)",
            "solution_to_be": "AI 기반 자동 분류 및 처리 시스템 도입으로 처리 시간 80% 단축 및 정확도 95% 달성",
            "summary": f"{domain} 분야에 AI 자동화를 도입하여 업무 효율성을 크게 향상시킨 사례. 6개월 내 ROI 200% 달성",
            "tips": "초기 데이터 품질 확보가 중요. 파일럿 프로젝트로 시작하여 점진적 확대 권장",
            "link": ""  # 더미 데이터는 링크 없음
        },
        {
            "title": f"{division} {domain} 데이터 분석 플랫폼 구축",
            "tech_type": "AI/ML - 예측 분석",
            "business_domain": domain,
            "division": division,
            "problem_as_was": "분산된 데이터로 인한 의사결정 지연 및 인사이트 부족",
            "solution_to_be": "통합 데이터 분석 플랫폼 구축으로 실시간 인사이트 제공 및 예측 정확도 향상",
            "summary": f"{division} 사업부의 {domain} 데이터를 통합 분석하여 의사결정 속도 3배 향상",
            "tips": "데이터 거버넌스 체계를 먼저 수립한 후 플랫폼 구축 시작",
            "link": ""
        },
        {
            "title": f"{domain} 최적화를 위한 머신러닝 모델 적용",
            "tech_type": "AI/ML - 최적화",
            "business_domain": domain,
            "division": division,
            "problem_as_was": "경험 기반 의사결정으로 인한 최적화 한계 및 리소스 낭비",
            "solution_to_be": "ML 기반 최적화 모델로 리소스 활용률 30% 개선 및 비용 절감",
            "summary": f"{domain} 업무 최적화를 위한 ML 모델 개발 및 적용 성공 사례",
            "tips": "도메인 전문가와 데이터 사이언티스트의 긴밀한 협업이 성공의 핵심",
            "link": ""
        }
    ]

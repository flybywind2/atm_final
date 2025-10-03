# database/db.py - SQLite 연동 (MVP 간단 구현)
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/review.db")

def init_database():
    """데이터베이스 초기화"""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 테이블 생성
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS review_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            user_id TEXT,
            proposal_content TEXT,
            domain TEXT,
            division TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        )
    """)

    # 필요한 컬럼 추가 (스키마 마이그레이션)
    cursor.execute("PRAGMA table_info(review_jobs)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    if "decision" not in existing_columns:
        cursor.execute("ALTER TABLE review_jobs ADD COLUMN decision TEXT DEFAULT 'pending'")

    if "llm_decision" not in existing_columns:
        cursor.execute("ALTER TABLE review_jobs ADD COLUMN llm_decision TEXT DEFAULT 'pending'")
        cursor.execute("UPDATE review_jobs SET llm_decision = COALESCE(decision, 'pending')")

    if "title" not in existing_columns:
        cursor.execute("ALTER TABLE review_jobs ADD COLUMN title TEXT")

    if "confluence_page_id" not in existing_columns:
        cursor.execute("ALTER TABLE review_jobs ADD COLUMN confluence_page_id TEXT")

    if "confluence_page_url" not in existing_columns:
        cursor.execute("ALTER TABLE review_jobs ADD COLUMN confluence_page_url TEXT")

    if "enable_sequential_thinking" not in existing_columns:
        cursor.execute("ALTER TABLE review_jobs ADD COLUMN enable_sequential_thinking INTEGER DEFAULT 0")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hitl_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            agent_id TEXT NOT NULL,
            feedback_data TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES review_jobs(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enterprise_bp_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            tech_type TEXT,
            business_domain TEXT,
            division TEXT,
            organization TEXT,
            problem_as_was TEXT,
            solution_to_be TEXT,
            summary TEXT,
            tips TEXT,
            reference_docs TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print("Database initialized successfully")

def create_job(
    proposal_content: str,
    domain: str,
    division: str,
    *,
    title: str | None = None,
    hitl_stages: list | None = None,
    status: str = "pending",
    human_decision: str = "pending",
    llm_decision: str = "pending",
    metadata: dict | None = None,
    confluence_page_id: str | None = None,
    confluence_page_url: str | None = None,
    enable_sequential_thinking: bool = False,
):
    """새 검토 작업 생성"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    metadata_payload = metadata.copy() if metadata else {}
    if hitl_stages is not None:
        metadata_payload["hitl_stages"] = hitl_stages

    cursor.execute(
        """
        INSERT INTO review_jobs (status, decision, llm_decision, title, proposal_content, domain, division, metadata, confluence_page_id, confluence_page_url, enable_sequential_thinking)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            status,
            human_decision,
            llm_decision,
            title,
            proposal_content,
            domain,
            division,
            json.dumps(metadata_payload),
            confluence_page_id,
            confluence_page_url,
            1 if enable_sequential_thinking else 0,
        ),
    )

    job_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return job_id

def _row_to_job_dict(row):
    (
        job_id,
        status,
        decision,
        llm_decision,
        title,
        proposal_content,
        domain,
        division,
        metadata_json,
        created_at,
        updated_at,
        confluence_page_id,
        confluence_page_url,
        enable_sequential_thinking,
    ) = row

    metadata = json.loads(metadata_json) if metadata_json else {}

    return {
        "id": job_id,
        "status": status,
        "decision": decision or "pending",
        "human_decision": decision or "pending",
        "llm_decision": llm_decision or "pending",
        "title": title or "",
        "content": proposal_content,
        "proposal_content": proposal_content,
        "domain": domain,
        "division": division,
        "metadata": metadata,
        "hitl_stages": metadata.get("hitl_stages", []),
        "feedback": metadata.get("feedback", ""),
        "feedback_skip": metadata.get("feedback_skip", False),
        "feedback_history": metadata.get("feedback_history", []),
        "report": metadata.get("report"),
        "created_at": created_at,
        "updated_at": updated_at,
        "confluence_page_id": confluence_page_id,
        "confluence_page_url": confluence_page_url,
        "enable_sequential_thinking": bool(enable_sequential_thinking),
    }


def get_job(job_id: int):
    """작업 단건 조회"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, status, decision, llm_decision, title, proposal_content, domain, division, metadata, created_at, updated_at, confluence_page_id, confluence_page_url, enable_sequential_thinking
        FROM review_jobs WHERE id = ?
        """,
        (job_id,),
    )

    row = cursor.fetchone()
    conn.close()

    return _row_to_job_dict(row) if row else None


def list_jobs(
    *,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    decision: str | None = None,
    llm_decision: str | None = None,
    search: str | None = None,
    order: str = "desc",
):
    """작업 목록 조회"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = [
        "SELECT id, status, decision, llm_decision, title, proposal_content, domain, division, metadata, created_at, updated_at, confluence_page_id, confluence_page_url, enable_sequential_thinking",
        "FROM review_jobs",
        "WHERE 1 = 1",
    ]
    params: list = []

    if status:
        query.append("AND status = ?")
        params.append(status)

    if decision:
        query.append("AND decision = ?")
        params.append(decision)

    if llm_decision:
        query.append("AND llm_decision = ?")
        params.append(llm_decision)

    if search:
        query.append("AND (proposal_content LIKE ? OR COALESCE(title, '') LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])

    order_clause = "DESC" if order.lower() != "asc" else "ASC"
    query.append(f"ORDER BY datetime(created_at) {order_clause}")
    query.append("LIMIT ? OFFSET ?")
    params.extend([limit, offset])

    cursor.execute("\n".join(query), params)
    rows = cursor.fetchall()
    conn.close()

    return [_row_to_job_dict(row) for row in rows]


def count_jobs(
    *,
    status: str | None = None,
    decision: str | None = None,
    llm_decision: str | None = None,
    search: str | None = None,
):
    """필터에 따른 총 개수"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = ["SELECT COUNT(*) FROM review_jobs WHERE 1 = 1"]
    params: list = []

    if status:
        query.append("AND status = ?")
        params.append(status)

    if decision:
        query.append("AND decision = ?")
        params.append(decision)

    if llm_decision:
        query.append("AND llm_decision = ?")
        params.append(llm_decision)

    if search:
        query.append("AND (proposal_content LIKE ? OR COALESCE(title, '') LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])

    cursor.execute("\n".join(query), params)
    total = cursor.fetchone()[0]
    conn.close()
    return total


def update_job_record(
    job_id: int,
    *,
    title: str | None = None,
    proposal_content: str | None = None,
    domain: str | None = None,
    division: str | None = None,
    status: str | None = None,
    human_decision: str | None = None,
    llm_decision: str | None = None,
    metadata: dict | None = None,
):
    """필드 단위 업데이트"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    fields = []
    params: list = []

    if title is not None:
        fields.append("title = ?")
        params.append(title)

    if proposal_content is not None:
        fields.append("proposal_content = ?")
        params.append(proposal_content)

    if domain is not None:
        fields.append("domain = ?")
        params.append(domain)

    if division is not None:
        fields.append("division = ?")
        params.append(division)

    if status is not None:
        fields.append("status = ?")
        params.append(status)

    if human_decision is not None:
        fields.append("decision = ?")
        params.append(human_decision)

    if llm_decision is not None:
        fields.append("llm_decision = ?")
        params.append(llm_decision)

    if metadata is not None:
        fields.append("metadata = ?")
        params.append(json.dumps(metadata))

    if not fields:
        conn.close()
        return False

    fields.append("updated_at = CURRENT_TIMESTAMP")
    params.append(job_id)

    cursor.execute(
        f"""
        UPDATE review_jobs
        SET {', '.join(fields)}
        WHERE id = ?
        """,
        params,
    )

    conn.commit()
    conn.close()
    return True


def delete_job(job_id: int):
    """작업 삭제"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM review_jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()


def update_job_status(
    job_id: int,
    status: str,
    metadata: dict = None,
    decision: str | None = None,
    llm_decision: str | None = None,
    human_decision: str | None = None,
):
    """작업 상태 및 결정 결과 업데이트"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    fields = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
    params = [status]

    if metadata is not None:
        fields.append("metadata = ?")
        params.append(json.dumps(metadata))

    human_value = human_decision if human_decision is not None else decision
    if human_value is not None:
        fields.append("decision = ?")
        params.append(human_value)

    if llm_decision is not None:
        fields.append("llm_decision = ?")
        params.append(llm_decision)

    params.append(job_id)

    cursor.execute(
        f"""
        UPDATE review_jobs
        SET {', '.join(fields)}
        WHERE id = ?
        """,
        params,
    )

    conn.commit()
    conn.close()

def update_job_feedback(job_id: int, feedback: str, skip: bool = False):
    """작업에 피드백 저장 (메타데이터에 저장)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 기존 metadata 가져오기
    cursor.execute("SELECT metadata FROM review_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()

    if row:
        metadata = json.loads(row[0]) if row[0] else {}
        metadata.setdefault("feedback_history", []).append({
            "timestamp": datetime.utcnow().isoformat(),
            "feedback": feedback,
            "skip": bool(skip)
        })

        metadata["feedback"] = feedback
        metadata["feedback_skip"] = bool(skip)

        cursor.execute("""
            UPDATE review_jobs
            SET metadata = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (json.dumps(metadata), job_id))

        conn.commit()

    conn.close()

def reset_feedback_state(job_id: int):
    """HITL 피드백 상태 초기화"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT metadata FROM review_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()

    if row:
        metadata = json.loads(row[0]) if row[0] else {}
        updated = False

        if "feedback" in metadata:
            metadata.pop("feedback", None)
            updated = True
        if "feedback_skip" in metadata:
            metadata.pop("feedback_skip", None)
            updated = True

        if updated:
            cursor.execute("""
                UPDATE review_jobs
                SET metadata = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (json.dumps(metadata), job_id))
            conn.commit()

    conn.close()

def save_feedback(job_id: int, agent_id: str, feedback_data: dict):
    """HITL 피드백 저장"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO hitl_feedback (job_id, agent_id, feedback_data)
        VALUES (?, ?, ?)
    """, (job_id, agent_id, json.dumps(feedback_data)))

    conn.commit()
    conn.close()

def insert_sample_bp_cases():
    """샘플 BP 사례 삽입 (개발/테스트용)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    sample_cases = [
        ("웨이퍼 수율 개선 AI 모델", "예측", "제조", "메모리", "FAB팀",
         "웨이퍼 공정 중 수율이 85%로 낮음", "AI 예측 모델로 불량 패턴 조기 감지",
         "딥러닝 기반 이미지 분석으로 수율 3% 향상", "실시간 모니터링 필수", "내부문서-2024-001"),
        ("설계 검증 자동화 시스템", "분류", "설계", "S.LSI", "설계검증팀",
         "설계 검증에 수작업으로 2주 소요", "자동화 도구로 검증 시간 단축",
         "검증 시간 70% 단축 (2주→3일)", "초기 세팅 시간 확보 필요", "설계가이드-v2.3"),
        ("IT 인프라 이상 감지", "이상 감지", "IT/DX", "메모리", "IT운영팀",
         "서버 장애 발생 후 대응으로 다운타임 증가", "ML 기반 이상 징후 사전 감지",
         "평균 다운타임 50% 감소", "오탐률 관리 중요", "IT운영매뉴얼-2024")
    ]

    cursor.executemany("""
        INSERT INTO enterprise_bp_cases
        (title, tech_type, business_domain, division, organization,
         problem_as_was, solution_to_be, summary, tips, reference_docs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sample_cases)

    conn.commit()
    conn.close()
    print(f"Inserted {len(sample_cases)} sample BP cases successfully")

if __name__ == "__main__":
    init_database()
    insert_sample_bp_cases()

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

def create_job(proposal_content: str, domain: str, division: str, hitl_stages: list = None):
    """새 검토 작업 생성"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # metadata에 hitl_stages 저장
    metadata = {"hitl_stages": hitl_stages or [2]}

    cursor.execute("""
        INSERT INTO review_jobs (status, proposal_content, domain, division, metadata)
        VALUES (?, ?, ?, ?, ?)
    """, ("pending", proposal_content, domain, division, json.dumps(metadata)))

    job_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return job_id

def get_job(job_id: int):
    """작업 조회"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, status, proposal_content, domain, division, metadata
        FROM review_jobs WHERE id = ?
    """, (job_id,))

    row = cursor.fetchone()
    conn.close()

    if row:
        metadata = json.loads(row[5])
        return {
            "id": row[0],
            "status": row[1],
            "content": row[2],  # Changed key to "content" for consistency
            "proposal_content": row[2],
            "domain": row[3],
            "division": row[4],
            "metadata": metadata,
            "hitl_stages": metadata.get("hitl_stages", [2])
        }
    return None

def update_job_status(job_id: int, status: str, metadata: dict = None):
    """작업 상태 업데이트"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if metadata:
        cursor.execute("""
            UPDATE review_jobs
            SET status = ?, metadata = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, json.dumps(metadata), job_id))
    else:
        cursor.execute("""
            UPDATE review_jobs
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, job_id))

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
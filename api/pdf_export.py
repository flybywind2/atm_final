"""PDF Export API - 한글 폰트 임베딩 및 에이전트 결과 PDF화"""

from datetime import datetime
from html import escape
import io
import os
from typing import Callable, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
from xhtml2pdf import pisa

router = APIRouter()
_get_job_func: Optional[Callable[[int], dict]] = None

# ---------------------------------------------------------------------------
# Font registration helpers
# ---------------------------------------------------------------------------

FontInfo = Tuple[str, Optional[str], Optional[str]]  # (family, regular_path, bold_path)


def _register_korean_font() -> FontInfo:
    """시스템에서 사용 가능한 한글 폰트를 찾아 ReportLab과 xhtml2pdf에 등록한다."""
    font_candidates = [
        ("MalgunGothic", r"C:\\Windows\\Fonts\\malgun.ttf", r"C:\\Windows\\Fonts\\malgunbd.ttf"),
        ("AppleSDGothicNeo", "/System/Library/Fonts/AppleSDGothicNeo.ttc", None),
        ("NanumGothic", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
        ("NotoSansKR", "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.otf", "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.otf"),
        ("NotoSansCJK", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", None),
    ]

    for family, regular, bold in font_candidates:
        if not regular or not os.path.exists(regular):
            continue
        try:
            pdfmetrics.registerFont(TTFont(family, regular))
            addMapping(family, 0, 0, family)
            if bold and os.path.exists(bold):
                bold_name = f"{family}-Bold"
                pdfmetrics.registerFont(TTFont(bold_name, bold))
                addMapping(family, 1, 0, bold_name)
            else:
                addMapping(family, 1, 0, family)
            addMapping(family, 0, 1, family)
            addMapping(family, 1, 1, family)
            return (family, regular, bold if bold and os.path.exists(bold) else None)
        except Exception as exc:  # pragma: no cover
            print(f"Warning: failed to register font {family}: {exc}")
            continue

    return ("Helvetica", None, None)


FONT_FAMILY, FONT_PATH_REGULAR, FONT_PATH_BOLD = _register_korean_font()
if FONT_FAMILY == "Helvetica":
    FONT_STACK = "Helvetica, 'Malgun Gothic', 'Apple SD Gothic Neo', 'Nanum Gothic', 'Noto Sans KR', sans-serif"
else:
    FONT_STACK = f"'{FONT_FAMILY}', 'Malgun Gothic', 'Apple SD Gothic Neo', 'Nanum Gothic', 'Noto Sans KR', sans-serif"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def init_pdf_export_router(get_job_func: Callable[[int], dict]) -> None:
    global _get_job_func
    _get_job_func = get_job_func


def get_job_dependency() -> Callable[[int], dict]:
    if _get_job_func is None:
        raise HTTPException(status_code=500, detail="PDF export not initialized")
    return _get_job_func


def _html_escape(text: str) -> str:
    return escape(text or "").replace("\n", "<br>")

def _render_pdf(html_content: str) -> bytes:
    buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(html_content, dest=buffer, encoding='utf-8')
    if pisa_status.err:
        raise HTTPException(status_code=500, detail="PDF generation failed")
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def _font_face_css() -> str:
    # ReportLab에 직접 등록했으므로 CSS 선언은 생략
    return ""


def _build_html_document(title: str, sections: list[dict], job_id: int) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sections_html = []
    for idx, section in enumerate(sections, start=1):
        heading = escape(section.get("heading", f"섹션 {idx}"))
        body = _html_escape(section.get("body", ""))
        sections_html.append(
            f"""
            <h2>{heading}</h2>
            <div class=\"section\">
                <div class=\"content\">{body}</div>
            </div>
            """
        )

    font_face_css = _font_face_css()

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset=\"UTF-8\">
        <style>
            {font_face_css}
            @page {{
                size: A4;
                margin: 2cm;
            }}
            body {{
                font-family: {FONT_STACK};
                line-height: 1.6;
                color: #333;
            }}
            h1 {{
                color: #2c3e50;
                border-bottom: 3px solid #3498db;
                padding-bottom: 10px;
                margin-bottom: 20px;
            }}
            h2 {{
                color: #34495e;
                border-bottom: 2px solid #ecf0f1;
                padding-bottom: 8px;
                margin-top: 30px;
                margin-bottom: 15px;
            }}
            .section {{
                margin-bottom: 25px;
                padding: 15px;
                background-color: #f8f9fa;
                border-radius: 5px;
            }}
            .metadata {{
                font-size: 0.9em;
                color: #7f8c8d;
                margin-bottom: 30px;
            }}
            .content {{
                white-space: pre-wrap;
                word-wrap: break-word;
            }}
        </style>
    </head>
    <body>
        <h1>{escape(title)}</h1>
        <div class=\"metadata\">
            <p>Job ID: {job_id}</p>
            <p>생성일시: {generated_at}</p>
        </div>
        {''.join(sections_html)}
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@router.get("/api/export/final-recommendation/{job_id}")
async def export_final_recommendation_pdf(job_id: int, get_job=Depends(get_job_dependency)):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    metadata = job.get("metadata", {})
    agent_results = metadata.get("agent_results", {})

    sections = [
        {"heading": "1. 목표 검토", "body": agent_results.get("objective_review", "")},
        {"heading": "2. 데이터 분석", "body": agent_results.get("data_analysis", "")},
        {"heading": "3. 리스크 분석", "body": agent_results.get("risk_analysis", "")},
        {"heading": "4. ROI 추정", "body": agent_results.get("roi_estimation", "")},
        {"heading": "5. 최종 의견", "body": agent_results.get("final_recommendation") or metadata.get("final_recommendation", "")},
    ]

    if not sections[-1]["body"].strip():
        raise HTTPException(status_code=404, detail="Final recommendation not found")

    html_content = _build_html_document("AI 과제 검토 보고서 - 최종 의견", sections, job_id)
    pdf_bytes = _render_pdf(html_content)

    filename = f"final_recommendation_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/export/improved-proposal/{job_id}")
async def export_improved_proposal_pdf(job_id: int, get_job=Depends(get_job_dependency)):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    metadata = job.get("metadata", {})
    agent_results = metadata.get("agent_results", {})
    improved_proposal = agent_results.get("improved_proposal") or metadata.get("improved_proposal", "")

    if not improved_proposal.strip():
        raise HTTPException(status_code=404, detail="Improved proposal not found")

    sections = [{"heading": "개선된 제안서", "body": improved_proposal}]
    html_content = _build_html_document("AI 과제 검토 보고서 - 개선 제안", sections, job_id)
    pdf_bytes = _render_pdf(html_content)

    filename = f"improved_proposal_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

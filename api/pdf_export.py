# api/pdf_export.py - PDF Export API

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from xhtml2pdf import pisa
from datetime import datetime
import io
import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping

# Register Korean font (Malgun Gothic)
font_path = "C:\\Windows\\Fonts\\malgun.ttf"
if os.path.exists(font_path):
    try:
        pdfmetrics.registerFont(TTFont('MalgunGothic', font_path))
        addMapping('MalgunGothic', 0, 0, 'MalgunGothic')  # normal
        addMapping('MalgunGothic', 1, 0, 'MalgunGothic')  # bold
        addMapping('MalgunGothic', 0, 1, 'MalgunGothic')  # italic
        addMapping('MalgunGothic', 1, 1, 'MalgunGothic')  # bold+italic
    except Exception as e:
        print(f"Warning: Failed to register Korean font: {e}")

router = APIRouter()

# Global variable to store the get_job function
_get_job_func = None

def init_pdf_export_router(get_job_func):
    """Initialize PDF export router with database function"""
    global _get_job_func
    _get_job_func = get_job_func


def get_job_dependency():
    """Dependency to get the job function"""
    if _get_job_func is None:
        raise HTTPException(status_code=500, detail="PDF export not initialized")
    return _get_job_func


@router.get("/api/export/final-recommendation/{job_id}")
async def export_final_recommendation_pdf(job_id: int, get_job = Depends(get_job_dependency)):
    """Export final recommendation (Agent 6) as PDF"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    metadata = job.get("metadata", {})
    agent_results = metadata.get("agent_results", {})

    # Try to get from agent_results first, fallback to metadata root
    final_recommendation = agent_results.get("final_recommendation") or metadata.get("final_recommendation", "")
    objective_review = agent_results.get("objective_review") or metadata.get("objective_review", "")
    data_analysis = agent_results.get("data_analysis") or metadata.get("data_analysis", "")
    risk_analysis = agent_results.get("risk_analysis") or metadata.get("risk_analysis", "")
    roi_estimation = agent_results.get("roi_estimation") or metadata.get("roi_estimation", "")

    if not final_recommendation or final_recommendation.strip() == "":
        raise HTTPException(status_code=404, detail="Final recommendation not found")

    # HTML template for final recommendation
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4;
                margin: 2cm;
            }}
            body {{
                font-family: MalgunGothic, sans-serif;
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
        <h1>AI 과제 검토 보고서 - 최종 의견</h1>
        <div class="metadata">
            <p>Job ID: {job_id}</p>
            <p>생성일시: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        </div>

        <h2>1. 목표 검토</h2>
        <div class="section">
            <div class="content">{objective_review}</div>
        </div>

        <h2>2. 데이터 분석</h2>
        <div class="section">
            <div class="content">{data_analysis}</div>
        </div>

        <h2>3. 리스크 분석</h2>
        <div class="section">
            <div class="content">{risk_analysis}</div>
        </div>

        <h2>4. ROI 추정</h2>
        <div class="section">
            <div class="content">{roi_estimation}</div>
        </div>

        <h2>5. 최종 의견</h2>
        <div class="section">
            <div class="content">{final_recommendation}</div>
        </div>
    </body>
    </html>
    """

    # Generate PDF
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(html_content, dest=pdf_buffer)

    if pisa_status.err:
        raise HTTPException(status_code=500, detail="PDF generation failed")

    pdf_bytes = pdf_buffer.getvalue()
    pdf_buffer.close()

    # Return PDF as response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=final_recommendation_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        }
    )


@router.get("/api/export/improved-proposal/{job_id}")
async def export_improved_proposal_pdf(job_id: int, get_job = Depends(get_job_dependency)):
    """Export improved proposal (Agent 7) as PDF"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    metadata = job.get("metadata", {})
    agent_results = metadata.get("agent_results", {})

    # Try to get from agent_results first, fallback to metadata root
    improved_proposal = agent_results.get("improved_proposal") or metadata.get("improved_proposal", "")

    if not improved_proposal or improved_proposal.strip() == "":
        raise HTTPException(status_code=404, detail="Improved proposal not found")

    # HTML template for improved proposal
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4;
                margin: 2cm;
            }}
            body {{
                font-family: MalgunGothic, sans-serif;
                line-height: 1.6;
                color: #333;
            }}
            h1 {{
                color: #2c3e50;
                border-bottom: 3px solid #27ae60;
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
        <h1>AI 과제 검토 보고서 - 개선된 지원서 제안</h1>
        <div class="metadata">
            <p>Job ID: {job_id}</p>
            <p>생성일시: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        </div>

        <h2>개선된 지원서 제안</h2>
        <div class="section">
            <div class="content">{improved_proposal}</div>
        </div>
    </body>
    </html>
    """

    # Generate PDF
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(html_content, dest=pdf_buffer)

    if pisa_status.err:
        raise HTTPException(status_code=500, detail="PDF generation failed")

    pdf_bytes = pdf_buffer.getvalue()
    pdf_buffer.close()

    # Return PDF as response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=improved_proposal_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        }
    )

// static/js/app.js - 메인 애플리케이션 로직
let currentJobId = null;
let wsConnection = null;

// 입력 방식 전환
document.querySelectorAll('input[name="input-type"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
        const inputType = e.target.value;
        if (inputType === 'file') {
            document.getElementById('file-upload-container').style.display = 'block';
            document.getElementById('text-input-container').style.display = 'none';
        } else {
            document.getElementById('file-upload-container').style.display = 'none';
            document.getElementById('text-input-container').style.display = 'block';
        }
    });
});

// 제안서 제출 및 검토 시작
document.getElementById('submit-btn').addEventListener('click', async () => {
    const domain = document.getElementById('domain-select').value;
    const division = document.getElementById('division-select').value;
    const inputType = document.querySelector('input[name="input-type"]:checked').value;

    // HITL 단계 선택 수집
    const hitlStages = Array.from(document.querySelectorAll('input[name="hitl-stage"]:checked'))
        .map(checkbox => parseInt(checkbox.value));

    let formData = new FormData();
    formData.append('domain', domain);
    formData.append('division', division);
    formData.append('hitl_stages', JSON.stringify(hitlStages));

    if (inputType === 'file') {
        // 파일 업로드
        const fileInput = document.getElementById('file-input');
        const file = fileInput.files[0];

        if (!file) {
            alert('파일을 선택해주세요');
            return;
        }

        formData.append('file', file);
    } else {
        // 텍스트 직접 입력
        const textInput = document.getElementById('text-input').value.trim();

        if (!textInput) {
            alert('제안서 내용을 입력해주세요');
            return;
        }

        formData.append('text', textInput);
    }

    try {
        const response = await fetch('/api/v1/review/submit', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();
        currentJobId = result.job_id;

        console.log('✅ 제출 완료:', result);

        // 진행 상황 섹션 표시
        document.getElementById('upload-section').style.display = 'none';
        document.getElementById('progress-section').style.display = 'block';

        // WebSocket 연결
        connectWebSocket(currentJobId);
    } catch (error) {
        console.error('❌ Submit error:', error);
        alert('제출 중 오류 발생: ' + error.message);
    }
});

// WebSocket 연결 및 실시간 업데이트
function connectWebSocket(jobId) {
    const wsUrl = `ws://${window.location.host}/ws/${jobId}`;
    console.log('🔌 WebSocket 연결 중:', wsUrl);

    wsConnection = new WebSocket(wsUrl);

    wsConnection.onopen = () => {
        console.log('✅ WebSocket 연결됨');
    };

    wsConnection.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('📨 메시지 수신:', data);

        // 에이전트 상태 업데이트
        if (data.agent) {
            updateAgentStatus(data.agent, data.status);
            updateProgressMessage(data.message);
        }

        // BP 검색 결과 표시
        if (data.bp_cases) {
            showBPCases(data.bp_cases);
        }

        // HITL 인터럽트 처리
        if (data.status === 'interrupt') {
            showHITLSection(data.results);
        }

        // 최종 완료 (report가 있을 때만)
        if (data.status === 'completed' && data.report) {
            showFinalResults(data.report);
        }
    };

    wsConnection.onerror = (error) => {
        console.error('❌ WebSocket error:', error);
    };

    wsConnection.onclose = () => {
        console.log('🔌 WebSocket 연결 종료');
    };

    // Keep-alive ping (10초마다)
    setInterval(() => {
        if (wsConnection && wsConnection.readyState === WebSocket.OPEN) {
            wsConnection.send('ping');
        }
    }, 10000);
}

// 에이전트 상태 업데이트
function updateAgentStatus(agent, status) {
    const agentMap = {
        'BP_Scouter': 'agent-1-status',
        'Objective_Reviewer': 'agent-2-status',
        'Data_Analyzer': 'agent-3-status',
        'Risk_Analyzer': 'agent-4-status',
        'ROI_Estimator': 'agent-5-status',
        'Final_Generator': 'agent-6-status'
    };

    const elementId = agentMap[agent];
    if (elementId) {
        const statusElement = document.getElementById(elementId);
        if (statusElement) {
            statusElement.textContent = status === 'processing' ? '처리중...' : '완료';
            statusElement.className = 'status-badge ' + (status === 'processing' ? 'processing' : 'completed');
        }
    }
}

// 진행 메시지 업데이트
function updateProgressMessage(message) {
    const messageDiv = document.getElementById('progress-message');
    if (messageDiv) {
        messageDiv.textContent = message || '';
    }
}

// BP 검색 결과 표시
function showBPCases(bpCases) {
    const panel = document.getElementById('bp-cases-panel');
    const content = document.getElementById('bp-cases-content');

    if (!bpCases || bpCases.length === 0) {
        return;
    }

    panel.style.display = 'block';

    let html = '';
    bpCases.forEach((bpCase, index) => {
        html += `
            <div style="background: white; padding: 12px; margin-bottom: 12px; border-radius: 6px; border-left: 4px solid #4CAF50;">
                <h4 style="margin: 0 0 8px 0; color: #333; font-size: 0.95em;">
                    ${index + 1}. ${bpCase.title}
                </h4>
                <div style="font-size: 0.85em; color: #666; line-height: 1.5;">
                    <p style="margin: 4px 0;"><strong>기술 유형:</strong> ${bpCase.tech_type}</p>
                    <p style="margin: 4px 0;"><strong>도메인:</strong> ${bpCase.business_domain} | <strong>사업부:</strong> ${bpCase.division}</p>
                    <p style="margin: 4px 0;"><strong>문제 (AS-WAS):</strong> ${bpCase.problem_as_was}</p>
                    <p style="margin: 4px 0;"><strong>솔루션 (TO-BE):</strong> ${bpCase.solution_to_be}</p>
                    <p style="margin: 4px 0; color: #2196F3;"><strong>핵심 요약:</strong> ${bpCase.summary}</p>
                    ${bpCase.tips ? `<p style="margin: 4px 0; color: #FF9800;"><strong>💡 팁:</strong> ${bpCase.tips}</p>` : ''}
                </div>
            </div>
        `;
    });

    content.innerHTML = html;
}

// HITL 섹션 표시
function showHITLSection(results) {
    document.getElementById('progress-section').style.display = 'none';
    document.getElementById('hitl-section').style.display = 'block';

    // 검토 결과 표시 - 받은 데이터에 따라 다르게 표시
    const resultsDiv = document.getElementById('review-results');
    const feedbackTextarea = document.getElementById('feedback-input');
    let html = '';

    if (results.objective_review) {
        // Agent 2: Objective Reviewer 결과
        html = `
            <h3>🎯 목표 적합성 검토 결과</h3>
            <div style="background: #f5f5f5; padding: 15px; border-radius: 8px; margin: 10px 0;">
                <p style="white-space: pre-wrap;">${results.objective_review}</p>
            </div>
            <p style="color: #666; font-size: 0.9em; margin-top: 10px;">
                ℹ️ Agent 2 (Objective Reviewer)의 분석이 완료되었습니다.
                아래 제안된 피드백을 검토하고 수정하여 제출하거나 건너뛰어 다음 단계로 진행하세요.
            </p>
        `;
    } else if (results.data_analysis) {
        // Agent 3: Data Analyzer 결과
        html = `
            <h3>📊 데이터 분석 결과</h3>
            <div style="background: #e7f3ff; padding: 15px; border-radius: 8px; margin: 10px 0;">
                <p style="white-space: pre-wrap;">${results.data_analysis}</p>
            </div>
            <p style="color: #666; font-size: 0.9em; margin-top: 10px;">
                ℹ️ Agent 3 (Data Analyzer)의 분석이 완료되었습니다.
                아래 제안된 피드백을 검토하고 수정하여 제출하거나 건너뛰어 다음 단계로 진행하세요.
            </p>
        `;
    } else if (results.risk_analysis) {
        // Agent 4: Risk Analyzer 결과
        html = `
            <h3>⚠️ 리스크 분석 결과</h3>
            <div style="background: #fff3cd; padding: 15px; border-radius: 8px; margin: 10px 0;">
                <p style="white-space: pre-wrap;">${results.risk_analysis}</p>
            </div>
            <p style="color: #666; font-size: 0.9em; margin-top: 10px;">
                ℹ️ Agent 4 (Risk Analyzer)의 분석이 완료되었습니다.
                아래 제안된 피드백을 검토하고 수정하여 제출하거나 건너뛰어 다음 단계로 진행하세요.
            </p>
        `;
    } else if (results.roi_estimation) {
        // Agent 5: ROI Estimator 결과
        html = `
            <h3>💰 ROI 추정 결과</h3>
            <div style="background: #d4edda; padding: 15px; border-radius: 8px; margin: 10px 0;">
                <p style="white-space: pre-wrap;">${results.roi_estimation}</p>
            </div>
            <p style="color: #666; font-size: 0.9em; margin-top: 10px;">
                ℹ️ Agent 5 (ROI Estimator)의 분석이 완료되었습니다.
                아래 제안된 피드백을 검토하고 수정하여 제출하거나 건너뛰어 다음 단계로 진행하세요.
            </p>
        `;
    } else if (results.final_recommendation) {
        // Agent 6: Final Generator 결과
        html = `
            <h3>📋 최종 의견</h3>
            <div style="background: #e8f4f8; padding: 15px; border-radius: 8px; margin: 10px 0;">
                <p style="white-space: pre-wrap;">${results.final_recommendation}</p>
            </div>
            <p style="color: #666; font-size: 0.9em; margin-top: 10px;">
                ℹ️ Agent 6 (Final Generator)의 최종 의견이 완료되었습니다.
                아래 제안된 피드백을 검토하고 수정하여 제출하거나 건너뛰어 다음 단계로 진행하세요.
            </p>
        `;
    }

    resultsDiv.innerHTML = html;

    // 피드백 제안을 textarea에 미리 채우기
    if (results.feedback_suggestion) {
        feedbackTextarea.value = results.feedback_suggestion;
    } else {
        feedbackTextarea.value = '';
    }
}

// 피드백 제출
document.getElementById('submit-feedback-btn').addEventListener('click', async () => {
    const feedback = document.getElementById('feedback-input').value;

    try {
        await fetch(`/api/v1/review/feedback/${currentJobId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feedback })
        });

        console.log('✅ 피드백 제출 완료');

        // 다시 진행 상황으로 전환
        document.getElementById('hitl-section').style.display = 'none';
        document.getElementById('progress-section').style.display = 'block';
    } catch (error) {
        console.error('❌ Feedback error:', error);
    }
});

// 피드백 건너뛰기
document.getElementById('skip-feedback-btn').addEventListener('click', async () => {
    try {
        await fetch(`/api/v1/review/feedback/${currentJobId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feedback: '' })
        });

        console.log('⏭️ 피드백 건너뛰기');

        // 다시 진행 상황으로 전환
        document.getElementById('hitl-section').style.display = 'none';
        document.getElementById('progress-section').style.display = 'block';
    } catch (error) {
        console.error('❌ Skip error:', error);
    }
});

// 최종 결과 표시
function showFinalResults(report) {
    document.getElementById('progress-section').style.display = 'none';
    document.getElementById('hitl-section').style.display = 'none';
    document.getElementById('result-section').style.display = 'block';

    document.getElementById('final-report').innerHTML = report;
}

// PDF 다운로드
document.getElementById('download-pdf-btn').addEventListener('click', async () => {
    window.location.href = `/api/v1/review/pdf/${currentJobId}`;
});

// Accordion 토글 함수
function toggleAccordion(sectionId) {
    const content = document.getElementById(sectionId);
    const header = content.previousElementSibling;
    const icon = header.querySelector('.accordion-icon');

    if (content.style.display === 'block') {
        content.style.display = 'none';
        icon.classList.remove('rotated');
    } else {
        content.style.display = 'block';
        icon.classList.add('rotated');
    }
}

// 전역 스코프에 함수 등록 (HTML onclick에서 사용하기 위해)
window.toggleAccordion = toggleAccordion;

console.log('🚀 AI Proposal Reviewer 초기화 완료');
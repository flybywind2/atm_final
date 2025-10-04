// static/js/app.js - 메인 애플리케이션 로직
let currentJobId = null;
let wsConnection = null;
let activeFeedbackJobId = null;
let currentPageInfo = { currentPage: 1, totalPages: 1, agentName: '', agentMessage: '' };

if (window.marked && typeof window.marked.setOptions === 'function') {
    window.marked.setOptions({
        breaks: true,
        gfm: true,
        mangle: false,
        headerIds: false,
    });
}

function renderMarkdown(text) {
    if (!text) return '';
    if (window.marked) {
        if (typeof window.marked.parse === 'function') {
            return window.marked.parse(text);
        }
        if (typeof window.marked === 'function') {
            return window.marked(text);
        }
    }
    return String(text).replace(/\n/g, '<br>');
}

const AGENT_STATUS_IDS = [
    'agent-1-status',
    'agent-2-status',
    'agent-3-status',
    'agent-4-status',
    'agent-5-status',
    'agent-6-status'
];

// Floating BP Panel - Drag functionality
let isDragging = false;
let currentX;
let currentY;
let initialX;
let initialY;
let xOffset = 0;
let yOffset = 0;

const floatingPanel = document.getElementById('bp-cases-floating');
const floatingHeader = document.getElementById('bp-cases-floating-header');
const floatingContent = document.getElementById('bp-cases-floating-content');
const toggleBtn = document.getElementById('toggle-bp-btn');
const closeBtn = document.getElementById('close-bp-btn');

// Drag events
floatingHeader.addEventListener('mousedown', dragStart);
document.addEventListener('mousemove', drag);
document.addEventListener('mouseup', dragEnd);

function dragStart(e) {
    if (e.target.classList.contains('floating-btn')) return;

    initialX = e.clientX - xOffset;
    initialY = e.clientY - yOffset;

    if (e.target === floatingHeader || e.target.parentElement === floatingHeader) {
        isDragging = true;
    }
}

function drag(e) {
    if (isDragging) {
        e.preventDefault();
        currentX = e.clientX - initialX;
        currentY = e.clientY - initialY;
        xOffset = currentX;
        yOffset = currentY;

        setTranslate(currentX, currentY, floatingPanel);
    }
}

function dragEnd(e) {
    initialX = currentX;
    initialY = currentY;
    isDragging = false;
}

function setTranslate(xPos, yPos, el) {
    el.style.transform = `translate3d(${xPos}px, ${yPos}px, 0)`;
}

// Toggle collapse/expand
let isCollapsed = false;
toggleBtn.addEventListener('click', () => {
    isCollapsed = !isCollapsed;
    if (isCollapsed) {
        floatingContent.style.display = 'none';
        toggleBtn.textContent = '+';
        floatingPanel.classList.add('collapsed');
    } else {
        floatingContent.style.display = 'block';
        toggleBtn.textContent = '−';
        floatingPanel.classList.remove('collapsed');
    }
});

// Close panel
closeBtn.addEventListener('click', () => {
    floatingPanel.style.display = 'none';
});

// 입력 방식 전환
document.querySelectorAll('input[name="input-type"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
        const inputType = e.target.value;
        document.getElementById('file-upload-container').style.display = 'none';
        document.getElementById('text-input-container').style.display = 'none';
        document.getElementById('confluence-input-container').style.display = 'none';

        if (inputType === 'file') {
            document.getElementById('file-upload-container').style.display = 'block';
        } else if (inputType === 'text') {
            document.getElementById('text-input-container').style.display = 'block';
        } else if (inputType === 'confluence') {
            document.getElementById('confluence-input-container').style.display = 'block';
        }
    });
});

// Confluence 페이지 미리보기
document.getElementById('preview-confluence-btn').addEventListener('click', async () => {
    const pageId = document.getElementById('confluence-page-id').value.trim();
    const includeChildren = document.getElementById('include-child-pages').checked;
    const includeCurrent = document.getElementById('include-current-page').checked;
    const maxDepth = document.getElementById('max-depth').value;

    if (!pageId) {
        alert('Confluence 페이지 ID를 입력해주세요');
        return;
    }

    try {
        const formData = new FormData();
        formData.append('page_id', pageId);
        formData.append('include_children', includeChildren);
        formData.append('include_current', includeCurrent);
        formData.append('max_depth', maxDepth);

        const response = await fetch('/api/v1/confluence/fetch-pages', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            // 미리보기 표시
            const previewDiv = document.getElementById('confluence-preview');
            const contentDiv = document.getElementById('confluence-preview-content');

            let html = `<p><strong>총 ${result.page_count}개 페이지</strong> (전체 내용: ${result.combined_content_length.toLocaleString()} 자)</p>`;
            html += '<ul style="margin: 0; padding-left: 20px;">';
            result.pages.forEach((page, idx) => {
                html += `<li>${idx + 1}. ${page.title} (ID: ${page.id}, ${page.content_length.toLocaleString()} 자)</li>`;
            });
            html += '</ul>';

            contentDiv.innerHTML = html;
            previewDiv.style.display = 'block';
        } else {
            alert('페이지를 가져올 수 없습니다: ' + result.error);
        }
    } catch (error) {
        console.error('❌ Preview error:', error);
        alert('미리보기 중 오류 발생: ' + error.message);
    }
});

// 제안서 제출 및 검토 시작
document.getElementById('submit-btn').addEventListener('click', async () => {
    const domain = document.getElementById('domain-select').value;
    const division = document.getElementById('division-select').value;
    const inputType = document.querySelector('input[name="input-type"]:checked').value;

    // HITL 단계 선택 수집
    const hitlStages = Array.from(document.querySelectorAll('input[name="hitl-stage"]:checked'))
        .map(checkbox => parseInt(checkbox.value));

    // Sequential Thinking 활성화 여부
    const enableSequentialThinking = document.getElementById('enable-sequential-thinking').checked;

    let formData = new FormData();
    formData.append('domain', domain);
    formData.append('division', division);
    formData.append('hitl_stages', JSON.stringify(hitlStages));
    formData.append('enable_sequential_thinking', enableSequentialThinking.toString());

    let apiEndpoint = '/api/v1/review/submit';

    if (inputType === 'file') {
        // 파일 업로드
        const fileInput = document.getElementById('file-input');
        const file = fileInput.files[0];

        if (!file) {
            alert('파일을 선택해주세요');
            return;
        }

        formData.append('file', file);
    } else if (inputType === 'text') {
        // 텍스트 직접 입력
        const textInput = document.getElementById('text-input').value.trim();

        if (!textInput) {
            alert('제안서 내용을 입력해주세요');
            return;
        }

        formData.append('text', textInput);
    } else if (inputType === 'confluence') {
        // Confluence 페이지
        const pageId = document.getElementById('confluence-page-id').value.trim();
        const includeChildren = document.getElementById('include-child-pages').checked;
        const includeCurrent = document.getElementById('include-current-page').checked;
        const maxDepth = document.getElementById('max-depth').value;

        if (!pageId) {
            alert('Confluence 페이지 ID를 입력해주세요');
            return;
        }

        formData.append('page_id', pageId);
        formData.append('include_children', includeChildren);
        formData.append('include_current', includeCurrent);
        formData.append('max_depth', maxDepth);

        apiEndpoint = '/api/v1/confluence/submit-for-review';
    }

    try {
        const response = await fetch(apiEndpoint, {
            method: 'POST',
            body: formData
        });

        const result = await response.json();
        currentJobId = result.job_id;
        activeFeedbackJobId = currentJobId;

        console.log('✅ 제출 완료:', result);

        // currentPageInfo 초기화 (제출 시 받은 페이지 정보 사용)
        currentPageInfo.currentPage = 1;
        currentPageInfo.totalPages = result.page_count || 1;
        currentPageInfo.agentName = '';
        currentPageInfo.agentMessage = '';

        // 진행 상황 섹션 표시 (입력 섹션은 유지)
        document.getElementById('progress-section').style.display = 'block';

        // 초기 전체 진행 상황 표시
        updateOverallProgress(currentPageInfo.currentPage, currentPageInfo.totalPages, '', '');

        // Confluence 페이지 목록 표시
        if (result.pages && result.pages.length > 0) {
            const progressMessage = document.getElementById('progress-message');
            let pageListHtml = '<div class="confluence-page-list" style="margin-top: 15px; padding: 10px; background: #f0f8ff; border-left: 4px solid #2196F3; border-radius: 4px;">';
            pageListHtml += `<strong>📚 분석 중인 페이지 (총 ${result.page_count}개):</strong><br>`;
            pageListHtml += '<ul style="margin: 10px 0; padding-left: 20px;">';
            result.pages.forEach((page, idx) => {
                pageListHtml += `<li>${idx + 1}. ${page.title} <span style="color: #666;">(ID: ${page.id})</span></li>`;
            });
            pageListHtml += '</ul></div>';
            progressMessage.innerHTML = pageListHtml;
        }

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
    activeFeedbackJobId = jobId;

    wsConnection.onopen = () => {
        console.log('✅ WebSocket 연결됨');
    };

    wsConnection.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('📨 메시지 수신:', data);

        // 페이지별 진행 상황 업데이트
        if (data.type === 'page_progress') {
            console.log('📄 Page progress event received:', {
                current_page: data.current_page,
                total_pages: data.total_pages,
                status: data.status,
                page_title: data.page_title
            });
            updatePageProgress(data);
            // currentPageInfo 업데이트
            currentPageInfo.currentPage = data.current_page;
            currentPageInfo.totalPages = data.total_pages;
            // 전체 진행 상황도 업데이트 (단일 페이지일 때도 표시)
            updateOverallProgress(currentPageInfo.currentPage, currentPageInfo.totalPages, currentPageInfo.agentName, currentPageInfo.agentMessage);
        }

        // 에이전트 상태 업데이트
        if (data.agent) {
            updateAgentStatus(data.agent, data.status);
            // currentPageInfo에 에이전트 정보 저장
            currentPageInfo.agentName = data.agent;
            currentPageInfo.agentMessage = data.message || '';
            if (data.message) {
                updateProgressMessage(data.message);
            }
            // 에이전트 정보가 업데이트되면 전체 진행 상황도 업데이트
            updateOverallProgress(currentPageInfo.currentPage, currentPageInfo.totalPages, currentPageInfo.agentName, currentPageInfo.agentMessage);
        }

        // BP 검색 결과 표시
        if (data.bp_cases) {
            showBPCases(data.bp_cases);
        }

        // HITL 인터럽트 처리
        if (data.status === 'interrupt') {
            if (data.job_id) {
                activeFeedbackJobId = data.job_id;
            }
            showHITLSection(data.results);
        }

       // 페이지별 완료 (중간 결과)
        if (data.status === 'page_completed' && data.page_report) {
            console.log('📄 Page completed event received:', {
                current_page: data.current_page,
                total_pages: data.total_pages,
                page_title: data.page_title,
                page_id: data.page_id
            });
            appendPageResult(data);
            // 전체 진행 상황 업데이트
            currentPageInfo.currentPage = data.current_page;
            currentPageInfo.totalPages = data.total_pages;
            updateOverallProgress(currentPageInfo.currentPage, currentPageInfo.totalPages, currentPageInfo.agentName, currentPageInfo.agentMessage);
        }

       // 최종 완료 (report가 있을 때만)
        if (data.status === 'completed' && data.report) {
            showFinalResults(data.report, data.decision, data.decision_reason, data.decisions);
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
        'Final_Generator': 'agent-6-status',
        'Proposal_Improver': 'agent-7-status'
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

function resetAgentStatuses() {
    AGENT_STATUS_IDS.forEach((elementId) => {
        const statusElement = document.getElementById(elementId);
        if (statusElement) {
            statusElement.textContent = '대기중';
            statusElement.className = 'status-badge';
        }
    });

    const progressMessage = document.getElementById('progress-message');
    if (progressMessage) {
        const progressStatus = progressMessage.querySelector('.progress-status-message');
        if (progressStatus) {
            progressStatus.textContent = '';
        }
    }
}

// 페이지별 진행 상황 업데이트
function updatePageProgress(data) {
    console.log('📄 페이지 진행 상황:', data);

    const progressMessage = document.getElementById('progress-message');
    if (!progressMessage) return;

    if (data.reset_agents) {
        resetAgentStatuses();
    }

    if (data.job_id) {
        activeFeedbackJobId = data.job_id;
    }

    // 페이지 목록이 있으면 해당 페이지 상태 업데이트
    const pageList = progressMessage.querySelector('.confluence-page-list ul');
    if (pageList) {
        const pageItems = pageList.querySelectorAll('li');
        pageItems.forEach((item, idx) => {
            if (idx === data.current_page - 1) {
                // 현재 처리 중인 페이지
                if (data.status === 'processing') {
                    item.style.fontWeight = 'bold';
                    item.style.color = '#2196F3';
                    item.innerHTML = item.innerHTML.replace('</li>', ' ⏳ 분석 중...</li>').replace(' ⏳ 분석 중...', '') + ' ⏳ 분석 중...';
                } else if (data.status === 'completed') {
                    item.style.fontWeight = 'normal';
                    item.style.color = '#4CAF50';
                    item.innerHTML = item.innerHTML.replace(' ⏳ 분석 중...', '').replace(' ✅ 완료', '') + ' ✅ 완료';
                }
            }
        });
    }

    // 진행 메시지 업데이트
    let statusMsg = progressMessage.querySelector('.page-progress-status');
    if (!statusMsg) {
        statusMsg = document.createElement('div');
        statusMsg.className = 'page-progress-status';
        statusMsg.style.marginTop = '15px';
        statusMsg.style.padding = '10px';
        statusMsg.style.background = '#fff3cd';
        statusMsg.style.borderLeft = '4px solid #ffc107';
        statusMsg.style.borderRadius = '4px';
        progressMessage.appendChild(statusMsg);
    }
    statusMsg.textContent = data.message;
}

// 진행 메시지 업데이트
function updateProgressMessage(message) {
    const messageDiv = document.getElementById('progress-message');
    if (messageDiv) {
        // 기존 페이지 목록이 있으면 유지하고 메시지만 추가
        const existingPageList = messageDiv.querySelector('.confluence-page-list');
        console.log('🔍 updateProgressMessage - existingPageList:', existingPageList);
        console.log('🔍 updateProgressMessage - message:', message);

        if (existingPageList) {
            console.log('✅ 페이지 목록 유지');
            // 페이지 목록은 유지하고 진행 메시지만 업데이트
            let statusMsg = messageDiv.querySelector('.progress-status-message');
            if (!statusMsg) {
                statusMsg = document.createElement('div');
                statusMsg.className = 'progress-status-message';
                statusMsg.style.marginTop = '10px';
                messageDiv.appendChild(statusMsg);
            }
            statusMsg.textContent = message || '';
        } else {
            console.log('⚠️ 페이지 목록 없음, 전체 덮어쓰기');
            messageDiv.textContent = message || '';
        }
    }
}

// BP 검색 결과 표시 (Floating Panel)
function showBPCases(bpCases) {
    if (!bpCases || bpCases.length === 0) {
        return;
    }

    // Floating 패널 표시
    floatingPanel.style.display = 'block';

    let html = '';
    bpCases.forEach((bpCase, index) => {
        const titleHtml = bpCase.link
            ? `<h4>${index + 1}. <a href="${bpCase.link}" target="_blank" style="color: #007bff; text-decoration: none;">${bpCase.title} 🔗</a></h4>`
            : `<h4>${index + 1}. ${bpCase.title}</h4>`;

        html += `
            <div class="bp-case-item">
                ${titleHtml}
                <div class="bp-field"><strong>기술 유형:</strong> ${bpCase.tech_type}</div>
                <div class="bp-field"><strong>도메인:</strong> ${bpCase.business_domain} | <strong>사업부:</strong> ${bpCase.division}</div>
                <div class="bp-field"><strong>문제 (AS-IS):</strong> ${bpCase.problem_as_was}</div>
                <div class="bp-field"><strong>솔루션 (TO-BE):</strong> ${bpCase.solution_to_be}</div>
                <div class="bp-field bp-summary"><strong>💎 핵심 요약:</strong> ${bpCase.summary}</div>
                ${bpCase.tips ? `<div class="bp-field bp-tips"><strong>💡 팁:</strong> ${bpCase.tips}</div>` : ''}
                ${bpCase.link ? `<div class="bp-field" style="margin-top: 8px;"><a href="${bpCase.link}" target="_blank" style="color: #007bff; text-decoration: none; font-size: 0.9em;">📄 원본 문서 보기 →</a></div>` : ''}
            </div>
        `;
    });

    floatingContent.innerHTML = html;
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
                <div class="markdown-body">${renderMarkdown(results.objective_review)}</div>
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
                <div class="markdown-body">${renderMarkdown(results.data_analysis)}</div>
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
                <div class="markdown-body">${renderMarkdown(results.risk_analysis)}</div>
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
                <div class="markdown-body">${renderMarkdown(results.roi_estimation)}</div>
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
                <div class="markdown-body">${renderMarkdown(results.final_recommendation)}</div>
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
    const targetJobId = activeFeedbackJobId || currentJobId;

    try {
        await fetch(`/api/v1/review/feedback/${targetJobId}`, {
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
    const targetJobId = activeFeedbackJobId || currentJobId;

    try {
        await fetch(`/api/v1/review/feedback/${targetJobId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feedback: '', skip: true })
        });

        console.log('⏭️ 피드백 건너뛰기');

        // 다시 진행 상황으로 전환
        document.getElementById('hitl-section').style.display = 'none';
        document.getElementById('progress-section').style.display = 'block';
    } catch (error) {
        console.error('❌ Skip error:', error);
    }
});

// 페이지별 결과 추가 (실시간)
// 전체 진행 상황 업데이트
function updateOverallProgress(currentPage, totalPages, agentName = '', agentMessage = '') {
    // 진행 섹션과 결과 섹션 모두 확인
    const progressSection = document.getElementById('progress-section');
    const resultSection = document.getElementById('result-section');

    // 어느 섹션이 보이는지 확인
    const targetSection = (resultSection && resultSection.style.display !== 'none')
        ? resultSection
        : progressSection;

    if (!targetSection) return;

    // 전체 진행 상황 헤더 확인/생성
    let overallHeader = document.getElementById('overall-progress-header');
    if (!overallHeader) {
        overallHeader = document.createElement('div');
        overallHeader.id = 'overall-progress-header';
        overallHeader.className = 'overall-progress-header';
        targetSection.insertBefore(overallHeader, targetSection.firstChild);
    } else {
        // 헤더가 이미 있지만 다른 섹션에 있으면 이동
        if (overallHeader.parentElement !== targetSection) {
            targetSection.insertBefore(overallHeader, targetSection.firstChild);
        }
    }

    // 진행률 계산
    const percentage = Math.round((currentPage / totalPages) * 100);

    // 에이전트 이름 매핑
    const agentNameMap = {
        'BP_Scouter': 'BP 사례 검색',
        'Objective_Reviewer': '목표 적합성 검토',
        'Data_Analyzer': '데이터 분석',
        'Risk_Analyzer': '리스크 분석',
        'ROI_Estimator': 'ROI 추정',
        'Final_Generator': '최종 보고서 생성',
        'Proposal_Improver': '개선된 지원서 작성'
    };

    const koreanAgentName = agentNameMap[agentName] || agentName;

    // 2페이지 이상일 때만 에이전트 정보 표시
    const agentInfoHtml = (totalPages > 1 && agentName) ? `
        <div style="font-size: 0.9em; color: #fff; margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255, 255, 255, 0.3); font-weight: 500;">
            현재: ${koreanAgentName}${agentMessage ? ` - ${agentMessage}` : ''}
        </div>
    ` : '';

    overallHeader.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <span style="font-size: 1.1em; font-weight: 600;">
                📊 전체 진행 상황: ${currentPage} / ${totalPages} 페이지
            </span>
            <span style="font-size: 1em; color: #667eea; font-weight: 600;">
                ${percentage}%
            </span>
        </div>
        <div class="progress-bar-container">
            <div class="progress-bar-fill" style="width: ${percentage}%"></div>
        </div>
        ${agentInfoHtml}
    `;
}

function appendPageResult(data) {
    console.log('📄 appendPageResult called with data:', data);

    const resultSection = document.getElementById('result-section');
    const finalReport = document.getElementById('final-report');

    // 결과 섹션이 숨겨져 있으면 표시하고 초기화
    if (resultSection.style.display === 'none') {
        resultSection.style.display = 'block';
        // progress section 숨기기
        document.getElementById('progress-section').style.display = 'none';
        finalReport.innerHTML = '<h3>📄 페이지별 검토 결과</h3>';
    }

    // 이미 같은 페이지의 결과가 있는지 확인 (중복 방지)
    const existingPage = finalReport.querySelector(`[data-page-index="${data.current_page}"]`);
    if (existingPage) {
        console.log(`⚠️ Page ${data.current_page} result already exists, skipping`);
        return;
    }

    // 페이지 결과 추가
    // HTML인지 마크다운인지 확인
    const isHTML = /<[a-z][\s\S]*>/i.test(data.page_report);
    const reportContent = isHTML ? data.page_report : renderMarkdown(data.page_report);

    const pageResultHtml = `
        <div class="page-result-item" data-page-index="${data.current_page}">
            <h4>📋 ${data.page_title || `페이지 ${data.current_page}`} <small style="color: #888;">(${data.current_page}/${data.total_pages})</small></h4>
            <div class="page-decision">
                <strong>판정:</strong> ${data.page_decision || '승인'}
                ${data.page_decision_reason ? `<br><small>${data.page_decision_reason}</small>` : ''}
            </div>
            <div class="accordion-item">
                <div class="accordion-header" onclick="toggleAccordion('page-${data.current_page}-content')">
                    <span>상세 검토 내용</span>
                    <span class="accordion-icon">▼</span>
                </div>
                <div id="page-${data.current_page}-content" class="accordion-content">
                    ${isHTML ? reportContent : `<div class="markdown-body">${reportContent}</div>`}
                </div>
            </div>
        </div>
    `;

    finalReport.insertAdjacentHTML('beforeend', pageResultHtml);
    console.log(`✅ Page ${data.current_page}/${data.total_pages} result appended to DOM`);
}

// 최종 결과 표시
function showFinalResults(report, decision = null, decisionReason = null, decisions = null) {
    console.log('📊 showFinalResults called', { hasReport: !!report, hasDecision: !!decision, hasDecisions: !!decisions });

    const resultSection = document.getElementById('result-section');
    const finalReport = document.getElementById('final-report');

    // progress section 숨기기
    document.getElementById('progress-section').style.display = 'none';
    document.getElementById('hitl-section').style.display = 'none';
    resultSection.style.display = 'block';

    // 기존에 페이지별 결과가 있는지 확인
    const hasPageResults = finalReport.querySelector('.page-result-item');
    console.log('📊 Has page results:', !!hasPageResults);

    let headerHtml = '';

    if (Array.isArray(decisions) && decisions.length > 0) {
        // 다중 페이지인 경우 - 페이지별 판정 요약만 표시
        headerHtml += '<div class="decision-summary">';
        headerHtml += '<h3>📌 페이지별 자동 판정</h3>';
        headerHtml += '<ul>';
        decisions.forEach((item, index) => {
            const title = item.page_title || `페이지 ${index + 1}`;
            const decisionText = item.decision || '대기';
            const reason = item.reason ? ` - ${item.reason}` : '';
            headerHtml += `<li><strong>${title}</strong>: ${decisionText}${reason}</li>`;
        });
        headerHtml += '</ul>';
        headerHtml += '</div>';

        if (hasPageResults) {
            // 페이지별 결과가 이미 있으면 맨 위에 요약만 추가
            const existingHeader = finalReport.querySelector('.decision-summary');
            if (existingHeader) {
                existingHeader.remove(); // 기존 헤더 제거
            }
            finalReport.insertAdjacentHTML('afterbegin', headerHtml);
            console.log('✅ Added summary header to existing page results');
        } else {
            // 페이지별 결과가 없으면 헤더만 표시 (개별 페이지는 page_completed 이벤트로 추가됨)
            finalReport.innerHTML = `${headerHtml}<h3>📄 페이지별 검토 결과</h3>`;
            console.log('✅ Initialized with header (waiting for page results)');
        }
    } else if (decision) {
        // 단일 페이지인 경우 - 전체 리포트 표시
        headerHtml += '<div class="decision-summary-single">';
        headerHtml += `<h3>📌 자동 판정: ${decision}</h3>`;
        if (decisionReason) {
            headerHtml += `<p>${decisionReason}</p>`;
        }
        headerHtml += '</div>';

        const isHTML = /<[a-z][\s\S]*>/i.test(report);
        const bodyHtml = isHTML ? report : `<div class="markdown-body">${renderMarkdown(report)}</div>`;
        finalReport.innerHTML = `${headerHtml}${bodyHtml}`;
        console.log('✅ Displayed single page result');
    }

    // data-markdown 속성을 가진 요소들을 마크다운으로 렌더링
    document.querySelectorAll('[data-markdown]').forEach(element => {
        const markdownText = element.textContent;
        element.innerHTML = renderMarkdown(markdownText);
        element.classList.add('markdown-body');
    });
}

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

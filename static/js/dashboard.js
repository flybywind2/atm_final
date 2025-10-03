// static/js/dashboard.js - 대시보드 상호작용 및 CRUD
const state = {
    jobs: [],
    total: 0,
    limit: 25,
    offset: 0,
    filters: {
        status: '',
        humanDecision: '',
        llmDecision: '',
        search: ''
    },
    selectedJob: null
};

// 필터 요소
const filterForm = document.getElementById('filter-form');
const resetFiltersBtn = document.getElementById('reset-filters');
const filterStatus = document.getElementById('filter-status');
const filterHumanDecision = document.getElementById('filter-decision');
const filterLLMDecision = document.getElementById('filter-llm-decision');
const filterSearch = document.getElementById('filter-search');
const filterLimit = document.getElementById('filter-limit');

// 목록 및 카운트
const jobsTableBody = document.getElementById('jobs-table-body');
const jobsCountLabel = document.getElementById('jobs-count');

// 페이지네이션 요소
const prevPageBtn = document.getElementById('prev-page');
const nextPageBtn = document.getElementById('next-page');
const pageInfoLabel = document.getElementById('page-info');

// 생성 폼
const createForm = document.getElementById('create-job-form');
const createFeedback = document.getElementById('create-feedback');

// 모달 및 상세 요소
const detailModal = document.getElementById('detail-modal');
const detailModalClose = document.getElementById('detail-modal-close');
const detailModalBackdrop = document.getElementById('detail-modal-backdrop');
const detailForm = document.getElementById('detail-form');
const detailEmptyState = document.getElementById('detail-empty');
const detailFeedback = document.getElementById('detail-feedback');
const detailMetadata = document.getElementById('detail-metadata');
const agentResultsContainer = document.getElementById('agent-results');

const detailInputs = {
    id: document.getElementById('detail-id'),
    title: document.getElementById('detail-title'),
    domain: document.getElementById('detail-domain'),
    division: document.getElementById('detail-division'),
    status: document.getElementById('detail-status'),
    humanDecision: document.getElementById('detail-human-decision'),
    llmDecision: document.getElementById('detail-llm-decision'),
    llmReason: document.getElementById('detail-llm-reason'),
    hitl: document.getElementById('detail-hitl'),
    content: document.getElementById('detail-content')
};

const markApprovedBtn = document.getElementById('mark-approved');
const markOnHoldBtn = document.getElementById('mark-onhold');
const deleteJobBtn = document.getElementById('delete-job');

function mapDecisionLabel(value) {
    if (!value || value === 'pending') return '대기';
    return value;
}

function parseHitlStages(inputValue) {
    if (inputValue === undefined || inputValue === null) return null;
    const trimmed = inputValue.trim();
    if (trimmed === '') return [];
    return trimmed
        .split(',')
        .map((item) => item.trim())
        .filter((item) => item.length > 0)
        .map((item) => Number.parseInt(item, 10))
        .filter((num) => Number.isFinite(num));
}

function showTableLoading() {
    jobsTableBody.innerHTML = `
        <tr>
            <td colspan="9" class="empty-row">데이터를 불러오는 중입니다...</td>
        </tr>
    `;
}

function updateCountLabel() {
    jobsCountLabel.textContent = `총 ${state.total}건`;
}

function updatePaginationUI() {
    const currentPage = Math.floor(state.offset / state.limit) + 1;
    const totalPages = Math.ceil(state.total / state.limit);

    pageInfoLabel.textContent = `페이지 ${currentPage} / ${totalPages}`;

    prevPageBtn.disabled = state.offset === 0;
    nextPageBtn.disabled = state.offset + state.limit >= state.total;
}

async function fetchJobs() {
    showTableLoading();
    const params = new URLSearchParams();
    params.set('limit', String(state.limit));
    params.set('offset', String(state.offset));
    if (state.filters.status) params.set('status', state.filters.status);
    if (state.filters.humanDecision) params.set('decision', state.filters.humanDecision);
    if (state.filters.llmDecision) params.set('llm_decision', state.filters.llmDecision);
    if (state.filters.search) params.set('search', state.filters.search);

    try {
        const response = await fetch(`/api/v1/dashboard/jobs?${params.toString()}`);
        if (!response.ok) {
            throw new Error(await response.text());
        }
        const data = await response.json();
        state.jobs = data.jobs || [];
        state.total = data.total || 0;
        renderJobs();
        updateCountLabel();
        updatePaginationUI();
    } catch (error) {
        console.error('목록 조회 실패:', error);
        jobsTableBody.innerHTML = `
            <tr>
                <td colspan="9" class="empty-row error">목록을 불러오지 못했습니다.</td>
            </tr>
        `;
        updateCountLabel();
    }
}

function renderJobs() {
    if (!state.jobs.length) {
        jobsTableBody.innerHTML = `
            <tr>
                <td colspan="9" class="empty-row">조건에 맞는 작업이 없습니다.</td>
            </tr>
        `;
        return;
    }

    const rows = state.jobs.map((job) => {
        const title = job.title && job.title.trim().length ? job.title : '(제목 없음)';
        const updated = job.updated_at || '-';
        const llmDecision = mapDecisionLabel(job.llm_decision);
        const humanDecision = mapDecisionLabel(job.human_decision || job.decision);
        return `
            <tr data-job-id="${job.id}">
                <td>${job.id}</td>
                <td>${title}</td>
                <td>${job.domain || ''}</td>
                <td>${job.division || ''}</td>
                <td>${job.status || ''}</td>
                <td>${llmDecision}</td>
                <td>${humanDecision}</td>
                <td>${updated}</td>
                <td>
                    <div class="action-buttons">
                        <button class="btn-secondary" data-action="view" data-id="${job.id}">보기</button>
                        <button class="btn-success" data-action="approve" data-id="${job.id}">승인</button>
                        <button class="btn-warning" data-action="hold" data-id="${job.id}">보류</button>
                    </div>
                </td>
            </tr>
        `;
    });

    jobsTableBody.innerHTML = rows.join('');

    jobsTableBody.querySelectorAll('button[data-action]').forEach((button) => {
        button.addEventListener('click', handleRowAction);
    });
}

function openDetailModal() {
    detailModal.classList.remove('hidden');
    document.body.classList.add('modal-open');
}

function closeDetailModal() {
    detailModal.classList.add('hidden');
    document.body.classList.remove('modal-open');
    state.selectedJob = null;
    detailForm.style.display = 'none';
    detailEmptyState.style.display = 'block';
    detailFeedback.textContent = '';
    detailFeedback.classList.remove('error');
    agentResultsContainer.innerHTML = '';
    detailMetadata.textContent = '';
}

async function handleRowAction(event) {
    const target = event.currentTarget;
    const jobId = Number.parseInt(target.dataset.id, 10);
    const action = target.dataset.action;

    if (!Number.isFinite(jobId)) return;

    if (action === 'view') {
        await loadJob(jobId, { openModal: true });
    } else if (action === 'approve') {
        await quickUpdateDecision(jobId, '승인');
    } else if (action === 'hold') {
        await quickUpdateDecision(jobId, '보류');
    }
}

async function quickUpdateDecision(jobId, decision) {
    try {
        const response = await fetch(`/api/v1/dashboard/jobs/${jobId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ human_decision: decision })
        });
        if (!response.ok) {
            throw new Error(await response.text());
        }
        await fetchJobs();
        if (state.selectedJob && state.selectedJob.id === jobId) {
            await loadJob(jobId, { suppressNotification: true, openModal: true });
        }
    } catch (error) {
        console.error('결정 업데이트 실패:', error);
    }
}

async function loadJob(jobId, options = {}) {
    try {
        const response = await fetch(`/api/v1/dashboard/jobs/${jobId}`);
        if (!response.ok) {
            throw new Error(await response.text());
        }
        const data = await response.json();
        state.selectedJob = data;
        renderDetail(options);
    } catch (error) {
        console.error('상세 조회 실패:', error);
        detailFeedback.textContent = '상세 정보를 불러오지 못했습니다.';
        detailFeedback.classList.add('error');
        openDetailModal();
    }
}

function renderDetail({ suppressNotification = false, openModal: open = false } = {}) {
    const job = state.selectedJob;

    if (open) {
        openDetailModal();
    }

    if (!job) {
        detailForm.style.display = 'none';
        detailEmptyState.style.display = 'block';
        return;
    }

    detailForm.style.display = 'flex';
    detailEmptyState.style.display = 'none';

    detailInputs.id.value = job.id;
    detailInputs.title.value = job.title || '';
    detailInputs.domain.value = job.domain || '';
    detailInputs.division.value = job.division || '';
    detailInputs.status.value = job.status || 'pending';
    detailInputs.humanDecision.value = job.human_decision || job.decision || 'pending';
    detailInputs.llmDecision.value = job.llm_decision || 'pending';
    detailInputs.llmReason.value = (job.metadata?.final_decision?.reason) || '';
    detailInputs.hitl.value = (job.metadata?.hitl_stages || []).join(', ');
    detailInputs.content.value = job.proposal_content || '';

    // Confluence 링크 표시
    const confluenceLinkSection = document.getElementById('confluence-link-section');
    const confluencePageLink = document.getElementById('confluence-page-link');
    if (job.confluence_page_url) {
        confluencePageLink.href = job.confluence_page_url;
        confluenceLinkSection.style.display = 'block';
    } else {
        confluenceLinkSection.style.display = 'none';
    }

    renderAgentResults(job.metadata?.agent_results || {});
    detailMetadata.textContent = JSON.stringify(job.metadata || {}, null, 2);

    if (!suppressNotification) {
        detailFeedback.textContent = '';
        detailFeedback.classList.remove('error');
    }
}

function renderAgentResults(results) {
    if (!results || Object.keys(results).length === 0) {
        agentResultsContainer.innerHTML = '';
        agentResultsContainer.style.display = 'none';
        return;
    }

    const entries = Object.entries(results);
    const labels = {
        bp_scouter: 'BP 사례',
        objective_review: '목표 검토',
        data_analysis: '데이터 분석',
        risk_analysis: '리스크 분석',
        roi_estimation: 'ROI 추정',
        final_recommendation: '최종 의견'
    };

    let html = '<h3>에이전트 결과</h3><dl>';
    for (const [key, value] of entries) {
        const label = labels[key] || key;
        html += `<dt>${label}</dt><dd>${formatAgentValue(value)}</dd>`;
    }
    html += '</dl>';

    agentResultsContainer.innerHTML = html;
    agentResultsContainer.style.display = 'block';
}

function formatAgentValue(value) {
    if (Array.isArray(value)) {
        return value
            .map((item) => (typeof item === 'object' ? JSON.stringify(item) : String(item)))
            .join('\n');
    }
    if (typeof value === 'object') {
        return JSON.stringify(value, null, 2);
    }
    return String(value || '');
}

function collectCreatePayload() {
    const hitlStages = parseHitlStages(document.getElementById('create-hitl').value);

    return {
        title: document.getElementById('create-title').value.trim() || null,
        domain: document.getElementById('create-domain').value.trim(),
        division: document.getElementById('create-division').value.trim(),
        status: document.getElementById('create-status').value.trim() || 'pending',
        human_decision: document.getElementById('create-decision').value || 'pending',
        proposal_content: document.getElementById('create-content').value,
        hitl_stages: hitlStages,
        metadata: {}
    };
}

function collectDetailPayload() {
    const hitlStages = parseHitlStages(detailInputs.hitl.value);

    return {
        title: detailInputs.title.value,
        domain: detailInputs.domain.value,
        division: detailInputs.division.value,
        status: detailInputs.status.value,
        human_decision: detailInputs.humanDecision.value,
        proposal_content: detailInputs.content.value,
        hitl_stages: hitlStages
    };
}

filterForm.addEventListener('submit', (event) => {
    event.preventDefault();
    state.filters.status = filterStatus.value;
    state.filters.humanDecision = filterHumanDecision.value;
    state.filters.llmDecision = filterLLMDecision.value;
    state.filters.search = filterSearch.value.trim();
    state.limit = Number.parseInt(filterLimit.value, 10) || 25;
    state.offset = 0;
    fetchJobs();
});

filterLimit.addEventListener('change', () => {
    state.limit = Number.parseInt(filterLimit.value, 10) || 25;
    state.offset = 0;
    fetchJobs();
});

resetFiltersBtn.addEventListener('click', () => {
    filterStatus.value = '';
    filterHumanDecision.value = '';
    filterLLMDecision.value = '';
    filterSearch.value = '';
    filterLimit.value = '25';
    state.filters = { status: '', humanDecision: '', llmDecision: '', search: '' };
    state.limit = 25;
    state.offset = 0;
    fetchJobs();
});

createForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    createFeedback.textContent = '저장 중...';
    createFeedback.classList.remove('error');

    const payload = collectCreatePayload();

    try {
        const response = await fetch('/api/v1/dashboard/jobs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            throw new Error(await response.text());
        }
        createFeedback.textContent = '기록이 추가되었습니다.';
        createForm.reset();
        fetchJobs();
    } catch (error) {
        console.error('생성 실패:', error);
        createFeedback.textContent = '생성에 실패했습니다.';
        createFeedback.classList.add('error');
    }
});

if (detailForm) {
    detailForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!state.selectedJob) return;

        detailFeedback.textContent = '저장 중...';
        detailFeedback.classList.remove('error');

        const payload = collectDetailPayload();
        const jobId = state.selectedJob.id;

        try {
            const response = await fetch(`/api/v1/dashboard/jobs/${jobId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!response.ok) {
                throw new Error(await response.text());
            }
            detailFeedback.textContent = '저장되었습니다.';
            await fetchJobs();
            await loadJob(jobId, { suppressNotification: true });
        } catch (error) {
            console.error('업데이트 실패:', error);
            detailFeedback.textContent = '업데이트에 실패했습니다.';
            detailFeedback.classList.add('error');
        }
    });
}

markApprovedBtn.addEventListener('click', async () => {
    if (!state.selectedJob) return;
    detailInputs.humanDecision.value = '승인';
    await quickUpdateDecision(state.selectedJob.id, '승인');
});

markOnHoldBtn.addEventListener('click', async () => {
    if (!state.selectedJob) return;
    detailInputs.humanDecision.value = '보류';
    await quickUpdateDecision(state.selectedJob.id, '보류');
});

deleteJobBtn.addEventListener('click', async () => {
    if (!state.selectedJob) return;
    const confirmDelete = window.confirm('정말로 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.');
    if (!confirmDelete) return;

    try {
        const response = await fetch(`/api/v1/dashboard/jobs/${state.selectedJob.id}`, {
            method: 'DELETE'
        });
        if (!response.ok) {
            throw new Error(await response.text());
        }
        closeDetailModal();
        await fetchJobs();
    } catch (error) {
        console.error('삭제 실패:', error);
        detailFeedback.textContent = '삭제에 실패했습니다.';
        detailFeedback.classList.add('error');
    }
});

detailModalClose.addEventListener('click', closeDetailModal);
detailModalBackdrop.addEventListener('click', closeDetailModal);
window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !detailModal.classList.contains('hidden')) {
        closeDetailModal();
    }
});

prevPageBtn.addEventListener('click', () => {
    if (state.offset > 0) {
        state.offset = Math.max(0, state.offset - state.limit);
        fetchJobs();
    }
});

nextPageBtn.addEventListener('click', () => {
    if (state.offset + state.limit < state.total) {
        state.offset += state.limit;
        fetchJobs();
    }
});

fetchJobs();

# Code Refactoring - Modular Structure

## Overview
main.py has been refactored from a monolithic 816-line file into a clean modular structure.

## New Directory Structure

```
atm_claude2/
├── core/                    # Core functionality
│   ├── __init__.py
│   ├── llm.py              # LLM initialization and calling (173 lines)
│   ├── rag.py              # RAG search functions (167 lines)
│   └── websocket.py        # WebSocket connection management (38 lines)
│
├── utils/                   # Utility functions
│   ├── __init__.py
│   └── text.py             # Text processing utilities (75 lines)
│
├── agents/                  # Agent modules (existing)
│   ├── __init__.py
│   ├── utils.py
│   ├── agent1_bp_scouter.py
│   ├── agent2_objective_reviewer.py
│   ├── agent3_data_analyzer.py
│   ├── agent4_risk_analyzer.py
│   ├── agent5_roi_estimator.py
│   ├── agent6_final_generator.py
│   └── agent7_proposal_improver.py
│
├── database/                # Database layer (existing)
│   └── db.py
│
├── main.py                  # Minimal FastAPI entry point
├── static/                  # Static files
├── templates/               # HTML templates
└── .env                     # Environment variables
```

## Module Descriptions

### core/llm.py
**Purpose**: LLM initialization and calling functions

**Exports**:
- `LLM_PROVIDER` - Current LLM provider ("internal" or "ollama")
- `llm_client` - Global LLM client instance
- `init_llm()` - Initialize LLM client based on env variables
- `call_llm(prompt, enable_sequential_thinking=False, use_context7=False)` - Unified LLM calling function
- `call_ollama(prompt, ...)` - Backward compatibility wrapper
- `clean_unicode_for_cp949(text)` - Clean text for CP949 encoding

**Key Features**:
- Supports both Internal LLM and Ollama
- Tool calling support (sequential_thinking, context7_search) for Internal LLM
- Unicode cleaning for CP949 compatibility

### core/rag.py
**Purpose**: RAG (Retrieval Augmented Generation) search functions

**Exports**:
- `retrieve_from_rag(query_text, num_result_doc=5, retrieval_method="rrf")` - Core RAG search
- `rag_retrieve_bp_cases(domain, division, proposal_content="")` - BP case search wrapper for Agent 1
- `get_dummy_bp_cases(domain, division)` - Dummy data fallback

**Key Features**:
- Supports multiple retrieval methods: RRF, BM25, KNN, CC
- Automatic fallback to dummy data when RAG unavailable
- Integration with external RAG API

### core/websocket.py
**Purpose**: WebSocket connection management for real-time updates

**Exports**:
- `active_connections` - Global WebSocket connections dictionary
- `websocket_endpoint(websocket, job_id)` - WebSocket endpoint handler
- `get_active_connections()` - Get active connections registry

**Key Features**:
- Real-time progress updates to clients
- Keep-alive ping/pong mechanism
- Automatic connection cleanup on disconnect

### utils/text.py
**Purpose**: Text processing and utility functions

**Exports**:
- `_extract_json_dict(text)` - Extract JSON dictionary from LLM response
- `_truncate_for_prompt(text, limit=800)` - Truncate text for prompts
- `_generate_title_sync(content, fallback)` - Generate proposal title (sync)
- `generate_job_title(content, fallback)` - Generate proposal title (async wrapper)

**Key Features**:
- JSON extraction from mixed text responses
- Smart title generation using LLM
- Fallback to first non-empty line if LLM fails

## Migration Guide

### Before (monolithic main.py):
```python
# Everything in main.py (816 lines)
def init_llm():
    ...
def call_llm(prompt):
    ...
def retrieve_from_rag(query):
    ...
# ... 800+ more lines
```

### After (modular structure):
```python
# main.py (minimal entry point)
from core import init_llm, call_llm, websocket_endpoint
from core.rag import retrieve_from_rag, rag_retrieve_bp_cases
from utils import generate_job_title
from agents import (
    run_bp_scouter,
    run_objective_reviewer,
    # ... other agents
)

# FastAPI setup
app = FastAPI()

@app.on_event("startup")
async def startup():
    init_llm()

@app.websocket("/ws/{job_id}")
async def ws(websocket: WebSocket, job_id: str):
    await websocket_endpoint(websocket, job_id)

# API routes remain in main.py
```

## Benefits

1. **Modularity**: Each module has a single, well-defined responsibility
2. **Maintainability**: Easier to locate and modify specific functionality
3. **Testability**: Modules can be tested independently
4. **Reusability**: Core functions can be imported and reused elsewhere
5. **Scalability**: Easy to add new modules without bloating main.py
6. **Type Safety**: Clear module boundaries with documented exports
7. **Code Organization**: Logical grouping of related functions

## Import Examples

### Using LLM functions:
```python
from core import init_llm, call_llm, call_ollama

# Initialize LLM
init_llm()

# Call LLM with Sequential Thinking
response = call_llm(
    "Analyze this proposal...",
    enable_sequential_thinking=True
)

# Backward compatible Ollama call
response = call_ollama("Generate a response...")
```

### Using RAG functions:
```python
from core.rag import retrieve_from_rag, rag_retrieve_bp_cases

# Direct RAG search
hits = retrieve_from_rag("AI automation", num_result_doc=5, retrieval_method="rrf")

# BP case search for agents
bp_cases = await rag_retrieve_bp_cases("제조", "메모리", "제안서 내용...")
```

### Using utilities:
```python
from utils import generate_job_title, _extract_json_dict, _truncate_for_prompt

# Generate title
title = await generate_job_title(proposal_content, "Default Title")

# Extract JSON from LLM response
data = _extract_json_dict(llm_response)

# Truncate for prompt
short_text = _truncate_for_prompt(long_text, limit=500)
```

### Using WebSocket:
```python
from core.websocket import active_connections, websocket_endpoint

# Access active connections
if job_id in active_connections:
    ws = active_connections[job_id]
    await ws.send_json({"type": "progress", "message": "Processing..."})

# Use endpoint in FastAPI
@app.websocket("/ws/{job_id}")
async def ws(websocket: WebSocket, job_id: str):
    await websocket_endpoint(websocket, job_id)
```

## Notes

- All API routes remain in main.py (can be further modularized into `api/` if needed)
- Database functions remain in `database/db.py`
- Agent modules remain in `agents/` directory
- Existing functionality is 100% preserved
- No breaking changes to external APIs or interfaces

## Next Steps (Optional)

1. **Further API modularization**: Move API routes to `api/` directory
   - `api/jobs.py` - Job management routes
   - `api/confluence.py` - Confluence routes
   - `api/dashboard.py` - Dashboard routes
   - `api/export.py` - Export routes (PDF, improved proposal)

2. **Orchestrator layer**: Move complex orchestration logic
   - `orchestrator/review.py` - process_review() function
   - `orchestrator/confluence.py` - process_confluence_pages_sequentially()

3. **Configuration management**: Centralize configuration
   - `config/settings.py` - Environment variable management
   - `config/constants.py` - Application constants

## Line Count Summary

**Before**:
- main.py: 816 lines

**After**:
- core/llm.py: 173 lines
- core/rag.py: 167 lines
- core/websocket.py: 38 lines
- utils/text.py: 75 lines
- main.py: ~400 lines (routes and orchestration)
- **Total**: ~853 lines (slight increase due to module boilerplate, but much better organized)

**Agents** (separate modularization):
- agents/: 1,884 lines across 7 agent modules + utils

**Grand Total**: ~2,737 lines across all modules (vs ~2,700 in monolithic structure)

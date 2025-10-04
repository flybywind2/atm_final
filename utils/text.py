"""Text processing utilities"""
import json
import re
import asyncio
from typing import Optional


def _extract_json_dict(text: str) -> Optional[dict]:
    """Extract JSON dictionary from text"""
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _truncate_for_prompt(text: str, limit: int = 800) -> str:
    """Truncate text for prompt usage"""
    if not text:
        return ''
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + '...'


def _generate_title_sync(content: str, fallback: str) -> str:
    """Generate title from proposal content (synchronous)"""
    # Import here to avoid circular dependency
    from core.llm import call_llm

    prompt_body = _truncate_for_prompt(content, 600)
    prompt = f"""
당신은 제안서 제목을 만드는 전문가입니다. 아래 제안서 내용을 보고 핵심을 표현하는 25자 이하의 한국어 제목을 작성하세요.
제목은 특수문자 없이 간결하게 작성하고, JSON 형식으로만 응답하세요.

제안서:
{prompt_body}

응답 형식:
{{"title": "여기에 제목"}}
"""
    response = call_llm(prompt)
    data = _extract_json_dict(response)
    if data and isinstance(data.get('title'), str):
        title = data['title'].strip()
        if title:
            return title[:50]
    snippet_lines = (content or '').strip().splitlines()
    for line in snippet_lines:
        line = line.strip()
        if line:
            return line[:50]
    return fallback


async def generate_job_title(content: str, fallback: str) -> str:
    """Generate title from proposal content (asynchronous wrapper)"""
    return await asyncio.to_thread(_generate_title_sync, content, fallback)

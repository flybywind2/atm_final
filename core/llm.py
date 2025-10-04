"""LLM initialization and calling functions"""
import os
import uuid
import ollama


# LLM 설정 및 초기화
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
llm_client = None


def init_llm():
    """환경 변수에 따라 LLM 클라이언트 초기화"""
    global llm_client

    if LLM_PROVIDER == "internal":
        # Internal LLM 설정 (lazy import to avoid pydantic version issues)
        from langchain_openai import ChatOpenAI

        base_url = os.getenv("INTERNAL_BASE_URL")
        model = os.getenv("INTERNAL_MODEL")
        credential_key = os.getenv("INTERNAL_CREDENTIAL_KEY")
        system_name = os.getenv("INTERNAL_SYSTEM_NAME")
        user_id = os.getenv("INTERNAL_USER_ID")

        llm_client = ChatOpenAI(
            base_url=base_url,
            model=model,
            default_headers={
                "x-dep-ticket": credential_key,
                "Send-System-Name": system_name,
                "User-ID": user_id,
                "User-Type": "AD",
                "Prompt-Msg-Id": str(uuid.uuid4()),
                "Completion-Msg-Id": str(uuid.uuid4()),
            },
        )
        print(f"Internal LLM initialized: {model}")
    else:
        # Ollama 설정
        llm_client = "ollama"  # Ollama는 직접 함수로 호출
        print(f"Ollama LLM initialized: {os.getenv('OLLAMA_MODEL', 'gemma2:2b')}")


def clean_unicode_for_cp949(text: str) -> str:
    """CP949 인코딩에서 문제가 되는 유니코드 문자를 안전하게 제거"""
    if not text:
        return text

    # CP949로 인코딩 가능한 문자만 유지
    try:
        # 먼저 CP949로 인코딩 시도
        text.encode('cp949')
        return text
    except UnicodeEncodeError:
        # 인코딩 실패 시 문자별로 처리
        cleaned = []
        for char in text:
            try:
                char.encode('cp949')
                cleaned.append(char)
            except UnicodeEncodeError:
                # CP949로 인코딩할 수 없는 문자는 공백 또는 ? 로 대체
                if char.isspace():
                    cleaned.append(' ')
                else:
                    cleaned.append('?')
        return ''.join(cleaned)


def call_llm(prompt: str, enable_sequential_thinking: bool = False, use_context7: bool = False) -> str:
    """통합 LLM 호출 함수

    Args:
        prompt: LLM에 전달할 프롬프트
        enable_sequential_thinking: Sequential Thinking MCP 활성화 여부
        use_context7: Context7 tool 활성화 여부

    Returns:
        LLM 응답 문자열
    """
    try:
        if LLM_PROVIDER == "internal":
            # Internal LLM 사용 (tool calling 지원)
            if enable_sequential_thinking or use_context7:
                # Tool calling 활성화
                from langchain_core.tools import tool

                @tool
                def sequential_thinking(
                    thought: str,
                    next_thought_needed: bool,
                    thought_number: int,
                    total_thoughts: int,
                    is_revision: bool = False,
                    revises_thought: int = None,
                    branch_from_thought: int = None,
                    branch_id: str = None,
                    needs_more_thoughts: bool = False
                ) -> str:
                    """Sequential Thinking tool for step-by-step reasoning.

                    This tool helps analyze problems through a flexible thinking process.
                    Each thought can build on, question, or revise previous insights.

                    Args:
                        thought: Current thinking step
                        next_thought_needed: Whether another thought step is needed
                        thought_number: Current thought number (starts at 1)
                        total_thoughts: Estimated total thoughts needed
                        is_revision: Whether this revises previous thinking
                        revises_thought: Which thought number is being reconsidered
                        branch_from_thought: Branching point thought number
                        branch_id: Branch identifier
                        needs_more_thoughts: If more thoughts are needed

                    Returns:
                        Confirmation message
                    """
                    print(f"[Sequential Thinking {thought_number}/{total_thoughts}] {thought[:100]}...")
                    return f"Thought {thought_number} recorded. Continue: {next_thought_needed}"

                @tool
                def context7_search(library_name: str, topic: str = None) -> str:
                    """Search library documentation using Context7.

                    Args:
                        library_name: Name of the library to search
                        topic: Optional topic to focus on

                    Returns:
                        Library documentation
                    """
                    print(f"[Context7] Searching {library_name} for topic: {topic}")
                    # Context7 실제 구현은 향후 추가 (현재는 placeholder)
                    return f"Documentation for {library_name} (topic: {topic})"

                tools = []
                if enable_sequential_thinking:
                    tools.append(sequential_thinking)
                if use_context7:
                    tools.append(context7_search)

                # Tool binding
                llm_with_tools = llm_client.bind_tools(tools)
                print(f"[LLM] Tool calling enabled: sequential_thinking={enable_sequential_thinking}, context7={use_context7}")

                response = llm_with_tools.invoke(prompt)

                # Tool calls 처리
                if hasattr(response, 'tool_calls') and response.tool_calls:
                    print(f"[LLM] Tool calls detected: {len(response.tool_calls)}")
                    for tool_call in response.tool_calls:
                        print(f"  - {tool_call.get('name', 'unknown')}: {str(tool_call.get('args', {}))[:100]}")

                # Clean response content to avoid encoding issues
                content = response.content
                return clean_unicode_for_cp949(content) if content else content
            else:
                # Tool 없이 일반 호출
                response = llm_client.invoke(prompt)
                # Clean response content to avoid encoding issues
                content = response.content
                return clean_unicode_for_cp949(content) if content else content
        else:
            # Ollama 사용 (tool calling 미지원, 일반 호출)
            model = os.getenv("OLLAMA_MODEL", "gemma2:2b")
            response = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}]
            )
            print(f"LLM response: {response['message']['content']}")
            return response['message']['content']
    except Exception as e:
        print(f"LLM API 호출 실패: {e}")
        import traceback
        traceback.print_exc()
        return f"AI 응답 생성 실패: {e}"


def call_ollama(prompt: str, model: str = "gemma3:1b", enable_sequential_thinking: bool = False, use_context7: bool = False) -> str:
    """Ollama를 통한 LLM 호출 (하위 호환성을 위해 유지, 내부적으로 call_llm 사용)"""
    return call_llm(prompt, enable_sequential_thinking=enable_sequential_thinking, use_context7=use_context7)

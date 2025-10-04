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
                import json
                from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

                # Sequential thinking tool definition
                sequential_thinking_tool = {
                    "type": "function",
                    "function": {
                        "name": "sequentialthinking",
                        "description": """A detailed tool for dynamic and reflective problem-solving through thoughts.
This tool helps analyze problems through a flexible thinking process that can adapt and evolve.
Each thought can build on, question, or revise previous insights as understanding deepens.""",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "thought": {
                                    "type": "string",
                                    "description": "Your current thinking step"
                                },
                                "nextThoughtNeeded": {
                                    "type": "boolean",
                                    "description": "Whether another thought step is needed"
                                },
                                "thoughtNumber": {
                                    "type": "integer",
                                    "description": "Current thought number",
                                    "minimum": 1
                                },
                                "totalThoughts": {
                                    "type": "integer",
                                    "description": "Estimated total thoughts needed",
                                    "minimum": 1
                                },
                                "isRevision": {
                                    "type": "boolean",
                                    "description": "Whether this revises previous thinking"
                                },
                                "revisesThought": {
                                    "type": "integer",
                                    "description": "Which thought is being reconsidered"
                                },
                                "branchFromThought": {
                                    "type": "integer",
                                    "description": "Branching point thought number"
                                },
                                "branchId": {
                                    "type": "string",
                                    "description": "Branch identifier"
                                },
                                "needsMoreThoughts": {
                                    "type": "boolean",
                                    "description": "If more thoughts are needed"
                                }
                            },
                            "required": ["thought", "nextThoughtNeeded", "thoughtNumber", "totalThoughts"]
                        }
                    }
                }

                tools = []
                if enable_sequential_thinking:
                    tools.append(sequential_thinking_tool)

                # Tool binding
                llm_with_tools = llm_client.bind_tools(tools)
                print(f"[LLM] Tool calling enabled: sequential_thinking={enable_sequential_thinking}, context7={use_context7}")

                # Handle sequential thinking loop
                messages = [HumanMessage(content=prompt)]
                thoughts = []

                while True:
                    response = llm_with_tools.invoke(messages)

                    # Tool calls 처리
                    if hasattr(response, 'tool_calls') and response.tool_calls:
                        print(f"[LLM] Tool calls detected: {len(response.tool_calls)}")

                        for tool_call in response.tool_calls:
                            if tool_call['name'] == 'sequentialthinking':
                                args = tool_call['args']
                                thoughts.append(args)

                                print(f"💭 Thought {args['thoughtNumber']}/{args['totalThoughts']}: {args['thought'][:100]}...")

                                # Add tool response to messages
                                messages.append(AIMessage(content="", tool_calls=[tool_call]))
                                messages.append(ToolMessage(
                                    tool_call_id=tool_call['id'],
                                    content=json.dumps({"status": "thought_recorded"})
                                ))

                                # Check if more thoughts are needed
                                if not args.get('nextThoughtNeeded', False):
                                    print(f"✅ Thinking complete! Total thoughts: {len(thoughts)}")
                                    # Get final answer
                                    final_response = llm_client.invoke(messages + [HumanMessage(content="Please provide your final answer based on the thoughts above.")])
                                    return clean_unicode_for_cp949(final_response.content) if final_response.content else ""
                    else:
                        # No tool call, return response
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

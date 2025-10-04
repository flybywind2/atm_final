# utils/internal_vlm.py - Internal VLM (Vision Language Model) Client
import os
import base64
import uuid
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()


class InternalVLMClient:
    """
    Internal VLM 클라이언트 - vLLM 기반 gemma3:27b 모델 사용
    Base64 인코딩된 이미지를 처리
    """

    def __init__(self):
        self.enabled = os.getenv("VLM_ENABLED", "false").lower() == "true"

        # VLM 설정 (model3 사용)
        self.base_url = os.getenv("VLM_BASE_URL", "https://model3.openai.com/v1")
        self.model = os.getenv("VLM_MODEL", "gemma3:27b")
        self.credential_key = os.getenv("VLM_CREDENTIAL_KEY", "")
        self.system_name = os.getenv("VLM_SYSTEM_NAME", "System_Name")
        self.user_id = os.getenv("VLM_USER_ID", "ID")

        # API Key는 OPENAI_API_KEY 사용
        os.environ["OPENAI_API_KEY"] = os.getenv("VLM_API_KEY", "your_openai_api_key")

        if self.enabled:
            self._init_client()

    def _init_client(self):
        """VLM 클라이언트 초기화"""
        self.llm = ChatOpenAI(
            base_url=self.base_url,
            model=self.model,
            default_headers={
                "x-dep-ticket": self.credential_key,
                "Send-System-Name": self.system_name,
                "User-ID": self.user_id,
                "User-Type": "AD",
                "Prompt-Msg-Id": str(uuid.uuid4()),
                "Completion-Msg-Id": str(uuid.uuid4()),
            },
        )

    def is_enabled(self) -> bool:
        """VLM이 활성화되어 있는지 확인"""
        return self.enabled

    def encode_image_to_base64(self, image_bytes: bytes) -> str:
        """
        이미지 바이트를 Base64로 인코딩

        Args:
            image_bytes: 이미지 바이너리 데이터

        Returns:
            Base64 인코딩된 문자열
        """
        return base64.b64encode(image_bytes).decode('utf-8')

    def analyze_image(
        self,
        image_base64: str,
        prompt: str = "이 이미지를 상세히 설명해주세요.",
        max_tokens: int = 1000
    ) -> str:
        """
        Base64 인코딩된 이미지를 VLM으로 분석

        Args:
            image_base64: Base64 인코딩된 이미지
            prompt: 이미지 분석을 위한 프롬프트
            max_tokens: 최대 토큰 수

        Returns:
            VLM의 분석 결과 텍스트
        """
        if not self.enabled:
            return "[VLM이 비활성화되어 있습니다. 이미지를 분석할 수 없습니다.]"

        try:
            # LangChain HumanMessage 형식으로 이미지와 텍스트 전달
            message = HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    }
                ]
            )

            # UUID 갱신
            self.llm.default_headers["Prompt-Msg-Id"] = str(uuid.uuid4())
            self.llm.default_headers["Completion-Msg-Id"] = str(uuid.uuid4())

            response = self.llm.invoke([message])
            return response.content

        except Exception as e:
            return f"[VLM 이미지 분석 중 오류: {str(e)}]"

    def analyze_multiple_images(
        self,
        images_base64: List[str],
        prompt: str = "이 이미지들을 분석하고 설명해주세요.",
        max_tokens: int = 2000
    ) -> str:
        """
        여러 개의 Base64 인코딩된 이미지를 VLM으로 분석

        Args:
            images_base64: Base64 인코딩된 이미지 리스트
            prompt: 이미지 분석을 위한 프롬프트
            max_tokens: 최대 토큰 수

        Returns:
            VLM의 분석 결과 텍스트
        """
        if not self.enabled:
            return "[VLM이 비활성화되어 있습니다. 이미지를 분석할 수 없습니다.]"

        try:
            # 메시지 콘텐츠 구성 (텍스트 + 여러 이미지)
            content = [
                {
                    "type": "text",
                    "text": prompt
                }
            ]

            # 각 이미지를 content에 추가
            for img_base64 in images_base64:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{img_base64}"
                    }
                })

            message = HumanMessage(content=content)

            # UUID 갱신
            self.llm.default_headers["Prompt-Msg-Id"] = str(uuid.uuid4())
            self.llm.default_headers["Completion-Msg-Id"] = str(uuid.uuid4())

            response = self.llm.invoke([message])
            return response.content

        except Exception as e:
            return f"[VLM 다중 이미지 분석 중 오류: {str(e)}]"


# 싱글톤 인스턴스
internal_vlm_client = InternalVLMClient()

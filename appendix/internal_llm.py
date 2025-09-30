import uuid
from langchain_openai import ChatOpenAI
import os

os.environ["OPENAI_API_KEY"] = "your_openai_api_key"
model1_base_url = "https://model1.openai.com/v1"
model2_base_url = "https://model2.openai.com/v1"
model3_base_url = "https://model3.openai.com/v1"
model4_base_url = "https://model4.openai.com/v1"
model5_base_url = "https://model5.openai.com/v1"

model1 = "llama4 maverick"
model2 = "llama4 scout"
model3 = "gemma3"
model4 = "deepseek-r1"
model5 = "gpt-oss"

credential_key = "your_credential_key"

llm = ChatOpenAI(
    base_url=model1_base_url,
    model=model1,
    default_headers={
        "x-dep-ticket": credential_key,
        "Send-System-Name": "System_Name",
        "User-ID": "ID",
        "User-Type": "AD",
        "Prompt-Msg-Id": str(uuid.uuid4()),
        "Completion-Msg-Id": str(uuid.uuid4()),
    },
)

print(llm.invoke("Hello, how are you?"))
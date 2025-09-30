import requests
import json

url = "http://localhost:8000/insert-doc"
credential_key = "your_credential_key"
rag_api_key = "your_rag_api_key"

headers = {
    "Content-Type": "application/json",
    "x-dep-ticket": credential_key,
    "api-key": rag_api_key
}

payload = {
    "index_name": "your_index_name",
    "data": {
        "doc_id": "ABCD0001",
        "title": "Sample Document",
        "content": "This is a sample document.",
        "permission_groups": ["user"],
        "created_time": "2025-05-29T17:02:54.917+09:00",
        "additional_field": "Some additional field"
    },
    "chunk_factor": {
        "logic": "fixed_size",
        "chunk_size": 1024,
        "chunk_overlap": 128,
        "separator": " "
    }
}

response = requests.post(url, headers=headers, data=json.dumps(payload))

print(response)
print(response.text)

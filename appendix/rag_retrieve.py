import requests
import json

rrf_retrieval_url = "http://localhost:8000/retrieve-rrf"
bm25_retrieval_url = "http://localhost:8000/retrieve-bm25"
knn_retrieval_url = "http://localhost:8000/retrieve-knn"
cc_retrieval_url = "http://localhost:8000/retrieve-cc"
credential_key = "your_credential_key"
rag_api_key = "your_rag_api_key"

headers = {
    "Content-Type": "application/json",
    "x-dep-ticket": credential_key,
    "api-key": rag_api_key
}

fields = {
    "index_name": "your_index_name",
    "permission_groups": ["user"],
    "query_text": "Sample query",
    "num_result_doc": 5,
    "fields_exclude": ["v_merge_title_content"],
    "filter": {
        "example_field_name": ["png"]
    }
}

json_data = json.dumps(fields)
response = requests.request("POST",rrf_retrieval_url,headers=headers,data=json_data)
# return은  Elasticsearch 응답
print(response)
print(response.text)

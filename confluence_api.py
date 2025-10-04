# confluence_api.py - Confluence Data Center API 연동
import os
import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import urllib3
from typing import List, Tuple
from utils.internal_vlm import internal_vlm_client

# SSL 경고 비활성화 (자체 서명 인증서 사용 시)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

CONFLUENCE_BASE_URL = os.getenv("CONFLUENCE_BASE_URL", "")
CONFLUENCE_USERNAME = os.getenv("CONFLUENCE_USERNAME", "")
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN", "")

def get_auth():
    """Confluence 인증 정보 반환"""
    return HTTPBasicAuth(CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN)

def get_page_images(page_id: str, html_content: str) -> List[bytes]:
    """페이지에서 이미지 추출"""
    images = []

    if not internal_vlm_client.is_enabled():
        return images

    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # 이미지 태그 찾기 (Confluence는 ac:image와 img 태그 사용)
        img_tags = soup.find_all(['img', 'ac:image'])

        for img in img_tags:
            # 이미지 URL 추출
            image_url = None

            # <img src="..."> 형태
            if img.name == 'img' and img.get('src'):
                image_url = img.get('src')

            # <ac:image><ri:attachment ri:filename="..."/></ac:image> 형태
            elif img.name == 'ac:image':
                attachment = img.find('ri:attachment')
                if attachment and attachment.get('ri:filename'):
                    filename = attachment.get('ri:filename')
                    # Confluence attachment URL 구성
                    image_url = f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}/child/attachment"
                    # 실제 첨부 파일 다운로드 URL 가져오기
                    image_url = get_attachment_download_url(page_id, filename)

            if image_url:
                # 상대 URL을 절대 URL로 변환
                if image_url.startswith('/'):
                    image_url = f"{CONFLUENCE_BASE_URL}{image_url}"

                # 이미지 다운로드
                try:
                    img_response = requests.get(image_url, auth=get_auth(), timeout=30, verify=False)
                    img_response.raise_for_status()
                    images.append(img_response.content)
                except Exception as img_err:
                    print(f"이미지 다운로드 실패 ({image_url}): {str(img_err)}")
                    continue

    except Exception as e:
        print(f"이미지 추출 중 오류: {str(e)}")

    return images


def get_attachment_download_url(page_id: str, filename: str) -> str:
    """Confluence 첨부파일 다운로드 URL 가져오기"""
    try:
        url = f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}/child/attachment"
        params = {"filename": filename}

        response = requests.get(url, params=params, auth=get_auth(), timeout=30, verify=False)
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        if results:
            # 첨부파일의 다운로드 링크 추출
            download_link = results[0].get("_links", {}).get("download")
            if download_link:
                return f"{CONFLUENCE_BASE_URL}{download_link}"

        return ""
    except Exception as e:
        print(f"첨부파일 URL 가져오기 실패: {str(e)}")
        return ""


def get_page_content(page_id: str) -> dict:
    """특정 페이지의 내용 가져오기"""
    try:
        url = f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}"
        params = {
            "expand": "body.storage,version,ancestors"
        }

        response = requests.get(url, params=params, auth=get_auth(), timeout=30, verify=False)
        response.raise_for_status()

        data = response.json()

        # HTML에서 텍스트 추출
        html_content = data.get("body", {}).get("storage", {}).get("value", "")
        soup = BeautifulSoup(html_content, 'html.parser')
        text_content = soup.get_text(separator='\n', strip=True)

        # 이미지 추출
        images = get_page_images(page_id, html_content)

        return {
            "id": data.get("id"),
            "title": data.get("title"),
            "content": text_content,
            "html": html_content,
            "images": images,
            "version": data.get("version", {}).get("number"),
            "space": data.get("space", {}).get("key"),
        }
    except Exception as e:
        print(f"페이지 {page_id} 가져오기 실패: {str(e)}")
        return None

def get_child_pages(page_id: str) -> list:
    """특정 페이지의 하위 페이지 목록 가져오기"""
    try:
        url = f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}/child/page"
        params = {
            "expand": "version",
            "limit": 100  # 최대 100개
        }

        response = requests.get(url, params=params, auth=get_auth(), timeout=30, verify=False)
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        child_pages = []
        for page in results:
            child_pages.append({
                "id": page.get("id"),
                "title": page.get("title"),
                "type": page.get("type")
            })

        return child_pages
    except Exception as e:
        print(f"하위 페이지 가져오기 실패: {str(e)}")
        return []

def get_pages_recursively(page_id: str, include_current: bool = True, max_depth: int = 3, current_depth: int = 0) -> list:
    """페이지와 하위 페이지를 재귀적으로 가져오기"""
    print(f"[DEBUG] get_pages_recursively called: page_id={page_id}, current_depth={current_depth}, max_depth={max_depth}, include_current={include_current}")

    pages = []

    # 현재 페이지 포함
    if include_current or current_depth > 0:
        print(f"[DEBUG] Fetching current page: {page_id}")
        current_page = get_page_content(page_id)
        if current_page:
            print(f"[DEBUG] Current page fetched: {current_page.get('title')}")
            pages.append(current_page)
        else:
            print(f"[DEBUG] Current page is None")

    # 하위 페이지 가져오기 (max_depth 체크는 재귀 호출 전에)
    if current_depth < max_depth:
        print(f"[DEBUG] Fetching child pages for: {page_id}")
        child_pages = get_child_pages(page_id)
        print(f"[DEBUG] Found {len(child_pages)} child pages")

        for child in child_pages:
            child_id = child.get("id")
            child_title = child.get("title")
            print(f"[DEBUG] Processing child: {child_title} (ID: {child_id})")
            # 재귀적으로 하위 페이지의 내용과 그 하위 페이지들 가져오기
            sub_pages = get_pages_recursively(child_id, include_current=True, max_depth=max_depth, current_depth=current_depth + 1)
            print(f"[DEBUG] Got {len(sub_pages)} pages from child {child_title}")
            pages.extend(sub_pages)
    else:
        print(f"[DEBUG] Max depth reached, skipping child page fetch")

    print(f"[DEBUG] Returning {len(pages)} total pages from page_id={page_id}")
    return pages

def search_pages_by_query(query: str, space_key: str = None, limit: int = 10) -> list:
    """CQL을 사용하여 페이지 검색"""
    try:
        url = f"{CONFLUENCE_BASE_URL}/rest/api/content/search"

        # CQL 쿼리 구성
        cql = f"type=page and text~'{query}'"
        if space_key:
            cql += f" and space='{space_key}'"

        params = {
            "cql": cql,
            "limit": limit,
            "expand": "version"
        }

        response = requests.get(url, params=params, auth=get_auth(), timeout=30, verify=False)
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        pages = []
        for page in results:
            pages.append({
                "id": page.get("id"),
                "title": page.get("title"),
                "space": page.get("space", {}).get("key")
            })

        return pages
    except Exception as e:
        print(f"페이지 검색 실패: {str(e)}")
        return []

def combine_pages_content(pages: list) -> str:
    """여러 페이지의 내용을 하나의 문자열로 결합"""
    combined = []

    for idx, page in enumerate(pages, 1):
        combined.append(f"{'='*80}")
        combined.append(f"페이지 {idx}: {page.get('title', 'Unknown')}")
        combined.append(f"ID: {page.get('id', 'Unknown')}")
        combined.append(f"{'='*80}")
        combined.append(page.get('content', ''))
        combined.append("\n")

    return "\n".join(combined)

if __name__ == "__main__":
    # 테스트
    print("Confluence API 테스트")

    test_page_id = "123456"  # 테스트용 페이지 ID

    # 페이지 내용 가져오기
    page = get_page_content(test_page_id)
    if page:
        print(f"✅ 페이지 제목: {page['title']}")
        print(f"✅ 내용 길이: {len(page['content'])} chars")

    # 하위 페이지 가져오기
    children = get_child_pages(test_page_id)
    print(f"✅ 하위 페이지 수: {len(children)}")
    for child in children:
        print(f"  - {child['title']} (ID: {child['id']})")

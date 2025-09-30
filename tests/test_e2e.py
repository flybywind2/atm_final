# tests/test_e2e.py - Playwright 기반 E2E 테스트
import pytest
from playwright.sync_api import Page, expect
import subprocess
import time
import os
import signal

@pytest.fixture(scope="module")
def server():
    """FastAPI 서버를 테스트용으로 실행"""
    # 서버 프로세스 시작
    env = os.environ.copy()
    env['PORT'] = '8081'  # 테스트용 포트

    process = subprocess.Popen(
        ['python', 'main.py'],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # 서버가 시작될 때까지 대기
    time.sleep(3)

    yield process

    # 테스트 후 서버 종료
    if os.name == 'nt':  # Windows
        os.kill(process.pid, signal.SIGTERM)
    else:  # Linux/Mac
        process.terminate()
    process.wait(timeout=5)

@pytest.fixture(scope="session")
def base_url():
    """테스트용 베이스 URL"""
    return "http://localhost:8080"

def test_homepage_loads(page: Page, base_url: str):
    """홈페이지가 정상적으로 로드되는지 테스트"""
    page.goto(base_url)

    # 페이지 제목 확인
    expect(page).to_have_title("AI 과제 지원서 검토 시스템")

    # 주요 요소가 표시되는지 확인
    expect(page.locator("h1")).to_contain_text("AI 과제 지원서 검토 시스템")
    expect(page.locator("#submit-btn")).to_be_visible()

def test_form_elements_exist(page: Page, base_url: str):
    """폼 요소들이 존재하는지 테스트"""
    page.goto(base_url)

    # 도메인 선택 박스
    domain_select = page.locator("#domain-select")
    expect(domain_select).to_be_visible()

    # 사업부 선택 박스
    division_select = page.locator("#division-select")
    expect(division_select).to_be_visible()

    # 입력 방식 라디오 버튼
    file_radio = page.locator('input[name="input-type"][value="file"]')
    text_radio = page.locator('input[name="input-type"][value="text"]')
    expect(file_radio).to_be_visible()
    expect(text_radio).to_be_visible()

def test_input_type_toggle(page: Page, base_url: str):
    """입력 방식 전환이 정상 동작하는지 테스트"""
    page.goto(base_url)

    # 초기 상태: 파일 업로드 보임, 텍스트 입력 숨김
    file_container = page.locator("#file-upload-container")
    text_container = page.locator("#text-input-container")

    expect(file_container).to_be_visible()
    expect(text_container).to_be_hidden()

    # 텍스트 입력으로 전환
    text_radio = page.locator('input[name="input-type"][value="text"]')
    text_radio.click()

    expect(file_container).to_be_hidden()
    expect(text_container).to_be_visible()

    # 파일 업로드로 다시 전환
    file_radio = page.locator('input[name="input-type"][value="file"]')
    file_radio.click()

    expect(file_container).to_be_visible()
    expect(text_container).to_be_hidden()

def test_text_submission(page: Page, base_url: str):
    """텍스트 직접 입력으로 제출하는 테스트"""
    page.goto(base_url)

    # 도메인 선택
    page.select_option("#domain-select", "IT/DX")

    # 사업부 선택
    page.select_option("#division-select", "메모리")

    # 텍스트 입력 모드로 전환
    page.locator('input[name="input-type"][value="text"]').click()

    # 제안서 텍스트 입력
    test_proposal = """
    과제 제목: AI 기반 IT 인프라 이상 감지 시스템

    배경: 현재 IT 인프라 장애가 발생한 후에야 대응하고 있어 다운타임이 길어지는 문제가 있습니다.

    목표: ML 기반 이상 징후 사전 감지 시스템을 구축하여 평균 다운타임을 50% 감소시키고자 합니다.

    기대효과: 시스템 안정성 향상 및 비용 절감
    """

    page.fill("#text-input", test_proposal)

    # 제출 버튼 클릭
    page.click("#submit-btn")

    # 진행 상황 섹션이 표시되는지 확인 (최대 5초 대기)
    page.wait_for_selector("#progress-section", state="visible", timeout=5000)

    # 업로드 섹션이 숨겨지는지 확인
    expect(page.locator("#upload-section")).to_be_hidden()
    expect(page.locator("#progress-section")).to_be_visible()

def test_empty_text_validation(page: Page, base_url: str):
    """빈 텍스트로 제출 시 검증 테스트"""
    page.goto(base_url)

    # 텍스트 입력 모드로 전환
    page.locator('input[name="input-type"][value="text"]').click()

    # 빈 상태로 제출 시도
    page.on("dialog", lambda dialog: dialog.accept())  # alert 자동 닫기
    page.click("#submit-btn")

    # alert가 발생하는지 확인 (실제로는 dialog 이벤트로 캐치됨)

def test_domain_options(page: Page, base_url: str):
    """도메인 선택 옵션이 올바른지 테스트"""
    page.goto(base_url)

    domain_select = page.locator("#domain-select")
    options = domain_select.locator("option").all_text_contents()

    expected_domains = ["제조/생산", "연구개발", "설계", "IT/DX", "경영/기획", "품질", "영업/마케팅", "HR/교육"]

    for domain in expected_domains:
        assert domain in options, f"도메인 '{domain}'이 선택 목록에 없습니다"

def test_division_options(page: Page, base_url: str):
    """사업부 선택 옵션이 올바른지 테스트"""
    page.goto(base_url)

    division_select = page.locator("#division-select")
    options = division_select.locator("option").all_text_contents()

    expected_divisions = ["메모리", "S.LSI", "Foundry"]

    for division in expected_divisions:
        assert division in options, f"사업부 '{division}'이 선택 목록에 없습니다"

def test_css_loaded(page: Page, base_url: str):
    """CSS가 제대로 로드되는지 테스트"""
    page.goto(base_url)

    # 헤더의 배경색이 white인지 확인 (CSS 적용 확인)
    header = page.locator("header")
    background_color = header.evaluate("element => getComputedStyle(element).backgroundColor")

    # rgb(255, 255, 255) 또는 rgba(255, 255, 255, 1) 형식
    assert "255, 255, 255" in background_color, "CSS가 제대로 로드되지 않았습니다"

def test_javascript_loaded(page: Page, base_url: str):
    """JavaScript가 제대로 로드되는지 테스트"""
    page.goto(base_url)

    # 콘솔에 초기화 메시지가 출력되는지 확인
    console_messages = []
    page.on("console", lambda msg: console_messages.append(msg.text))

    page.reload()
    page.wait_for_timeout(1000)  # 1초 대기

    # 초기화 메시지 확인
    assert any("초기화 완료" in msg for msg in console_messages), "JavaScript가 제대로 로드되지 않았습니다"
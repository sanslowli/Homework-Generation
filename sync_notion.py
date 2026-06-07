"""
sync_notion.py — Notion 예문 DB → Google Sheet SentenceBank 동기화

[사용법]
    환경변수 설정 후 실행:
        export NOTION_TOKEN=ntn_...
        python sync_notion.py

    또는 GitHub Actions에서 자동 실행 (NOTION_TOKEN secret 필요).

[동작]
1. 노션 빙고판(챕터) DB에서 챕터별 구간 매핑 가져옴 (601(S), 602(S), 603(S) 등)
2. 노션 예문 DB의 모든 행 읽음 (페이지네이션 자동 처리)
3. 각 행의 제목 "603@박대호" 형식에서 chapter, owner 파싱
4. 1~16번 그림칸 컬럼 순회:
     - 회색(첨삭 주석), 취소선 부분 자동 제거
     - 빈 셀 skip
     - 챕터 매핑으로 section 결정
5. SentenceBank 시트에 전체 교체 방식으로 기록

[필요 환경]
- NOTION_TOKEN 환경변수 (노션 integration access token)
- service_key.json (Google service account 키)
- pip install requests gspread oauth2client
"""

import os
import re
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials


# ─── 설정 ───
NOTION_VERSION = "2025-09-03"  # data sources API 지원 버전
NOTION_API_BASE = "https://api.notion.com/v1"

CHAPTER_DS_ID = "efb7798d-72c2-4b2a-bfa9-8161f5c5dc3f"   # 빙고판(챕터)
SENTENCE_DS_ID = "1c31c5e2-fb57-80a4-a087-000b7b455705"  # 예문 DB

SHEET_NAME = "Syntax Pitching DB"
WORKSHEET_NAME = "SentenceBank"
HEADERS_ROW = ["Chapter", "Pane", "Owner", "Section", "Sentence", "LastSyncedAt"]

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_KEY_PATH = SCRIPT_DIR / "service_key.json"

MAX_PANES = 16                 # 예문 DB 컬럼 최대 1~16
RATE_LIMIT_DELAY = 0.34        # 노션 API 3 req/sec 안전선

# 제목 패턴: "603@박대호", "603S@박대호" 등
TITLE_PATTERN = re.compile(r"^(\d+S?)@(.+)$")

# 점수 메모 찌꺼기 패턴: ": 80", "소서연: 80", "Untitled: 80", "박대호 : 90" 등
# 줄 전체가 [이름(선택)] + 콜론 + 숫자 형태일 때만 매칭
SCORE_STAMP_PATTERN = re.compile(r"^\s*[\w가-힣\s]*:\s*\d{1,4}\s*$")


# ─── 로깅 ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── 노션 API ───
def get_notion_token() -> str:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        log.error("❌ NOTION_TOKEN 환경변수가 비어있습니다.")
        sys.exit(1)
    return token


def notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_notion_token()}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def query_data_source(ds_id: str) -> list:
    """Notion data source의 모든 페이지를 페이지네이션으로 가져옴."""
    url = f"{NOTION_API_BASE}/data_sources/{ds_id}/query"
    all_pages = []
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(url, headers=notion_headers(), json=body, timeout=30)
        if r.status_code != 200:
            log.error("❌ 노션 API 에러 (%s): %s", r.status_code, r.text[:400])
            r.raise_for_status()
        data = r.json()
        all_pages.extend(data.get("results", []))
        time.sleep(RATE_LIMIT_DELAY)
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return all_pages


# ─── 페이지 파싱 ───
def extract_title(page: dict) -> str:
    """페이지의 title 속성에서 plain text 추출."""
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            rich = prop.get("title", [])
            return "".join(r.get("plain_text", "") for r in rich).strip()
    return ""


def clean_rich_text(rich_text: list) -> str:
    """rich_text 배열에서 비-콘텐츠 요소 제거하고 깨끗한 텍스트 반환.

    제외 대상:
      - mention 타입 (페이지/사용자/날짜 멘션 → "Untitled : 80" 같은 찌꺼기 방지)
      - equation 타입
      - 회색 글씨 (첨삭 주석)
      - 배경색 글씨 (심화/기초/통합 같은 라벨 태그)
      - 취소선 (학생 원본 중 선생님이 그어버린 부분)
      - ✅ / ☑️ 마커 (승인 표시지 콘텐츠 아님)
    """
    parts = []
    for item in rich_text:
        # text 타입만 처리. mention/equation 등은 모두 제외.
        if item.get("type") != "text":
            continue
        ann = item.get("annotations", {})
        color = ann.get("color", "default")
        # 회색 글씨 = 첨삭 주석
        if color == "gray":
            continue
        # 배경색 = 라벨 태그 (심화·기초·통합 등)
        if color.endswith("_background"):
            continue
        if ann.get("strikethrough"):
            continue
        text = item.get("plain_text") or item.get("text", {}).get("content", "")
        if text:
            parts.append(text)
    out = "".join(parts)
    # 승인 마커 제거 (콘텐츠가 아니라 메타정보)
    for marker in ("✅", "☑️", "✔️"):
        out = out.replace(marker, "")
    # 빈 줄 + 점수 메모 찌꺼기 줄 제거 (예: ": 80", "소서연: 80")
    lines = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if SCORE_STAMP_PATTERN.match(ln):
            continue
        lines.append(ln)
    return "\n".join(lines).strip()


def has_approval_marker(rich_text: list) -> bool:
    """셀 안에 ✅/☑️/✔️ 같은 승인 마커가 있는지.

    승인 마커 없는 셀 = 아직 미완성(템플릿 단계, S+V 같은 변수가 그대로 남아있음)
    → SentenceBank에 반영하지 않음.
    """
    for item in rich_text:
        text = item.get("plain_text", "")
        if "✅" in text or "☑️" in text or "✔️" in text:
            return True
    return False


# ─── 챕터 매핑 빌드 ───
def build_chapter_mapping(chapter_pages: list) -> dict:
    """빙고판 페이지에서 챕터별 구간 매핑 dict 빌드.

    Returns: {
        "601(S)": {1: (1,3), 2: (4,6), 3: (7,9), 4: (10,12)},
        "602(S)": {1: (1,4), 2: (5,6), 3: (7,9), 4: (10,12)},
        "603(S)": {1: (1,5), 2: (6,8), 3: (9,12)},
        ...
    }
    """
    mapping = {}
    for page in chapter_pages:
        title = extract_title(page)
        if not title:
            continue
        props = page.get("properties", {})
        sections = {}
        for sec in range(1, 5):
            start_prop = props.get(f"구간{sec} 시작칸", {})
            end_prop = props.get(f"구간{sec} 끝칸", {})
            start = start_prop.get("number")
            end = end_prop.get("number")
            if start is not None and end is not None:
                sections[sec] = (int(start), int(end))
        if sections:
            mapping[title] = sections
            log.info("📋 %s 매핑: %s", title, sections)
    return mapping


def find_section(chapter: str, pane: int, chapter_mapping: dict):
    """주어진 chapter+pane이 몇 번 구간에 속하는지.

    "603" 또는 "603S" → "603(S)" 매핑을 공유.
    """
    base = chapter.rstrip("S")
    pair_key = f"{base}(S)"
    sections = chapter_mapping.get(pair_key) or chapter_mapping.get(chapter)
    if not sections:
        return None
    for sec_num, (start, end) in sections.items():
        if start <= pane <= end:
            return sec_num
    return None


# ─── 예문 추출 ───
def extract_sentences(sentence_pages: list, chapter_mapping: dict) -> list:
    """예문 페이지 리스트에서 SentenceBank 행(리스트) 추출."""
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    skipped_titles = []

    for page in sentence_pages:
        title = extract_title(page)
        m = TITLE_PATTERN.match(title)
        if not m:
            skipped_titles.append(title)
            continue
        chapter = m.group(1)
        owner = m.group(2).strip()

        props = page.get("properties", {})
        for pane_num in range(1, MAX_PANES + 1):
            prop = props.get(str(pane_num))
            if not prop:
                continue
            rich = prop.get("rich_text", [])
            # ✅ 등 승인 마커가 없으면 미완성/템플릿으로 간주 → skip
            if not has_approval_marker(rich):
                continue
            sentence = clean_rich_text(rich)
            if not sentence:
                continue
            section = find_section(chapter, pane_num, chapter_mapping)
            rows.append([
                chapter,
                pane_num,
                owner,
                section if section is not None else "",
                sentence,
                now,
            ])

    if skipped_titles:
        log.warning("⚠️ 제목 패턴 안 맞아 skip된 행: %d개", len(skipped_titles))
        for t in skipped_titles[:5]:
            log.warning("   skip 예: %r", t)

    rows.sort(key=lambda r: (r[0], r[2], r[1]))  # Chapter → Owner → Pane
    return rows


# ─── 시트 기록 ───
def write_to_sheet(rows: list) -> None:
    """SentenceBank 시트에 전체 교체 방식으로 기록."""
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        str(SERVICE_KEY_PATH), scope
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open(SHEET_NAME)

    try:
        ws = spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        log.info("SentenceBank 시트가 없어 새로 만듭니다.")
        ws = spreadsheet.add_worksheet(title=WORKSHEET_NAME, rows=2000, cols=10)

    ws.clear()
    ws.update("A1", [HEADERS_ROW] + rows)
    log.info("📤 SentenceBank 시트에 헤더 + %d행 기록 완료", len(rows))


# ─── 메인 ───
def main():
    log.info("▶ 노션 동기화 시작")

    log.info("1/3 빙고판 DB에서 챕터 매핑 가져오는 중...")
    chapter_pages = query_data_source(CHAPTER_DS_ID)
    log.info("   → 챕터 페이지 %d개 발견", len(chapter_pages))
    chapter_mapping = build_chapter_mapping(chapter_pages)
    if not chapter_mapping:
        log.warning("⚠️ 챕터 매핑이 비어있음. 빙고판 DB의 구간1~4 시작/끝칸 채워야 함.")

    log.info("2/3 예문 DB에서 모든 행 가져오는 중...")
    sentence_pages = query_data_source(SENTENCE_DS_ID)
    log.info("   → 예문 페이지 %d개 발견", len(sentence_pages))

    log.info("3/3 데이터 정제 + SentenceBank 시트 기록...")
    rows = extract_sentences(sentence_pages, chapter_mapping)
    log.info("   → 추출된 문장: %d개", len(rows))
    write_to_sheet(rows)

    log.info("✅ 동기화 완료")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log.exception("❌ 치명적 오류: %s", e)
        sys.exit(1)

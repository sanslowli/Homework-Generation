"""
sync_notion.py — Notion 예문 DB → Supabase `sentence_bank` 동기화

[사용법]
    환경변수 설정 후 실행:
        export NOTION_TOKEN=ntn_...
        export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...
        python sync_notion.py

    또는 GitHub Actions에서 자동 실행 (위 secret 3종 필요).

[동작]
1. 노션 빙고판(챕터) DB에서 챕터별 구간 매핑 가져옴 (601(S), 602(S), 603(S) 등)
2. 노션 예문 DB의 모든 행 읽음 (페이지네이션 자동 처리)
3. 각 행의 제목 "603@박대호" 형식에서 chapter, owner 파싱
4. 1~16번 그림칸 컬럼 순회:
     - 회색(첨삭 주석), 취소선 부분 자동 제거
     - 빈 셀 skip
     - 챕터 매핑으로 section 결정
5. Supabase `sentence_bank`에 upsert → 성공했을 때만 이번 챕터의 옛 행 정리

[구글 시트 쓰기는 폐선(2026-09-14, 시트 폐선 2단계)]
    0822에 웹앱 읽기가 DB로, 0907에 음원 생성 읽기원·웹앱 폴백이 닫히면서 시트는
    쓰기만 남은 되돌리기 창이었다. 이제 **DB 단독**이고 시트는 동결 백업(쓰기 0).
    ⟹ DB 쓰기가 실패하면 받아줄 곳이 없으므로 **소리 내어 죽는다**(exit 1).

[읽기원 스위치 — SENTENCE_SOURCE (2026-10-01, 노션 절연 4번 칸 준비)]
    SENTENCE_SOURCE=db  → 노션 대신 Supabase `sentence_page`+`sentence`(웹앱 0028 표)에서 읽는다.
                          구간 경계도 노션 빙고판이 아니라 `chapter` 표(sec1~4_start/end)에서.
    그 밖(미설정 포함) → 종전 노션 경로 그대로(기본값).
    두 경로의 산출(chapter·pane·owner·section·sentence)은 같아야 한다 — segs를 노션 rich_text 모양으로
    되돌려 **같은** clean_rich_text·has_approval_marker를 태운다(색 계약·승인 게이트 두 벌 금지).
    GitHub Actions에선 repository variable `SENTENCE_SOURCE`로 넘어온다(비어 있으면 노션).

[드라이런]
    python sync_notion.py --dry-run [--out rows.json]
    DB에 쓰지 않고 추출 결과만 본다. --out 이면 행을 JSON으로 떨군다(두 읽기원 대조용).

[필요 환경]
- NOTION_TOKEN 환경변수 (노션 integration access token) — SENTENCE_SOURCE=db 면 불필요
- SUPABASE_URL · SUPABASE_SERVICE_ROLE_KEY 환경변수
- pip install requests
"""

import os
import re
import sys
import json
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta

import requests

import supa  # 정본 원장 = Supabase(시트 폐선 2단계, 0914)


# ─── 설정 ───
NOTION_VERSION = "2025-09-03"  # data sources API 지원 버전
NOTION_API_BASE = "https://api.notion.com/v1"

CHAPTER_DS_ID = "efb7798d-72c2-4b2a-bfa9-8161f5c5dc3f"   # 빙고판(챕터)
SENTENCE_DS_ID = "1c31c5e2-fb57-80a4-a087-000b7b455705"  # 예문 DB

KST = timezone(timedelta(hours=9))

MAX_PANES = 16                 # 예문 DB 컬럼 최대 1~16
RATE_LIMIT_DELAY = 0.34        # 노션 API 3 req/sec 안전선

# 제목 패턴: "603@박대호", "603S@박대호" 등
TITLE_PATTERN = re.compile(r"^(\d+S?)@(.+)$")

# 읽기원 스위치(2026-10-01): "db" = Supabase sentence_page·sentence · 그 밖 = 노션(기본)
SENTENCE_SOURCE = os.environ.get("SENTENCE_SOURCE", "").strip().lower()

# 승인 마커 — has_approval_marker·clean_rich_text와 같은 집합(🚧 는 승인 아님)
APPROVAL_MARKERS = ("✅", "☑️", "✔️")

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
    for marker in APPROVAL_MARKERS:
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
        if any(m in text for m in APPROVAL_MARKERS):
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


# ─── 읽기원 = Supabase 표 (SENTENCE_SOURCE=db, 2026-10-01) ───
def segs_to_rich(segs) -> list:
    """웹앱 `sentence.segs`(lib/correction Seg[] = {text, color?, bold?, italic?, strike?, code?})를
    노션 rich_text 항목 모양으로 되돌린다 — clean_rich_text·has_approval_marker를 **그대로** 태우기 위해.
    (웹앱 lounge.ts richOfSegList와 같은 변환. 색 이름은 노션 표기 그대로 'gray'·'brown'·'gray_background'.)
    segs에는 text 타입만 들어 있다(씨앗·parseNotionRich가 mention·equation을 이미 걸렀다)."""
    if isinstance(segs, str):
        try:
            segs = json.loads(segs)
        except ValueError:
            segs = []
    rich = []
    for sg in segs or []:
        if not isinstance(sg, dict):
            continue
        text = sg.get("text") or ""
        if not text:
            continue
        rich.append({
            "type": "text",
            "plain_text": text,
            "text": {"content": text},
            "annotations": {
                "color": sg.get("color") or "default",
                "bold": bool(sg.get("bold")),
                "italic": bool(sg.get("italic")),
                "strikethrough": bool(sg.get("strike")),
                "code": bool(sg.get("code")),
                "underline": False,
            },
        })
    return rich


def build_chapter_mapping_db() -> dict:
    """`chapter` 표(0023)에서 챕터별 구간 매핑 — 노션 빙고판 `구간N 시작칸/끝칸`의 자리.

    키 = 노션 제목 원문(`title`, '605(S)'·'505S'·'505')에 더해 `key`('605')도 같은 값으로 건다.
    ⟹ find_section은 손대지 않는다: '605'·'605S' → '605(S)' 공유, '505S' → 제목 '505S' 직격, 종전과 같은 순서.
    """
    rows = supa.select(
        "chapter",
        "select=key,title,sec1_start,sec1_end,sec2_start,sec2_end,sec3_start,sec3_end,sec4_start,sec4_end&order=key.asc",
        "챕터(구간 경계)",
    )
    mapping = {}
    for r in rows:
        sections = {}
        for sec in range(1, 5):
            start, end = r.get(f"sec{sec}_start"), r.get(f"sec{sec}_end")
            if start is not None and end is not None:
                sections[sec] = (int(start), int(end))
        if not sections:
            continue
        for k in {(r.get("title") or "").strip(), (r.get("key") or "").strip()}:
            if k:
                mapping[k] = sections
        log.info("📋 %s 매핑: %s", r.get("title") or r.get("key"), sections)
    return mapping


def extract_sentences_db(chapter_mapping: dict) -> list:
    """Supabase `sentence_page`+`sentence`(웹앱 0028)에서 SentenceBank 행 추출 — 노션 경로와 같은 산출.

    장 → chapter = chapter_key + ('S' if 레벨 기초) · owner = person.name(실명).
      노션 경로가 제목 `숫자(S)@이름`만 받듯 chapter_key가 숫자가 아닌 장(Matcha·Tut …)은 종전대로 건너뛴다.
    칸 → pane = seq 원문 그대로(정수면 정수 · '9·10' 같은 문자열이면 그대로) · sentence = segs를 rich_text로 되돌려
      **같은** clean_rich_text(회색·배경색·취소선·마커·점수 메모 제거).
    승인 게이트 = `marker` 열이 ✅/☑️/✔️ **또는** 본문 어딘가에 그 마커(노션 경로 has_approval_marker와 같은 관용 —
      웹앱은 앞머리 마커만 열에 적고, 사람이 손으로 중간에 찍은 ✅ 도 종전엔 통과했다).
    """
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    persons = supa.select("person", "select=id,name&order=id.asc", "사람(실명)")
    name_of = {p["id"]: (p.get("name") or "").strip() for p in persons}
    pages = supa.select(
        "sentence_page",
        "select=id,chapter_key,level,person_id,title,status&order=chapter_key.asc,level.asc,id.asc",
        "예문 장",
    )
    cells = supa.select(
        "sentence",
        "select=page_id,seq,segs,text,marker&order=page_id.asc,seq.asc",
        "예문 칸",
    )
    cells_by_page = {}
    for c in cells:
        cells_by_page.setdefault(c["page_id"], []).append(c)

    rows, skipped_titles, legacy_titles = [], [], []
    for pg in pages:
        key = (pg.get("chapter_key") or "").strip()
        owner = name_of.get(pg.get("person_id"), "")
        title = (pg.get("title") or "").strip()
        if not key.isdigit() or not owner:
            skipped_titles.append(title or key)
            continue
        # 옛 제목꼴('박진형507' — @ 없음)은 노션 경로가 TITLE_PATTERN으로 늘 걸렀다(101·506·507 옛 기수 27장·233칸, 1001 실측).
        # 씨앗은 이런 장도 받아들였지만 여기서 그대로 실으면 sentence_bank에 옛 행이 늘고 TTS가 그만큼 굽는다(지출).
        # ⟹ 산출 동일 원칙으로 종전과 같이 건너뛴다. 제목이 비어 있는 장(표에서 새로 난 장)은 이 문에 안 걸린다.
        if title and not TITLE_PATTERN.match(title):
            legacy_titles.append(title)
            continue
        chapter = key + ("S" if (pg.get("level") or "") == "기초" else "")
        for c in cells_by_page.get(pg["id"], []):
            seq = c.get("seq")
            if seq is None or str(seq).strip() == "":
                continue
            pane = seq if isinstance(seq, int) else str(seq).strip()
            rich = segs_to_rich(c.get("segs"))
            approved = (
                (c.get("marker") or "").strip() in APPROVAL_MARKERS
                or has_approval_marker(rich)
                or any(m in (c.get("text") or "") for m in APPROVAL_MARKERS)
            )
            if not approved:
                continue
            sentence = clean_rich_text(rich)
            if not sentence:
                continue
            nums = re.findall(r"\d+", str(pane))  # '9·10' 같은 병합 칸은 끝번으로 구간을 잰다(웹앱 fieldOf와 같은 결)
            section = find_section(chapter, int(nums[-1]), chapter_mapping) if nums else None
            rows.append([chapter, pane, owner, section if section is not None else "", sentence, now])

    if skipped_titles:
        log.warning("⚠️ 숫자 챕터가 아니거나 사람 없음 → skip된 장: %d개", len(skipped_titles))
        for t in skipped_titles[:5]:
            log.warning("   skip 예: %r", t)
    if legacy_titles:
        log.warning("⚠️ 옛 제목꼴(@ 없음, 노션 경로와 동일하게 제외) → skip된 장: %d개", len(legacy_titles))
        for t in legacy_titles[:5]:
            log.warning("   skip 예: %r", t)

    rows.sort(key=lambda r: (r[0], r[2], (0, r[1]) if isinstance(r[1], int) else (1, str(r[1]))))  # Chapter → Owner → Pane
    return rows


# ─── DB 기록 ───
def write_to_db(rows: list) -> None:
    """SentenceBank를 Supabase(sentence_bank)에 기록 — 시트 폐선 2단계(2026-09-14).

    웹앱과 음원 생성이 이 테이블에서 정답·구간 매핑을 읽는다. **여기가 유일한 쓰기**다.
    ★ 순서 = 전 행 upsert → **성공했을 때만** 이번에 쓴 챕터의 옛 행 정리.
      '지우고 다시 넣기'는 금지(0801 전멸 사고 경로).
    ★ 전부 들어가지 못하면 exit 1. 시트 이중 쓰기가 있던 때는 부분 실패를 다음 회차가 따라잡았지만,
      이제 받아줄 곳이 없어 조용한 부분 반영 = 조용한 데이터 유실이다(0907 '소리 내어 죽는다'와 같은 결).
    """
    batch_iso = datetime.now(KST).isoformat()
    payload, chapters = [], set()
    for r in rows:
        chapter = str(r[0]).strip()
        pane = str(r[1]).strip()
        owner = str(r[2]).strip()
        if not chapter or not pane or not owner:
            continue
        chapters.add(chapter)
        payload.append({
            "chapter": chapter,
            "pane": pane,
            "owner": owner,
            "section": str(r[3]).strip(),
            "sentence": r[4],
            "updated_at": batch_iso,
        })
    if not payload:
        # 추출 0행 = 노션이 비었거나 못 읽은 것. 지우지 않고 그대로 둔다(전멸 방지).
        log.warning("⚠️ 쓸 행이 0개 — DB는 손대지 않습니다(옛 데이터 보존).")
        return
    done = supa.upsert("sentence_bank", "chapter,pane,owner", payload, "정답 문장")
    if done != len(payload):
        log.error("❌ Supabase upsert가 일부만 성공(%d/%d) — 옛 행 정리를 건너뛰고 실패로 끝냅니다.", done, len(payload))
        sys.exit(1)
    log.info("📤 sentence_bank에 %d행 기록 완료", done)
    supa.prune_stale("sentence_bank", "chapter", chapters, batch_iso, "SentenceBank")


# ─── 메인 ───
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="예문(노션 또는 Supabase 표) → sentence_bank 동기화")
    ap.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않는다(추출·집계만)")
    ap.add_argument("--out", metavar="JSON", help="추출 행을 JSON 파일로 떨군다(두 읽기원 대조용)")
    return ap.parse_args(argv)


def collect_rows() -> list:
    """읽기원 스위치에 따라 SentenceBank 행을 모은다. 산출 모양은 두 경로가 같다."""
    if SENTENCE_SOURCE == "db":
        log.info("▶ 읽기원 = Supabase 표(SENTENCE_SOURCE=db)")
        log.info("1/3 chapter 표에서 구간 경계 가져오는 중...")
        chapter_mapping = build_chapter_mapping_db()
        if not chapter_mapping:
            log.warning("⚠️ 챕터 매핑이 비어있음. chapter 표의 sec1~4_start/end 채워야 함.")
        log.info("2/3 sentence_page·sentence 표 읽는 중...")
        rows = extract_sentences_db(chapter_mapping)
        return rows

    log.info("▶ 읽기원 = 노션(SENTENCE_SOURCE 미설정 또는 db 아님)")
    log.info("1/3 빙고판 DB에서 챕터 매핑 가져오는 중...")
    chapter_pages = query_data_source(CHAPTER_DS_ID)
    log.info("   → 챕터 페이지 %d개 발견", len(chapter_pages))
    chapter_mapping = build_chapter_mapping(chapter_pages)
    if not chapter_mapping:
        log.warning("⚠️ 챕터 매핑이 비어있음. 빙고판 DB의 구간1~4 시작/끝칸 채워야 함.")

    log.info("2/3 예문 DB에서 모든 행 가져오는 중...")
    sentence_pages = query_data_source(SENTENCE_DS_ID)
    log.info("   → 예문 페이지 %d개 발견", len(sentence_pages))
    return extract_sentences(sentence_pages, chapter_mapping)


def main(argv=None):
    args = parse_args(argv)
    log.info("▶ 예문 동기화 시작")
    rows = collect_rows()
    log.info("   → 추출된 문장: %d개", len(rows))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(
                [{"chapter": r[0], "pane": r[1], "owner": r[2], "section": r[3], "sentence": r[4]} for r in rows],
                f, ensure_ascii=False, indent=1,
            )
        log.info("📝 추출 행 %d개를 %s 에 기록", len(rows), args.out)

    if args.dry_run:
        log.info("🧪 드라이런 — DB에 쓰지 않고 끝냅니다.")
        return

    log.info("3/3 sentence_bank 기록...")
    write_to_db(rows)
    log.info("✅ 동기화 완료")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log.exception("❌ 치명적 오류: %s", e)
        sys.exit(1)

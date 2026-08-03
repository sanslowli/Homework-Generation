"""
파일명 → ImageMatching 시트 동기화 (역방향).

선생님이 그림 파일을 '<섹션-슬롯><주인>.png' (예: 1-3박대호.png) 로 rename 해
push 하면, 이 스크립트가 GitHub Actions 에서 돌면서 해당 매칭을 구글 시트
"Syntax Pitching DB" 의 ImageMatching 탭에 upsert 한다.

규칙(앱 app.py 와 동일):
  경로 = {최상위}/{학생}/{현행·지난 챕터}/{챕터}/{섹션-슬롯[주인]}.png
  ImageStudent = 학생 폴더명
  Chapter      = 이미지의 부모 폴더명(챕터)
  Image        = 정규화된 맨이름 '1-3.png'
  ContentOwner = 파일명에 붙은 주인 이름

설계 원칙:
  - 주인 suffix 가 붙은 파일만 처리(= 매칭된 것). 맨이름(미매칭)은 무시.
  - upsert 만 한다. 삭제는 하지 않는다 → 앱(gspread)이 직접 쓴 행을 보존.
  - 따라서 앱이 쓴 매칭과 선생님이 파일명으로 넣은 매칭이 충돌 없이 공존.
"""
import os
import re
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone, timedelta

SHEET_NAME = "Syntax Pitching DB"
TAB = "ImageMatching"
HEADER = ["ImageStudent", "Chapter", "Image", "ContentOwner", "Updated"]
TARGET_FOLDERS = ["Syntax Pitching", "Syntax Only", "Syntax + Open-ended Question"]
SKIP_DIR_TOKENS = ["보류", "보관"]
IMG_EXTS = (".png", ".jpg", ".jpeg")


def kst_now():
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")


def with_retry(fn, what, tries=5, base_delay=10.0):
    """구글 API 5xx·429(쿼터) 지수 백오프 재시도 (2026-08-01 — sync_notion.with_retry와 같은 규약).
    429는 '분당 쿼터 붐빔'이라 기다리면 풀리는 일시 장애 — 웹앱이 같은 서비스 계정 쿼터를 잠깐 태운 순간
    스캔 동기화가 통째로 죽던 사고(#54·55·56) 방어. 그 외 4xx(권한·잘못된 요청)는 즉시 raise."""
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except gspread.exceptions.APIError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            retryable = status is not None and (status >= 500 or status == 429)
            if not retryable or attempt == tries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            print(f"⚠️ 구글 API {status} ({what}) — {attempt}/{tries}회, {delay:.0f}초 후 재시도")
            time.sleep(delay)


def parse_named_image(filename):
    """'1-3박대호.png' → ('1-3.png', '박대호'). 주인 suffix 없으면 (None, None).
    Image 는 앱 app.py 의 match_image_key 와 동일하게 항상 '.png' 로 정규화."""
    name = os.path.splitext(filename)[0]
    if "-" not in name:
        return None, None
    sec, rest = name.split("-", 1)
    sec = sec.strip()
    m = re.match(r"^(\d+)(.+)$", rest.strip())
    if not (sec.isdigit() and m):
        return None, None
    slot, owner = m.group(1), m.group(2).strip()
    if not owner:
        return None, None
    return f"{sec}-{slot}.png", owner


def canon(image):
    """'1-3박대호.png' / '1-3.jpeg' / '1-3.png' → '1-3.png' (비교용 정규화, 확장자 .png 통일)."""
    name = os.path.splitext(image)[0]
    if "-" in name:
        sec, rest = name.split("-", 1)
        m = re.match(r"^(\d+)", rest.strip())
        if sec.strip().isdigit() and m:
            return f"{sec.strip()}-{m.group(1)}.png"
    return image


def collect():
    """{(student, chapter, image, set): owner} — 주인 붙은 파일만.

    경로 = {학생}/{현행·지난 챕터}/{챕터}/{파일}                     (4단, 종전)
         또는 {학생}/{현행·지난 챕터}/{챕터}/{세트}/{파일}           (5단, 2026-08-01)
    ★ 세트 = 주 2회 수강생의 반(요일) 분기 폴더(웹앱 0729). 종전처럼 '부모 폴더 = 챕터'로 읽으면
      세트 폴더를 챕터로 오인해('일'이 챕터가 됨) 매칭이 통째로 어긋난다 → 위치로 판정한다.
    """
    rows = {}
    for tf in TARGET_FOLDERS:
        if not os.path.isdir(tf):
            continue
        for root, dirs, files in os.walk(tf):
            if any(tok in root for tok in SKIP_DIR_TOKENS):
                continue
            for f in files:
                if not f.lower().endswith(IMG_EXTS):
                    continue
                image, owner = parse_named_image(f)
                if not image:
                    continue
                rel_parts = os.path.relpath(os.path.join(root, f), tf).split(os.sep)
                if len(rel_parts) < 4:
                    continue  # [학생, 현행/지난, 챕터, 파일] 미만 = 규약 밖 경로
                student = rel_parts[0]
                chapter = rel_parts[2]
                bset = rel_parts[3] if len(rel_parts) >= 5 else ""  # 5단이면 세트 폴더
                rows[(student, chapter, image, bset)] = owner
    return rows


def main():
    scope = ["https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("service_key.json", scope)
    client = gspread.authorize(creds)
    ss = with_retry(lambda: client.open(SHEET_NAME), "스프레드시트 열기")
    try:
        ws = with_retry(lambda: ss.worksheet(TAB), "워크시트 조회")
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=TAB, rows=2000, cols=6)
        ws.append_row(HEADER)

    existing = with_retry(lambda: ws.get_all_values(), "본문 읽기")
    rows = [r[:] for r in existing[1:]] if len(existing) > 1 else []
    # ★ 헤더 보존(2026-08-01) — 웹앱이 0729에 F열 'Set'(주 2회 보드 세트)을 추가했다. 여기서 고정 HEADER로
    #   덮으면 그 열 이름이 사라져 웹앱의 세트 필터가 통째로 무력화됨. 시트의 기존 헤더가 더 넓으면 그대로 쓴다.
    header = existing[0][:] if existing and len(existing[0]) >= len(HEADER) else HEADER[:]

    # 키에 세트(F열)까지 포함 — 같은 좌표라도 반이 다르면 다른 행(2026-08-01).
    idx = {}
    for i, r in enumerate(rows):
        if len(r) >= 3:
            idx[(r[0], r[1], canon(r[2]), (r[5].strip() if len(r) > 5 else ""))] = i

    found = collect()
    ts = kst_now()
    updated = appended = 0
    for (student, chapter, image, bset), owner in sorted(found.items()):
        key = (student, chapter, canon(image), bset)
        if key in idx:
            r = rows[idx[key]]
            while len(r) < 6:
                r.append("")
            r[2], r[3], r[4], r[5] = image, owner, ts, bset
            updated += 1
        else:
            rows.append([student, chapter, image, owner, ts, bset])
            idx[key] = len(rows) - 1
            appended += 1
    # 세트 행을 쓰는데 시트 헤더가 아직 5칸이면 F열 이름을 세워둔다(웹앱이 헤더명으로 열을 읽음).
    if any(len(r) > 5 and r[5] for r in rows) and len(header) < 6:
        header = header + [""] * (6 - len(header))
        header[5] = "Set"

    # ⚠ 행마다 update/append 호출하면 구글 쓰기 쿼터(분당 ~60) 초과로 실패함 → '한 번의 통째 쓰기'.
    # ★ clear() 선행 폐지(2026-08-01, sync_notion 0706 규칙 이식): '지우기 → 쓰기' 사이에 API가 죽으면
    #   (429·5xx) ImageMatching이 텅 빈 채 남아 전 학생 담기 정보가 증발한다 — 쿼터 사고가 실제로
    #   나던 중이라 실현 직전이었음. 덮어쓰기 먼저 → 남는 아래 행만 뒤에 정리(어느 시점에 죽어도 온전).
    values = [header] + rows
    with_retry(lambda: ws.update("A1", values), "본문 덮어쓰기")
    old_rows = ws.row_count
    if old_rows > len(values):
        with_retry(lambda: ws.batch_clear([f"A{len(values) + 1}:Z{old_rows}"]), "잔여 행 정리")

    print(f"ImageMatching sync: {updated} updated, {appended} appended, "
          f"total {len(rows)} rows (named files: {len(found)})")


if __name__ == "__main__":
    main()

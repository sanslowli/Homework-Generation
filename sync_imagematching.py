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
    """{(student, chapter, image): owner} — 주인 붙은 파일만."""
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
                if len(rel_parts) < 2:
                    continue
                student = rel_parts[0]
                chapter = os.path.basename(root)  # 이미지의 부모 폴더 = 챕터
                rows[(student, chapter, image)] = owner
    return rows


def main():
    scope = ["https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("service_key.json", scope)
    client = gspread.authorize(creds)
    ss = client.open(SHEET_NAME)
    try:
        ws = ss.worksheet(TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=TAB, rows=2000, cols=5)
        ws.append_row(HEADER)

    existing = ws.get_all_values()
    rows = [r[:] for r in existing[1:]] if len(existing) > 1 else []

    idx = {}
    for i, r in enumerate(rows):
        if len(r) >= 3:
            idx[(r[0], r[1], canon(r[2]))] = i

    found = collect()
    ts = kst_now()
    updated = appended = 0
    for (student, chapter, image), owner in sorted(found.items()):
        key = (student, chapter, canon(image))
        if key in idx:
            r = rows[idx[key]]
            while len(r) < 5:
                r.append("")
            r[2], r[3], r[4] = image, owner, ts
            updated += 1
        else:
            rows.append([student, chapter, image, owner, ts])
            idx[key] = len(rows) - 1
            appended += 1

    # ⚠ 행마다 update/append 호출하면 구글 쓰기 쿼터(분당 ~60) 초과로 실패함.
    # sync_notion.py 와 동일하게 '한 번의 통째 쓰기'로 처리(읽기1 + clear1 + update1).
    # 기존 행(앱이 쓴 매칭 포함)은 rows 에 그대로 들어있으므로 보존됨(= upsert).
    ws.clear()
    ws.update("A1", [HEADER] + rows)

    print(f"ImageMatching sync: {updated} updated, {appended} appended, "
          f"total {len(rows)} rows (named files: {len(found)})")


if __name__ == "__main__":
    main()

"""
1회성 backfill: ImageMatching 시트 → 그림 파일명 소급 적용.

이미 시트에 기록된 매칭들에 대해, 로컬 그림 파일을
  '<섹션-슬롯>.png'  →  '<섹션-슬롯><주인>.png'   (예: 1-3.png → 1-3박대호.png)
로 rename 한다. 이미 이름이 붙어 있고 주인이 바뀐 경우도 올바른 주인으로 교정.

앞으로의 매칭은 app.py(try_rename_image_on_github)와 sync_imagematching.py가
계속 동기화하므로, 이 스크립트는 과거분을 한 번 맞추는 용도다.

안전장치:
  - 기본은 DRY-RUN(미리보기만). 실제 변경은 `--apply` 플래그.
  - git 커밋/push 는 하지 않는다. 변경 후 `git diff`/`git status` 로 확인하고 직접 커밋.
  - 시트에 없는(미매칭) 파일은 건드리지 않는다 → 맨이름 유지(= 시각적으로 '아직 안 됨').

실행:
  python backfill_image_filenames.py                 # 미리보기
  python backfill_image_filenames.py --apply         # 실제 rename
  python backfill_image_filenames.py --key path.json # 서비스계정 키 경로 지정(기본: service_key.json)
"""
import os
import re
import sys
import argparse
import gspread
from oauth2client.service_account import ServiceAccountCredentials

SHEET_NAME = "Syntax Pitching DB"
TAB = "ImageMatching"
TARGET_FOLDERS = ["Syntax Pitching", "Syntax Only", "Syntax + Open-ended Question"]
SKIP_DIR_TOKENS = ["보류", "보관"]
IMG_EXTS = (".png", ".jpg", ".jpeg")


def extract_section_slot(filename):
    name = os.path.splitext(os.path.basename(filename))[0]
    if "-" in name:
        sec, rest = name.split("-", 1)
        m = re.match(r"^(\d+)", rest.strip())
        if sec.strip().isdigit() and m:
            return sec.strip(), int(m.group(1))
    return None, None


def canon(filename):
    sec, slot = extract_section_slot(filename)
    if sec is not None:
        return f"{sec}-{slot}.png"
    return os.path.basename(filename)


def load_sheet_matchings(key_path):
    scope = ["https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
    client = gspread.authorize(creds)
    ws = client.open(SHEET_NAME).worksheet(TAB)
    result = {}
    for r in ws.get_all_records():
        student = str(r.get("ImageStudent", "")).strip()
        chapter = str(r.get("Chapter", "")).strip()
        image = canon(str(r.get("Image", "")).strip())
        owner = str(r.get("ContentOwner", "")).strip()
        if student and chapter and image and owner:
            result[(student, chapter, image)] = owner
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 rename (기본은 미리보기)")
    ap.add_argument("--key", default="service_key.json", help="구글 서비스계정 키 JSON 경로")
    args = ap.parse_args()

    if not os.path.exists(args.key):
        print(f"[오류] 서비스계정 키 '{args.key}' 가 없습니다. --key 로 경로를 지정하세요.")
        sys.exit(1)

    matchings = load_sheet_matchings(args.key)
    print(f"시트 매칭 {len(matchings)}건 로드.\n")

    planned, skipped_no_match, conflicts = [], 0, []
    for tf in TARGET_FOLDERS:
        if not os.path.isdir(tf):
            continue
        for root, dirs, files in os.walk(tf):
            if any(tok in root for tok in SKIP_DIR_TOKENS):
                continue
            student_rel = os.path.relpath(root, tf).split(os.sep)
            if not student_rel or student_rel[0] in (".", ""):
                continue
            student = student_rel[0]
            chapter = os.path.basename(root)
            for f in files:
                if not f.lower().endswith(IMG_EXTS):
                    continue
                sec, slot = extract_section_slot(f)
                if sec is None:
                    continue
                owner = matchings.get((student, chapter, f"{sec}-{slot}.png"))
                if not owner:
                    skipped_no_match += 1
                    continue
                desired = f"{sec}-{slot}{owner}.png"
                if f == desired:
                    continue  # 이미 올바름
                src = os.path.join(root, f)
                dst = os.path.join(root, desired)
                if os.path.exists(dst):
                    conflicts.append((src, dst))
                    continue
                planned.append((src, dst))

    print(f"== 적용 예정 {len(planned)}건 (미매칭으로 건너뜀 {skipped_no_match}, 충돌 {len(conflicts)}) ==")
    for src, dst in planned:
        print(f"  {os.path.relpath(src):60} ->  {os.path.basename(dst)}")
    if conflicts:
        print("\n[충돌 — 대상 파일이 이미 존재, 건너뜀]")
        for src, dst in conflicts:
            print(f"  {os.path.relpath(src)}  ->  {os.path.basename(dst)}  (이미 있음)")

    if not args.apply:
        print("\n(미리보기 모드) 실제 적용하려면 --apply 를 붙여 다시 실행하세요.")
        return

    done = 0
    for src, dst in planned:
        try:
            os.rename(src, dst)
            done += 1
        except Exception as e:
            print(f"  실패: {src} -> {dst} ({e})")
    print(f"\n완료: {done}건 rename. 이제 `git status` 로 확인 후 커밋·push 하세요.")


if __name__ == "__main__":
    main()

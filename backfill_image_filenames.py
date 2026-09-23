"""
1회성 backfill: ImageMatching 원장(Supabase `image_matching`) → 그림 파일명 소급 적용.

원장에 기록된 매칭들에 대해, 로컬 그림 파일을
  '<섹션-슬롯>.png'  →  '<섹션-슬롯><주인>.png'   (예: 1-3.png → 1-3박대호.png)
로 rename 한다. 이미 이름이 붙어 있고 주인이 바뀐 경우도 올바른 주인으로 교정.

★ 읽기원 = Supabase(2026-09-22). 종전엔 구글 시트 ImageMatching 탭을 읽었는데, 시트는 0914 폐선 뒤 **동결 백업**이라
  그 뒤 웹앱에서 한 담기가 시트엔 없다 — 시트로 돌리면 낡은 주인으로 되돌려 놓는다. 그래서 DB로 옮겼다(gspread 의존 0).
  유령 행(재단 칸 폴더 `set_key='cells'`·주인 꼬리 `__N`)은 웹앱 창구(`pitchDb.isGhostMatchRow`)와 같은 관문으로 거른다.
  챕터는 숫자로 맞춘다 — 원장엔 `605`(웹 담기)·`605S`(스캔) 두 표기가 같은 담기로 공존한다(game-canon D-14ⓑ, 주인 갈림 0).

앞으로의 매칭은 웹앱 담기(`api/pitch/match`)와 sync_imagematching.py(파일명 → 원장)가
계속 동기화하므로, 이 스크립트는 과거분을 한 번 맞추는 용도다.

안전장치:
  - 기본은 DRY-RUN(미리보기만). 실제 변경은 `--apply` 플래그.
  - git 커밋/push 는 하지 않는다. 변경 후 `git diff`/`git status` 로 확인하고 직접 커밋.
  - 원장에 없는(미매칭) 파일은 건드리지 않는다 → 맨이름 유지(= 시각적으로 '아직 안 됨').

실행 (env: SUPABASE_URL · SUPABASE_SERVICE_ROLE_KEY — sync 워크플로와 같은 secret):
  python backfill_image_filenames.py                 # 미리보기
  python backfill_image_filenames.py --apply         # 실제 rename
"""
import os
import re
import sys
import argparse
import supa  # 원장 창구(0922) — 시트가 아니라 DB를 읽는다

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


def chapter_num(chapter):
    """챕터 표기에서 숫자만 — `605`·`605S`를 같은 담기로 본다(웹앱 `ownerKey`와 같은 규약)."""
    return re.sub(r"[^0-9]", "", chapter or "")


def load_db_matchings():
    rows = supa.select(
        "image_matching",
        "select=student,chapter,image_key,content_owner,set_key&order=student,chapter,image_key",
        "담기 원장",
    )
    result = {}
    for r in rows:
        student = str(r.get("student") or "").strip()
        chapter = chapter_num(str(r.get("chapter") or ""))
        image = canon(str(r.get("image_key") or "").strip())
        owner = str(r.get("content_owner") or "").strip()
        if str(r.get("set_key") or "").strip() == "cells" or re.search(r"__\d+$", owner):
            continue  # 유령 행 — 재단 칸 폴더가 주인처럼 들어간 것(0904 실사고), 웹앱과 같은 관문
        if student and chapter and image and owner:
            result[(student, chapter, image)] = owner
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 rename (기본은 미리보기)")
    args = ap.parse_args()

    try:
        matchings = load_db_matchings()
    except Exception as e:
        print(f"[오류] 담기 원장(Supabase image_matching)을 못 읽었습니다: {e}")
        sys.exit(1)
    print(f"원장 매칭 {len(matchings)}건 로드.\n")

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
                owner = matchings.get((student, chapter_num(chapter), f"{sec}-{slot}.png"))
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

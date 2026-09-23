"""
파일명 → Supabase `image_matching` 동기화 (역방향).

선생님이 그림 파일을 '<섹션-슬롯><주인>.png' (예: 1-3박대호.png) 로 rename 해
push 하면, 이 스크립트가 GitHub Actions 에서 돌면서 해당 매칭을 Supabase
`image_matching` 테이블에 upsert 한다.

규칙:
  경로 = {최상위}/{학생}/{현행·지난 챕터}/{챕터}/{섹션-슬롯[주인]}.png
  student       = 학생 폴더명
  chapter       = 이미지의 챕터 폴더명
  image_key     = 정규화된 맨이름 '1-3.png'
  content_owner = 파일명에 붙은 주인 이름

설계 원칙:
  - 주인 suffix 가 붙은 파일만 처리(= 매칭된 것). 맨이름(미매칭)은 무시.
  - upsert 만 한다. 삭제는 하지 않는다 → 웹앱에서 학생이 직접 담은 행을 보존.
  - 따라서 웹앱이 쓴 매칭과 선생님이 파일명으로 넣은 매칭이 충돌 없이 공존.

[구글 시트 쓰기는 폐선(2026-09-14, 시트 폐선 2단계)]
  종전엔 시트를 읽어 파일명 발견분과 합친 뒤 시트에 통째로 쓰고 그 최종 상태를 DB에 미러했다.
  이제 시트를 보지 않고 **파일명에서 발견한 것만 DB에 upsert**한다 — 웹앱의 담기는 0822부터
  `/api/pitch/match`가 DB에 직접 쓰므로(시트는 거기서도 그림자였다) 시트를 거칠 이유가 없다.
  삭제를 안 하는 원칙 그대로라 DB에 이미 있는 행은 영향받지 않는다.
"""
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import supa  # 정본 원장 = Supabase(시트 폐선 2단계, 0914)

KST = timezone(timedelta(hours=9))
TARGET_FOLDERS = ["Syntax Pitching", "Syntax Only", "Syntax + Open-ended Question"]
SKIP_DIR_TOKENS = ["보류", "보관"]
CELL_DIR = "cells"                      # 띠를 칸 단위로 자른 사본 폴더(0901). 원본이 아니라 사본이고,
                                        # 파일명이 '1-1이우강__1.png'라 주인이 '이우강__1'로 읽힌다 → 내려가지 않는다(0907)
OWNER_TAIL_RE = re.compile(r"(?:__\d+)+$")  # 이미 번진 꼬리를 읽을 때 떼는 안전망(0907)
IMG_EXTS = (".png", ".jpg", ".jpeg")


def kst_now_iso():
    """updated_at용 ISO(+09:00) 한 줄. 시트 Updated 문자열 왕복(kst_now/kst_iso)이 사라져 직접 만든다."""
    return datetime.now(KST).isoformat()


def parse_named_image(filename):
    """'1-3박대호.png' → ('1-3.png', '박대호'). 주인 suffix 없으면 (None, None).
    확장자는 항상 '.png' 로 정규화한다(웹앱 담기의 저장 규약과 같은 자리)."""
    name = os.path.splitext(filename)[0]
    if "-" not in name:
        return None, None
    sec, rest = name.split("-", 1)
    sec = sec.strip()
    m = re.match(r"^(\d+)(.+)$", rest.strip())
    if not (sec.isdigit() and m):
        return None, None
    slot, owner = m.group(1), m.group(2).strip()
    owner = OWNER_TAIL_RE.sub("", owner).strip()  # '이우강__1' → '이우강' (재단 꼬리가 띠 파일명까지 번진 것, 0907)
    if not owner:
        return None, None
    return f"{sec}-{slot}.png", owner


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
            dirs[:] = [d for d in dirs if d != CELL_DIR]  # 재단 칸은 사본이라 매칭 대상 아님(0907)
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
    """파일명에서 발견한 매칭을 `image_matching`에 upsert. 삭제는 하지 않는다.

    ★ 부분 실패는 exit 1. 시트 이중 쓰기가 있던 때는 시트가 받아 줬지만 이제 받아줄 곳이 없어,
      조용한 부분 반영 = 담기가 조용히 유실되는 길이다(0907 '소리 내어 죽는다'와 같은 결).
    """
    found = collect()
    if not found:
        print("ImageMatching sync: 주인 붙은 파일 0개 — DB는 손대지 않습니다.")
        return

    at = kst_now_iso()
    mirror = [
        {
            "student": student,
            "chapter": chapter,
            "image_key": image,   # parse_named_image가 이미 '{구간}-{슬롯}.png'로 정규화해 돌려준다
            "set_key": bset,
            "content_owner": owner,
            "updated_at": at,
        }
        for (student, chapter, image, bset), owner in sorted(found.items())
    ]
    done = supa.upsert("image_matching", "student,chapter,image_key,set_key", mirror, "그림 매칭")
    print(f"ImageMatching sync: {done}/{len(mirror)} rows upserted (named files: {len(found)})")
    if done != len(mirror):
        print("❌ 일부만 반영됨 — 실패로 끝냅니다(다음 실행이 같은 파일을 다시 올린다).")
        sys.exit(1)


if __name__ == "__main__":
    main()

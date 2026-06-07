"""
generate_tts.py — SentenceBank 기준으로 OpenAI TTS mp3 파일 생성

[사용법]
1. 환경 변수에 OPENAI_API_KEY 설정 (또는 openai_key.txt):
     export OPENAI_API_KEY=sk-...

2. 실행:
     python3 generate_tts.py

3. 옵션:
     --dry-run        실제 호출 없이 어떤 파일이 새로 만들어질지만 출력
     --force          내용 변경 여부 무시하고 전부 재생성
     --chapter 603    특정 챕터만 처리
     --voice shimmer  음성 변경 (기본: shimmer)
     --model tts-1-hd 모델 변경 (기본: tts-1-hd)
     --speed 1.0      재생 속도 (기본: 1.0)

[동작]
- Google Sheet 의 SentenceBank 시트를 읽어옴 (sync_notion.py로 채워진 데이터)
- 각 행 (Chapter, Pane, Owner, Sentence) 에 대해:
    audio/{Chapter}/{Pane}_{Owner}.mp3 + audio/{Chapter}/{Pane}_{Owner}.txt 페어 확인
    - mp3 없음                           → 생성
    - mp3 있고 .txt 내용 == 현재 Sentence → skip
    - mp3 있고 .txt 내용 != 현재 Sentence → 재생성 (내용 바뀜)
    - --force 플래그                      → 무조건 재생성
- 사이드카 .txt 파일은 mp3와 짝지어 저장되어, 다음 실행 때 변경 감지 기준이 됨

[옛 파일과의 공존]
- 기존 section 기반 mp3는 _old 접미사로 archive됨 (예: 602/1_박대호_old.mp3)
- 새 pane 기반 mp3는 깨끗한 양식 (예: 602/1_박대호.mp3, 602/2_박대호.mp3, ...)
- 같은 폴더에서 충돌 없음, 앱 transition 시 자연스럽게 옛 거 정리 가능
"""

import os
import sys
import argparse
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from pathlib import Path

# OpenAI SDK
try:
    from openai import OpenAI
except ImportError:
    print("❌ openai 패키지가 설치되어 있지 않습니다.")
    print("   설치: pip install openai")
    sys.exit(1)


SHEET_NAME = "Syntax Pitching DB"
SENTENCE_BANK_TAB = "SentenceBank"
BASE_FOLDER = os.path.dirname(os.path.abspath(__file__))
AUDIO_ROOT = os.path.join(BASE_FOLDER, "audio")
SERVICE_KEY_PATH = os.path.join(BASE_FOLDER, "service_key.json")
OPENAI_KEY_PATH = os.path.join(BASE_FOLDER, "openai_key.txt")


def load_openai_key():
    """환경변수 우선, 없으면 openai_key.txt 파일에서 읽음."""
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key
    if os.path.exists(OPENAI_KEY_PATH):
        with open(OPENAI_KEY_PATH, "r") as f:
            return f.read().strip()
    return ""


def get_sheet_client():
    """로컬 service_key.json 으로 인증."""
    if not os.path.exists(SERVICE_KEY_PATH):
        print(f"❌ service_key.json 을 찾을 수 없습니다: {SERVICE_KEY_PATH}")
        sys.exit(1)
    scope = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_KEY_PATH, scope)
    return gspread.authorize(creds)


def load_sentence_bank_rows(client):
    """SentenceBank 시트의 모든 행을 dict 리스트로 반환."""
    try:
        ws = client.open(SHEET_NAME).worksheet(SENTENCE_BANK_TAB)
    except gspread.exceptions.WorksheetNotFound:
        print(f"❌ '{SENTENCE_BANK_TAB}' 시트가 없습니다. 먼저 sync_notion.py로 동기화하세요.")
        sys.exit(1)
    return ws.get_all_records()


def get_audio_path(chapter, pane, owner):
    """audio/{chapter}/{pane}_{owner}.mp3"""
    return os.path.join(AUDIO_ROOT, str(chapter), f"{pane}_{owner}.mp3")


def get_sidecar_path(chapter, pane, owner):
    """audio/{chapter}/{pane}_{owner}.txt — 생성 시점의 원문을 기록해두는 텍스트 파일."""
    return os.path.join(AUDIO_ROOT, str(chapter), f"{pane}_{owner}.txt")


def needs_regen(mp3_path, sidecar_path, current_text):
    """재생성 필요 여부.

    - mp3 없음 → True (처음 생성)
    - 사이드카 없음 → True (옛 mp3, 안전하게 재생성)
    - 사이드카 내용 != 현재 문장 → True (콘텐츠 변경됨)
    - 그 외 → False (내용 그대로, skip)
    """
    if not os.path.exists(mp3_path):
        return True
    if not os.path.exists(sidecar_path):
        return True
    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            existing = f.read()
        return existing.strip() != current_text.strip()
    except Exception:
        return True


def write_sidecar(sidecar_path, text):
    """사이드카 텍스트 파일 생성/덮어쓰기."""
    Path(os.path.dirname(sidecar_path)).mkdir(parents=True, exist_ok=True)
    with open(sidecar_path, "w", encoding="utf-8") as f:
        f.write(text)


def generate_one(openai_client, text, out_path, voice, model, speed):
    """OpenAI TTS 로 mp3 생성 후 out_path 에 저장."""
    Path(os.path.dirname(out_path)).mkdir(parents=True, exist_ok=True)
    response = openai_client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
        speed=speed,
    )
    with open(out_path, "wb") as f:
        f.write(response.content)


def main():
    parser = argparse.ArgumentParser(description="SentenceBank → TTS mp3 generator")
    parser.add_argument("--dry-run", action="store_true", help="실제 생성 없이 계획만 출력")
    parser.add_argument("--force", action="store_true", help="내용 변경 무관 전부 재생성")
    parser.add_argument("--chapter", type=str, default=None, help="특정 챕터만 처리")
    parser.add_argument("--voice", type=str, default="shimmer", help="OpenAI voice (기본: shimmer)")
    parser.add_argument("--model", type=str, default="tts-1-hd", help="OpenAI model (기본: tts-1-hd)")
    parser.add_argument("--speed", type=float, default=1.0, help="재생 속도 (기본: 1.0)")
    parser.add_argument("--yes", "-y", action="store_true", help="확인 프롬프트 스킵 (CI용)")
    args = parser.parse_args()

    # OpenAI key 확인
    api_key = load_openai_key()
    if not api_key:
        print("❌ OpenAI API 키를 찾을 수 없습니다.")
        print(f"   환경변수 OPENAI_API_KEY 또는 {OPENAI_KEY_PATH} 파일을 확인하세요.")
        sys.exit(1)
    openai_client = OpenAI(api_key=api_key)

    # 시트 로드
    print("📊 SentenceBank 시트 로드 중...")
    client = get_sheet_client()
    rows = load_sentence_bank_rows(client)
    print(f"   총 {len(rows)} 행 발견")

    # 챕터 필터
    if args.chapter:
        rows = [r for r in rows if str(r.get("Chapter", "")).strip() == str(args.chapter)]
        print(f"   '챕터={args.chapter}' 필터 적용 → {len(rows)} 행")

    # 처리 계획
    plan = []  # (chapter, pane, owner, sentence, out_path, sidecar_path, action)
    for r in rows:
        chapter = str(r.get("Chapter", "")).strip()
        pane = str(r.get("Pane", "")).strip()
        owner = str(r.get("Owner", "")).strip()
        sentence = r.get("Sentence", "")
        if not (chapter and pane and owner and sentence and sentence.strip()):
            continue
        out_path = get_audio_path(chapter, pane, owner)
        sidecar_path = get_sidecar_path(chapter, pane, owner)
        if args.force or needs_regen(out_path, sidecar_path, sentence):
            plan.append((chapter, pane, owner, sentence, out_path, sidecar_path, "generate"))
        else:
            plan.append((chapter, pane, owner, sentence, out_path, sidecar_path, "skip"))

    to_generate = [p for p in plan if p[6] == "generate"]
    to_skip = [p for p in plan if p[6] == "skip"]

    print(f"\n📋 계획:")
    print(f"   생성/재생성 대상: {len(to_generate)} 개")
    print(f"   스킵(내용 동일): {len(to_skip)} 개")

    if to_generate:
        print(f"\n생성 예정 파일 (처음 10개만 표시):")
        for ch, pane, owner, _, out_path, _, _ in to_generate[:10]:
            rel = os.path.relpath(out_path, BASE_FOLDER)
            print(f"   • {rel}  (챕터 {ch}, 그림칸 {pane}, {owner})")
        if len(to_generate) > 10:
            print(f"   ... 외 {len(to_generate) - 10}개")

    if args.dry_run:
        print("\n--dry-run 모드 — 실제 생성은 하지 않습니다.")
        return

    if not to_generate:
        print("\n✅ 새로 생성할 파일이 없습니다. 모두 최신.")
        return

    # 비용 추정
    total_chars = sum(len(p[3]) for p in to_generate)
    rate = 0.030 if args.model == "tts-1-hd" else 0.015
    est_cost = total_chars / 1000 * rate
    print(f"\n💰 비용 추정: {total_chars:,} 자 × ${rate}/1K = ${est_cost:.3f}")

    # 사용자 확인
    if not args.yes:
        print(f"\n계속 진행하시겠어요? (model={args.model}, voice={args.voice}, speed={args.speed})")
        ans = input("[y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("취소됨.")
            return
    else:
        print(f"\n--yes 플래그로 자동 진행 (model={args.model}, voice={args.voice}, speed={args.speed})")

    # 실제 생성
    print("\n🎙️ 음성 생성 시작...\n")
    success = 0
    failed = []
    for i, (ch, pane, owner, sentence, out_path, sidecar_path, _) in enumerate(to_generate, 1):
        rel = os.path.relpath(out_path, BASE_FOLDER)
        print(f"[{i}/{len(to_generate)}] {rel} ...", end=" ", flush=True)
        try:
            generate_one(openai_client, sentence, out_path, args.voice, args.model, args.speed)
            write_sidecar(sidecar_path, sentence)  # 성공 시에만 사이드카 갱신
            print("✅")
            success += 1
        except Exception as e:
            print(f"❌  {e}")
            failed.append((rel, str(e)))

    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"✅ 성공: {success} / {len(to_generate)}")
    if failed:
        print(f"❌ 실패: {len(failed)}")
        for rel, err in failed:
            print(f"   • {rel}: {err}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"\n다음 단계: git add audio/ && git commit -m 'Add TTS audio files' && git push")


if __name__ == "__main__":
    main()

"""
generate_tts.py — AnswerBank 기준으로 OpenAI TTS mp3 파일 생성

[사용법]
1. 환경 변수에 OPENAI_API_KEY 설정 (또는 .env 파일):
     export OPENAI_API_KEY=sk-...
   또는 명령행에서 직접: OPENAI_API_KEY=sk-... python3 generate_tts.py

2. 실행:
     python3 generate_tts.py

3. 옵션:
     --dry-run        실제 호출 없이 어떤 파일이 새로 만들어질지만 출력
     --force          이미 존재하는 mp3도 다시 생성
     --chapter 602    특정 챕터만 처리
     --voice shimmer  음성 변경 (기본: shimmer)
     --model tts-1-hd 모델 변경 (기본: tts-1-hd)
     --speed 0.9      재생 속도 (기본: 0.9)

[동작]
- Google Sheet 의 AnswerBank 시트를 읽어옴
- 각 행 (Chapter, Section, Owner, Sentences) 에 대해:
    audio/{Chapter}/{Section}_{Owner}.mp3 파일을 확인
    없으면 OpenAI TTS API 로 생성 후 저장
- 결과 요약 출력 (생성/스킵/실패 개수)

[푸시 워크플로우]
이 스크립트는 로컬에서 실행하고, 생성된 mp3 파일을 git add 한 뒤
git push 하면 Streamlit Cloud 가 새 음원과 함께 배포합니다.
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
ANSWER_BANK_TAB = "AnswerBank"
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
    """Streamlit secrets 가 아닌, 로컬 service_key.json 으로 인증."""
    if not os.path.exists(SERVICE_KEY_PATH):
        print(f"❌ service_key.json 을 찾을 수 없습니다: {SERVICE_KEY_PATH}")
        sys.exit(1)
    scope = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_KEY_PATH, scope)
    return gspread.authorize(creds)


def load_answer_bank_rows(client):
    """AnswerBank 시트의 모든 행을 dict 리스트로 반환."""
    try:
        ws = client.open(SHEET_NAME).worksheet(ANSWER_BANK_TAB)
    except gspread.exceptions.WorksheetNotFound:
        print(f"❌ '{ANSWER_BANK_TAB}' 시트가 없습니다. 먼저 웹앱에서 정답을 입력하세요.")
        sys.exit(1)
    return ws.get_all_records()


def get_audio_path(chapter, section, owner):
    """audio/{chapter}/{section}_{owner}.mp3"""
    return os.path.join(AUDIO_ROOT, str(chapter), f"{section}_{owner}.mp3")


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
    parser = argparse.ArgumentParser(description="AnswerBank → TTS mp3 generator")
    parser.add_argument("--dry-run", action="store_true", help="실제 생성 없이 계획만 출력")
    parser.add_argument("--force", action="store_true", help="기존 파일도 다시 생성")
    parser.add_argument("--chapter", type=str, default=None, help="특정 챕터만 처리")
    parser.add_argument("--voice", type=str, default="shimmer", help="OpenAI voice (기본: shimmer)")
    parser.add_argument("--model", type=str, default="tts-1-hd", help="OpenAI model (기본: tts-1-hd)")
    parser.add_argument("--speed", type=float, default=0.9, help="재생 속도 (기본: 0.9)")
    parser.add_argument("--yes", "-y", action="store_true", help="확인 프롬프트 스킵 (CI용)")
    args = parser.parse_args()

    # OpenAI key 확인 (환경변수 우선, 없으면 openai_key.txt 파일)
    api_key = load_openai_key()
    if not api_key:
        print("❌ OpenAI API 키를 찾을 수 없습니다.")
        print(f"   환경변수 OPENAI_API_KEY 또는 {OPENAI_KEY_PATH} 파일을 확인하세요.")
        sys.exit(1)
    openai_client = OpenAI(api_key=api_key)

    # 시트 로드
    print("📊 AnswerBank 시트 로드 중...")
    client = get_sheet_client()
    rows = load_answer_bank_rows(client)
    print(f"   총 {len(rows)} 행 발견")

    # 필터
    if args.chapter:
        rows = [r for r in rows if str(r.get("Chapter", "")).strip() == str(args.chapter)]
        print(f"   '챕터={args.chapter}' 필터 적용 → {len(rows)} 행")

    # 처리 계획
    plan = []  # (chapter, section, owner, sentences, out_path, action)
    for r in rows:
        chapter = str(r.get("Chapter", "")).strip()
        section = str(r.get("Section", "")).strip()
        owner = str(r.get("Owner", "")).strip()
        sentences = r.get("Sentences", "")
        if not chapter or not section or not owner or not sentences:
            continue
        if not sentences.strip():
            continue
        out_path = get_audio_path(chapter, section, owner)
        if os.path.exists(out_path) and not args.force:
            plan.append((chapter, section, owner, sentences, out_path, "skip"))
        else:
            plan.append((chapter, section, owner, sentences, out_path, "generate"))

    to_generate = [p for p in plan if p[5] == "generate"]
    to_skip = [p for p in plan if p[5] == "skip"]

    print(f"\n📋 계획:")
    print(f"   생성 대상: {len(to_generate)} 개")
    print(f"   스킵(이미 존재): {len(to_skip)} 개")

    if to_generate:
        print(f"\n생성 예정 파일:")
        for ch, sec, owner, _, out_path, _ in to_generate:
            rel = os.path.relpath(out_path, BASE_FOLDER)
            print(f"   • {rel}  (챕터 {ch}, 구간 {sec}, {owner})")

    if args.dry_run:
        print("\n--dry-run 모드 — 실제 생성은 하지 않습니다.")
        return

    if not to_generate:
        print("\n✅ 새로 생성할 파일이 없습니다.")
        return

    # 비용 추정 (tts-1-hd: $0.030 per 1K chars, tts-1: $0.015 per 1K chars)
    total_chars = sum(len(p[3]) for p in to_generate)
    rate = 0.030 if args.model == "tts-1-hd" else 0.015
    est_cost = total_chars / 1000 * rate
    print(f"\n💰 비용 추정: {total_chars:,} 자 × ${rate}/1K = ${est_cost:.3f}")

    # 사용자 확인 (--yes 면 스킵)
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
    for i, (ch, sec, owner, sentences, out_path, _) in enumerate(to_generate, 1):
        rel = os.path.relpath(out_path, BASE_FOLDER)
        print(f"[{i}/{len(to_generate)}] {rel} ...", end=" ", flush=True)
        try:
            generate_one(openai_client, sentences, out_path, args.voice, args.model, args.speed)
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

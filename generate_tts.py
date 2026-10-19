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
- Supabase `sentence_bank` 를 읽어옴 (sync_notion.py로 채워진 데이터 · 구 SentenceBank 시트, 0907 이전)
- 각 행 (Chapter, Pane, Owner, Sentence) 에 대해:
    audio/{Chapter}/{Pane}_{Owner}.mp3 + audio/{Chapter}/{Pane}_{Owner}.txt 페어 확인
    - mp3 없음                           → 생성
    - mp3 있고 .txt 내용 == 현재 Sentence → skip
    - mp3 있고 .txt 내용 != 현재 Sentence → 재생성 (내용 바뀜)
    - --force 플래그                      → 무조건 재생성
- 사이드카 .txt 파일은 mp3와 짝지어 저장되어, 다음 실행 때 변경 감지 기준이 됨

[창고 이전 2단계 — 이중 쓰기 (2026-10-19, 웹앱 docs/art-storage-spec.md §4-5·§5)]
- mp3 생성 성공 직후 **창고 파일 그리고** R2 버킷·장부에도 쓴다:
    열쇠 = 내용 지문 `voice/{sha256 앞 16자}.mp3`(불변, Cache-Control 1년 immutable · 이미 있으면 PUT 건너뜀)
    장부 = Supabase `art_file`(kind=voice · 좌표 chapter/pane/owner · name `{Pane}_{Owner}.mp3` · legacy_path `audio/{챕터}/{Pane}_{Owner}.mp3`
           · sentence = 생성 원문 · source=tts) — 규칙은 `supa.record_art_file`(웹앱 `lib/artStore.recordArtFile`의 쌍둥이).
- secrets `R2_ENDPOINT`·`R2_ART_BUCKET`·`R2_ART_PUBLIC_BASE`·`R2_ART_ACCESS_KEY_ID`·`R2_ART_SECRET_ACCESS_KEY` 중 하나라도 비면
  "art 건너뜀" 한 줄만 찍고 종전대로(창고 커밋만) 간다. 버킷·장부 실패는 mp3 실패로 치지 않는다(창고 커밋은 그대로 — 장부 누락은 웹앱 대조 `/api/admin/art-parity`가 잡는다).
- 변경 감지는 아직 사이드카 .txt(5단계 창고 쓰기 끊기 때 장부 `sentence` 열로).

[옛 파일과의 공존]
- 기존 section 기반 mp3는 _old 접미사로 archive됨 (예: 602/1_박대호_old.mp3)
- 새 pane 기반 mp3는 깨끗한 양식 (예: 602/1_박대호.mp3, 602/2_박대호.mp3, ...)
- 같은 폴더에서 충돌 없음, 앱 transition 시 자연스럽게 옛 거 정리 가능
"""

import os
import sys
import time
import hashlib
import argparse
import supa  # 읽기원 = Supabase(2026-09-07 시트 폐선 1단계)
from pathlib import Path

# OpenAI SDK
try:
    from openai import OpenAI
except ImportError:
    print("❌ openai 패키지가 설치되어 있지 않습니다.")
    print("   설치: pip install openai")
    sys.exit(1)


BASE_FOLDER = os.path.dirname(os.path.abspath(__file__))
AUDIO_ROOT = os.path.join(BASE_FOLDER, "audio")
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






def load_sentence_bank_rows():
    """SentenceBank 전량을 dict 리스트로. **읽기원 = Supabase**(2026-09-07 시트 폐선 1단계).

    ★ 반환 키는 **시트 시절 그대로**(`Chapter`/`Pane`/`Owner`/`Sentence`)다 — 아래 공정을 안 건드리려고
      여기서만 이름을 옮긴다. 시트를 다시 볼 일은 없다.
    ★ 못 읽으면 **소리 내어 죽는다**(`supa.select_all`이 예외). 조용히 0행으로 넘어가면 그날 음원이
      통째로 안 생기고 아무도 모른다 — 매일 04:30에 도는 경로라 그게 제일 나쁘다.
    """
    rows = supa.select_all(
        "sentence_bank", "chapter,pane,owner,sentence", "chapter,pane,owner", "정답 문장"
    )
    return [
        {
            "Chapter": r.get("chapter", ""),
            "Pane": r.get("pane", ""),
            "Owner": r.get("owner", ""),
            "Sentence": r.get("sentence", ""),
        }
        for r in rows
    ]



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


# ─── 창고 이전 2단계: R2 버킷 + 장부 art_file (1019) ───────────────────────────
ART_ENV_KEYS = ("R2_ENDPOINT", "R2_ART_BUCKET", "R2_ART_PUBLIC_BASE", "R2_ART_ACCESS_KEY_ID", "R2_ART_SECRET_ACCESS_KEY")
ART_CACHE_CONTROL = "public, max-age=31536000, immutable"
_art_client = None


def art_env():
    """secrets 다섯이 전부 있으면 dict, 하나라도 비면 None(= 건너뜀)."""
    env = {k: (os.environ.get(k) or "").strip() for k in ART_ENV_KEYS}
    if not all(env.values()):
        return None
    env["R2_ENDPOINT"] = env["R2_ENDPOINT"].rstrip("/")
    return env


def art_hash(data):
    """내용 지문 = sha256 hex 앞 16자(웹앱 artStore.artHash와 같은 자리수)."""
    return hashlib.sha256(data).hexdigest()[:16]


def git_blob_sha(data):
    """창고 커밋이 이 파일에 매길 blob sha(sha1 'blob {n}\\0' + bytes) — 장부 legacy_sha(씨앗 재실행이 이 값으로 '이미 옮김'을 안다)."""
    h = hashlib.sha1()
    h.update(f"blob {len(data)}\0".encode("ascii"))
    h.update(data)
    return h.hexdigest()


def _client(env):
    global _art_client
    if _art_client is None:
        import boto3  # 워크플로가 pip install — 로컬 드라이런엔 없어도 된다(secrets 없으면 여기까지 안 온다)
        _art_client = boto3.client(
            "s3",
            endpoint_url=env["R2_ENDPOINT"],
            aws_access_key_id=env["R2_ART_ACCESS_KEY_ID"],
            aws_secret_access_key=env["R2_ART_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
    return _art_client


def art_put(env, key, data):
    """버킷에 올린다 — 열쇠가 지문이라 이미 있으면 건너뜀(멱등). 반환 True = 올림, False = 있었음."""
    s3 = _client(env)
    try:
        s3.head_object(Bucket=env["R2_ART_BUCKET"], Key=key)
        return False
    except Exception as e:  # 404 = 없음 → PUT · 그 밖(권한 등)은 PUT에서 다시 드러난다
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
        if code not in ("404", "NoSuchKey", "NotFound"):
            print(f"(HEAD {code or type(e).__name__})", end=" ")
    s3.put_object(
        Bucket=env["R2_ART_BUCKET"],
        Key=key,
        Body=data,
        ContentType="audio/mpeg",
        CacheControl=ART_CACHE_CONTROL,
    )
    return True


def store_art(env, chapter, pane, owner, sentence, data):
    """mp3 바이트 한 벌을 버킷 + 장부에. 반환 {"stored": bool, "changed": bool, "key": str}. 실패 = 예외(호출부가 mp3 실패로 치지 않는다)."""
    h = art_hash(data)
    key = f"voice/{h}.mp3"
    stored = art_put(env, key, data)
    rec = supa.record_art_file(
        {
            "kind": "voice",
            "chapter": chapter,
            "pane": pane,
            "owner": owner,
            "name": f"{pane}_{owner}.mp3",
            "legacy_path": f"audio/{chapter}/{pane}_{owner}.mp3",
            "legacy_sha": git_blob_sha(data),
            "sentence": sentence,
            "source": "tts",
        },
        {"object_key": key, "content_type": "audio/mpeg", "bytes": len(data), "hash": h},
        label=f"{chapter}/{pane}_{owner}",
    )
    return {"stored": stored, "changed": rec["changed"], "key": key}


def generate_one(openai_client, text, out_path, voice, model, speed):
    """OpenAI TTS 로 mp3 생성 후 out_path 에 저장. 생성된 바이트를 돌려준다(버킷·장부 쓰기용)."""
    Path(os.path.dirname(out_path)).mkdir(parents=True, exist_ok=True)
    response = openai_client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
        speed=speed,
    )
    data = response.content
    with open(out_path, "wb") as f:
        f.write(data)
    return data


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

    # SentenceBank 로드(Supabase)
    print("📊 SentenceBank 로드 중(Supabase)...")
    rows = load_sentence_bank_rows()
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

    # 창고 이전 2단계 — 버킷·장부 이중 쓰기 켜졌나(secrets 다섯 전부 있을 때만)
    art = art_env()
    if art:
        print(f"\n🪣 art 이중 쓰기 켜짐 — 버킷 {art['R2_ART_BUCKET']} ({art['R2_ART_PUBLIC_BASE']}) + 장부 art_file")
    else:
        missing = [k for k in ART_ENV_KEYS if not (os.environ.get(k) or "").strip()]
        print(f"\nℹ️ art 건너뜀 — R2 secrets 미설정({', '.join(missing)}) · 창고 커밋만")

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
    art_n = {"stored": 0, "unchanged": 0, "failed": []}  # 버킷·장부 영수증(mp3 성패와 별개)
    for i, (ch, pane, owner, sentence, out_path, sidecar_path, _) in enumerate(to_generate, 1):
        rel = os.path.relpath(out_path, BASE_FOLDER)
        print(f"[{i}/{len(to_generate)}] {rel} ...", end=" ", flush=True)
        try:
            data = generate_one(openai_client, sentence, out_path, args.voice, args.model, args.speed)
            write_sidecar(sidecar_path, sentence)  # 성공 시에만 사이드카 갱신
            print("✅", end=" ", flush=True)
            success += 1
        except Exception as e:
            print(f"❌  {e}")
            failed.append((rel, str(e)))
            continue
        if not art:
            print()
            continue
        # 창고 파일은 이미 섰다 — 버킷·장부는 덤이라 실패해도 mp3 실패로 치지 않는다(2단계 규약)
        try:
            r = store_art(art, ch, pane, owner, sentence, data)
            art_n["stored" if r["stored"] else "unchanged"] += 1
            print(f"🪣 {r['key']}" + ("" if r["stored"] else " (있음)") + ("" if r["changed"] else " 장부 같음"))
        except Exception as e:
            print(f"⚠️ art 실패: {e}")
            art_n["failed"].append((rel, str(e)))

    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"✅ 성공: {success} / {len(to_generate)}")
    if failed:
        print(f"❌ 실패: {len(failed)}")
        for rel, err in failed:
            print(f"   • {rel}: {err}")
    if art:
        print(f"🪣 art: 버킷 올림 {art_n['stored']} · 이미 있음 {art_n['unchanged']} · 실패 {len(art_n['failed'])}")
        for rel, err in art_n["failed"]:
            print(f"   • {rel}: {err}")
        if art_n["failed"]:
            print("   (버킷·장부 실패는 mp3 실패가 아니다 — 창고 커밋은 그대로, 누락은 웹앱 /api/admin/art-parity가 잡는다)")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"\n다음 단계: git add audio/ && git commit -m 'Add TTS audio files' && git push")

    # ★ 실패가 있으면 종료코드 1 (2026-08-01) — 종전엔 전부 실패해도 exit 0이라 워크플로가 초록으로 끝났다.
    #   OpenAI 잔액 소진·키 만료·모델 폐기 같은 사고가 조용히 지나가면 음원 없는 칸이 수업 당일에야 발각됨.
    #   ※ 성공분은 이미 저장·사이드카 갱신됐으니, 워크플로의 커밋 스텝은 if: always() 로 남긴다(부분 성과 보존).
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

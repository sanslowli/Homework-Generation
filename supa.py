"""
Supabase(PostgREST) 미러 — 시트 2단계(2026-08-22).

왜 있나:
  웹앱(kusukmap.com)이 ImageMatching·SentenceBank를 **Supabase에서 읽도록** 바뀌었다.
  이 레포의 sync 스크립트는 여전히 구글 시트에 쓰는데, 그것만으론 DB가 낡는다.
  → 시트에 쓰던 그 순간 **DB에도 같이 upsert**(이중 쓰기)한다.
  시트를 계속 쓰는 이유 = 웹앱(Vercel)과 이 레포(Actions)의 배포 시점이 달라서.
  양쪽에 같은 내용이 있으면 그 시차가 무해하고, 되돌릴 때도 시트가 살아 있다.

★ 절대 금지 — '전체 삭제 후 재기입'.
  2026-08-01 사고(ImageMatching이 텅 빈 채 남아 전 학생 담기 정보 증발)의 재현 경로다.
  여기 함수는 **upsert만** 한다. 사라진 키 정리가 필요하면 그때 별도로, 명시적으로.

★ 실패해도 스크립트를 죽이지 않는다(경고만).
  시트 쓰기가 정상 끝났다면 이번 회차는 성공이고, DB는 다음 실행이 따라잡는다.
  웹앱에도 시트 폴백이 있어 학생 화면은 안 멈춘다.

필요 secret (GitHub Actions):
  SUPABASE_URL              — https://xxxx.supabase.co
  SUPABASE_SERVICE_ROLE_KEY — 서버 전용 비밀키(RLS 우회)
  둘 중 하나라도 없으면 조용히 건너뛴다(= 종전과 동일하게 시트만 쓰고 끝).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

CHUNK = 500


def _env():
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        return None, None
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]
    return url, key


def _post(url, key, table, on_conflict, rows):
    body = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}?on_conflict={on_conflict}",
        data=body,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.status


def prune_stale(table, chapter_col, chapters, batch_iso, label=""):
    """이번 동기화에서 갱신되지 않은 행 정리 — **딱 이번에 쓴 챕터 안에서만**.

    노션이 정본인 SentenceBank는 예문이 지워지면 DB에서도 사라져야 한다. 그런데 '전부 지우고
    다시 넣기'는 2026-08-01 사고(전멸)의 길이라 절대 안 쓴다. 대신:
      ① 먼저 전 행 upsert(updated_at = 이번 배치 시각)
      ② 성공했을 때만, **이번에 건드린 챕터**의 행 중 updated_at이 배치 시각보다 오래된 것 삭제
    ⟹ 중간에 죽으면 삭제가 아예 안 일어나고(옛 데이터 온전), 손대지 않은 챕터는 영향 없음.
    """
    url, key = _env()
    if not url or not key or not chapters:
        return 0
    chs = ",".join(sorted({str(c).strip() for c in chapters if str(c).strip()}))
    if not chs:
        return 0
    q = f"{url}/rest/v1/{table}?{chapter_col}=in.({chs})&updated_at=lt.{urllib.parse.quote(batch_iso)}"
    req = urllib.request.Request(
        q,
        method="DELETE",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Prefer": "return=minimal",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60):
            print(f"🧹 Supabase 정리: {table} — 이번 배치에 없는 옛 행 삭제({label or chs})")
            return 1
    except Exception as e:
        print(f"⚠️ Supabase 정리 실패({table}) — 옛 행이 남을 뿐 데이터 손실은 없음: {e}")
        return 0


def upsert(table, on_conflict, rows, label=""):
    """rows(dict 리스트)를 table에 upsert. 성공 행 수 반환(건너뛰면 0).

    5xx·네트워크는 짧게 3회 재시도, 4xx는 즉시 포기(스키마·권한 오류라 반복해도 같음).
    """
    url, key = _env()
    if not url or not key:
        print(f"ℹ️ Supabase 미러 건너뜀({label or table}) — SUPABASE_URL/SERVICE_ROLE_KEY 미설정")
        return 0
    if not rows:
        return 0

    # ★ 배치 안 중복 키 제거(2026-08-22 실전 실패 수리) — 한 번의 upsert에 같은 키가 두 번 들어가면
    #   Postgres가 통째로 거부한다("ON CONFLICT DO UPDATE command cannot affect row a second time", 21000).
    #   시트엔 같은 칸이 두 줄로 남아 있을 수 있어(정규화 전 파일명 '1-3박대호.png' + 정규화 후 '1-3.png')
    #   실제로 터졌다. 규칙 = **뒤 행 승**(시트 읽기 규약과 동일 — 나중에 쓴 것이 최신).
    keys = [k.strip() for k in on_conflict.split(",") if k.strip()]
    if keys:
        dedup = {}
        for r in rows:
            dedup[tuple(str(r.get(k, "")) for k in keys)] = r
        if len(dedup) != len(rows):
            print(f"ℹ️ 배치 내 중복 키 {len(rows) - len(dedup)}건 정리(뒤 행 승) — {table}")
        rows = list(dedup.values())

    done = 0
    for i in range(0, len(rows), CHUNK):
        part = rows[i : i + CHUNK]
        for attempt in range(1, 4):
            try:
                _post(url, key, table, on_conflict, part)
                done += len(part)
                break
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                if e.code < 500 or attempt == 3:
                    print(f"⚠️ Supabase upsert 실패({table}, {e.code}) — 시트는 정상: {detail}")
                    return done
                time.sleep(2 * attempt)
            except Exception as e:  # 네트워크·타임아웃
                if attempt == 3:
                    print(f"⚠️ Supabase 연결 실패({table}) — 시트는 정상: {e}")
                    return done
                time.sleep(2 * attempt)
    print(f"🗄️ Supabase 미러: {table} {done}행 upsert")
    return done

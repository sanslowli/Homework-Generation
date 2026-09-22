"""
Supabase(PostgREST) 창구 — 이 레포 스크립트가 원장을 읽고 쓰는 유일한 문.

계보:
  2026-08-22 시트 2단계 — 시트에 쓰던 순간 DB에도 같이 upsert(이중 쓰기).
  2026-09-07 1단계 폐선 — TTS 읽기원이 시트 → `sentence_bank`(DB).
  2026-09-14 2단계 폐선 — sync 둘의 시트 쓰기 제거. **시트 = 동결 백업(쓰기 0)**, 원장 = DB 단독.
  2026-09-22 — 마지막 시트 소비자(backfill_image_filenames.py)도 `select`로 DB를 읽는다. gspread 의존 0.

★ 절대 금지 — '전체 삭제 후 재기입'.
  2026-08-01 사고(ImageMatching이 텅 빈 채 남아 전 학생 담기 정보 증발)의 재현 경로다.
  여기 함수는 **upsert만** 한다(`prune_stale`은 이번 배치가 만진 챕터 안의 낡은 행만, 전 행 upsert 성공 뒤에만).

★ DB 쓰기 실패 = 소리 내어 죽는다(exit 1, 0914).
  받아줄 시트가 없어졌으므로 조용한 부분 반영 = 유실이다. 크론이 Supabase 장애 때 빨개지는 것이 정상.

필요 secret (GitHub Actions):
  SUPABASE_URL              — https://xxxx.supabase.co
  SUPABASE_SERVICE_ROLE_KEY — 서버 전용 비밀키(RLS 우회)
  둘 중 하나라도 없으면 exit 1(0914 — 종전 "조용히 건너뛰고 시트만 쓴다"는 폐선과 함께 소멸).
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


def select_all(table, select="*", order=None, label=""):
    """table 전량을 dict 리스트로 읽는다. **없거나 못 읽으면 예외** — 빈 목록으로 눙치지 않는다.

    ★ PostgREST는 한 번에 **1000행**까지만 준다. 순진하게 한 번 읽으면 그 이상은 **조용히 빠지고**
      호출부는 "그만큼이 전부"로 안다(웹앱이 0814에 같은 자리에서 데였다 — `src/lib/db.ts`).
      그래서 Range 헤더로 페이지를 넘겨 끝까지 읽는다.
    ★ `order`는 **안정 정렬용이자 필수**다. 정렬이 없으면 페이지 경계에서 행이 겹치거나 빠진다.
      자연키를 그대로 준다(예: sentence_bank = "chapter,pane,owner").
    """
    url, key = _env()
    if not url or not key:
        raise RuntimeError(
            f"Supabase 미설정({label or table}) — SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY가 필요하다. "
            "워크플로 run 단계의 env를 확인할 것."
        )
    q = f"select={urllib.parse.quote(select)}"
    if order:
        q += f"&order={urllib.parse.quote(order)}"
    out, start = [], 0
    while True:
        req = urllib.request.Request(
            f"{url}/rest/v1/{table}?{q}",
            method="GET",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Range-Unit": "items",
                "Range": f"{start}-{start + CHUNK - 1}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as res:
            page = json.loads(res.read().decode("utf-8"))
        out += page
        if len(page) < CHUNK:
            break
        start += CHUNK
    return out


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


def select(table, query="", label=""):
    """table에서 행을 읽는다(PostgREST GET). query = "select=a,b&chapter=eq.605" 꼴(order 명시 권장).
    PostgREST 응답 상한(1000행)은 Range 헤더로 자동 페이지네이션한다.
    미설정·실패는 예외로 올린다 — 읽기원이 DB뿐이라 빈 목록을 조용히 돌리면 호출부가 '매칭 0건'으로 오독한다(0914 규약)."""
    url, key = _env()
    if not url or not key:
        raise RuntimeError(f"SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 미설정 — {label or table}을(를) 읽을 수 없다")
    out, start = [], 0
    while True:
        req = urllib.request.Request(
            f"{url}/rest/v1/{table}?{query}",
            headers={"apikey": key, "Authorization": f"Bearer {key}", "Range": f"{start}-{start + 999}"},
        )
        with urllib.request.urlopen(req, timeout=60) as res:
            chunk = json.loads(res.read().decode("utf-8"))
        if not isinstance(chunk, list):
            raise RuntimeError(f"{label or table} 읽기 응답이 목록이 아니다: {str(chunk)[:200]}")
        out.extend(chunk)
        if len(chunk) < 1000:
            return out
        start += 1000

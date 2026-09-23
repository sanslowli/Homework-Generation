import streamlit as st
import streamlit.components.v1 as components
import os
import re
import random
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import base64
import unicodedata
import textwrap
from io import BytesIO
import calendar

# ==========================================
# [설정] 기본 경로 및 구글 시트
# ==========================================
st.set_page_config(page_title="Syntax Pitching™", layout="wide")

st.markdown("""
    <style>
        .stApp, .stMarkdown, p, h1, h2, h3, h4, div[data-testid="stMarkdownContainer"] {
            font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans KR", sans-serif !important;
        }
        .stButton>button { border-radius: 8px; font-weight: 500; }
        .sidebar-title { font-size: 28px; font-weight: 700; margin-bottom: 20px; }
        .footer-text { color: #888; margin-top: 20px; font-size: 14px; }
        @media only screen and (max-width: 768px) {
            h1 { font-size: 32px !important; font-weight: 700 !important; line-height: 1.3 !important; }
            h3 { font-size: 20px !important; font-weight: 600 !important; margin-top: 10px !important; }
            .stMarkdown p { font-size: 16px !important; line-height: 1.5 !important; }
            .sidebar-title { font-size: 22px !important; margin-bottom: 15px !important; }
            .footer-text { font-size: 12px !important; color: #999 !important; }
            .stButton>button { font-size: 16px !important; }
        }
    </style>
    """, unsafe_allow_html=True)

BASE_FOLDER = os.path.dirname(os.path.abspath(__file__))
TARGET_FOLDERS = ["Syntax Pitching", "Syntax Only", "Syntax + Open-ended Question"]
ALLOWED_SUBFOLDERS = ["현행 챕터", "지난 챕터"]
# 매칭 드롭다운 후보 수집용 — 보류/보관 학생도 포함 (수업 잠시 쉬는 중인 학생의 그림도 매칭 가능)
MATCHING_SUBFOLDERS = ["현행 챕터", "지난 챕터", "보류", "보관", "보관 폴더"]
SHEET_NAME = "Syntax Pitching DB"
FONT_PATH = os.path.join(BASE_FOLDER, "font.ttf")

def get_kst_now():
    return datetime.utcnow() + timedelta(hours=9)

@st.cache_resource
def init_connection():
    try:
        credentials = st.secrets["connections"]["gsheets"]
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(credentials), scope)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"구글 시트 연결 실패: {e}")
        return None

def get_data_from_sheet(client):
    try:
        sheet = client.open(SHEET_NAME).sheet1
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except:
        return pd.DataFrame(columns=["Timestamp", "Student", "Chapter", "Image", "Result"])

def save_to_sheet(client, student, chapter, image, result):
    try:
        sheet = client.open(SHEET_NAME).sheet1
        if not sheet.get_all_values():
            sheet.append_row(["Timestamp", "Student", "Chapter", "Image", "Result"])
        timestamp = get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, student, chapter, image, result])
        st.cache_data.clear()
    except Exception as e:
        pass

# ==========================================
# [정답 시트] Answers 워크시트 - 자동 생성/조회/저장
# ==========================================
ANSWERS_HEADER = ["Student", "Chapter", "Image", "Answer", "Updated"]

# ==========================================
# [정답 시트 v3] SentenceBank — 그림칸별 1문장 (노션 sync로 자동 채워짐)
# ──────────────────────────────────────────
# SentenceBank : (Chapter, Pane, Owner) → Sentence  (sync_notion.py로 자동 채움)
# ImageMatching: (ImageStudent, Chapter, Image) → ContentOwner (학생이 매칭)
# 오디오 파일  : audio/{Chapter}/{Pane}_{Owner}.mp3 (generate_tts.py 로 생성)
#
# [v2 — AnswerBank/구간 단위는 deprecated]
# 옛 시트(AnswerBank, (Chapter, Section, Owner) → 여러 문장 합본)와 옛 오디오
# (audio/{Chapter}/{Section}_{Owner}.mp3) 는 그대로 두고 학생 흐름에서는 안 씀.
# 노션의 챕터별 그림칸 → 구간 매핑은 SentenceBank의 Section 컬럼으로 동기화돼 있음.
# ==========================================
IMAGE_MATCHING_HEADER = ["ImageStudent", "Chapter", "Image", "ContentOwner", "Updated"]
SENTENCE_BANK_TAB = "SentenceBank"


@st.cache_data(ttl=120, show_spinner=False)
def _load_sentence_bank_rows(_client):
    """SentenceBank 시트의 모든 행 dict 리스트 반환 (raw)."""
    if _client is None:
        return []
    try:
        ws = _client.open(SHEET_NAME).worksheet(SENTENCE_BANK_TAB)
        return ws.get_all_records()
    except Exception as e:
        if "429" not in str(e):
            st.error(f"[디버그] _load_sentence_bank_rows 에러: {type(e).__name__}: {e}")
        return []


def load_sentence_bank(_client):
    """{(chapter, pane_str, owner): sentence} 반환. 음원/정답 lookup용."""
    result = {}
    for r in _load_sentence_bank_rows(_client):
        chapter = str(r.get("Chapter", "")).strip()
        pane = str(r.get("Pane", "")).strip()
        owner = str(r.get("Owner", "")).strip()
        sentence = r.get("Sentence", "")
        if chapter and pane and owner and sentence:
            result[(chapter, pane, owner)] = sentence
    return result


def load_chapter_mapping(_client):
    """{(chapter, section_str): [sorted_panes]} 반환.
    이미지 파일명 "1-3.png" → (section="1", slot=3) 에서 실제 pane 번호 찾기용."""
    chapter_section_panes = {}
    for r in _load_sentence_bank_rows(_client):
        chapter = str(r.get("Chapter", "")).strip()
        section = str(r.get("Section", "")).strip()
        pane_str = str(r.get("Pane", "")).strip()
        if not (chapter and section and pane_str):
            continue
        try:
            pane_int = int(pane_str)
        except ValueError:
            continue
        chapter_section_panes.setdefault((chapter, section), set()).add(pane_int)
    return {k: sorted(v) for k, v in chapter_section_panes.items()}


def extract_section_slot_from_filename(image_filename):
    """'1-3.png' → ('1', 3), '11-2.png' → ('11', 2). 실패 시 (None, None).
    소유자 이름이 붙은 '1-3배해주.png' 도 ('1', 3) 으로 허용(슬롯의 앞 숫자만 파싱)."""
    try:
        name = os.path.splitext(os.path.basename(image_filename))[0]
        if "-" in name:
            parts = name.split("-", 1)
            section = parts[0].strip()
            slot_part = parts[1].strip()
            m = re.match(r"^(\d+)", slot_part)
            if section.isdigit() and m:
                return section, int(m.group(1))
    except Exception:
        pass
    return None, None


def match_image_key(image_filename):
    """매칭 시트 키로 쓸 정규화된 파일명. '1-3배해주.png' → '1-3.png'.
    파싱 불가하면 원본 basename 반환(하위호환)."""
    section, slot = extract_section_slot_from_filename(image_filename)
    if section is not None and slot is not None:
        return f"{section}-{slot}.png"
    return os.path.basename(image_filename)


def owner_suffix_from_filename(image_filename):
    """'1-3배해주.png' → '배해주'. 주인 suffix 없으면 ''."""
    try:
        name = os.path.splitext(os.path.basename(image_filename))[0]
        if "-" in name:
            slot_part = name.split("-", 1)[1].strip()
            m = re.match(r"^\d+(.*)$", slot_part)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    return ""


def image_to_pane(image_filename, chapter, chapter_mapping):
    """이미지 파일명을 실제 그림칸 번호로 변환.

    예: 601 챕터에서 '2-3.png' → section 2, slot 3.
        601의 section 2가 panes [4, 5, 6] 이라면 → pane 6 (slot 3 = 3번째 = 6)
    """
    section, slot = extract_section_slot_from_filename(image_filename)
    if section is None or slot is None:
        return None
    panes = chapter_mapping.get((str(chapter), section))
    if not panes or slot < 1 or slot > len(panes):
        return None
    return panes[slot - 1]


def get_audio_path_pane(chapter, pane, owner):
    """audio/{chapter}/{pane}_{owner}.mp3 — pane 단위 오디오 (신규)."""
    return os.path.join(BASE_FOLDER, "audio", str(chapter), f"{pane}_{owner}.mp3")

def get_or_create_image_matching_sheet(client):
    """ImageMatching 워크시트 반환. 없으면 생성."""
    try:
        spreadsheet = client.open(SHEET_NAME)
        try:
            ws = spreadsheet.worksheet("ImageMatching")
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title="ImageMatching", rows=2000, cols=5)
            ws.append_row(IMAGE_MATCHING_HEADER)
            return ws
        header = ws.row_values(1)
        if not header:
            ws.append_row(IMAGE_MATCHING_HEADER)
        return ws
    except Exception:
        return None

@st.cache_data(ttl=60, show_spinner=False)
def load_image_matchings(_client):
    """{(image_student, chapter, image): content_owner} 반환. 60초 캐시."""
    if _client is None:
        return {}
    try:
        ws = get_or_create_image_matching_sheet(_client)
        if ws is None:
            return {}
        rows = ws.get_all_records()
        result = {}
        for r in rows:
            img_student = str(r.get("ImageStudent", "")).strip()
            chapter = str(r.get("Chapter", "")).strip()
            image = match_image_key(str(r.get("Image", "")).strip())  # '1-3배해주.png'→'1-3.png'
            owner = str(r.get("ContentOwner", "")).strip()
            if img_student and chapter and image and owner:
                result[(img_student, chapter, image)] = owner
        return result
    except Exception:
        return {}

def save_image_matching(client, image_student, chapter, image, content_owner):
    """(ImageStudent, Chapter, Image) 키로 upsert. 빈 ContentOwner면 매칭 해제.
    Image 는 항상 정규화된 맨이름('1-3.png')으로 저장·비교(파일명에 주인 붙어도 일관)."""
    if client is None:
        return False
    try:
        ws = get_or_create_image_matching_sheet(client)
        if ws is None:
            return False
        image = match_image_key(image)
        rows = ws.get_all_values()
        timestamp = get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
        found_row = None
        for i, r in enumerate(rows[1:], start=2):
            if len(r) >= 3 and r[0] == image_student and r[1] == str(chapter) and match_image_key(r[2]) == image:
                found_row = i
                break
        if found_row:
            ws.update(f"C{found_row}:E{found_row}", [[image, content_owner, timestamp]])
        else:
            ws.append_row([image_student, str(chapter), image, content_owner, timestamp])
        load_image_matchings.clear()
        return True
    except Exception:
        return False


def try_rename_image_on_github(image_path, content_owner):
    """매칭된 그림 파일을 GitHub 에서 '<섹션-슬롯><주인>.png' 로 rename(커밋).
    목적: origin pull 후 로컬 폴더에서 아직 매칭 안 된 파일(이름 없는 것)을 육안 식별.
    실패해도 매칭 저장에는 영향 없음(비차단). secrets(github_pat/github_repo) 미설정 시 조용히 skip."""
    try:
        gh_pat = st.secrets.get("github_pat", "")
        gh_repo = st.secrets.get("github_repo", "")
    except Exception:
        gh_pat, gh_repo = "", ""
    if not (gh_pat and gh_repo and content_owner):
        return False
    try:
        import requests
        from urllib.parse import quote
        section, slot = extract_section_slot_from_filename(os.path.basename(image_path))
        if section is None or slot is None:
            return False
        ext = os.path.splitext(image_path)[1] or ".png"
        old_name = os.path.basename(image_path)
        new_name = f"{section}-{slot}{content_owner}{ext}"
        if old_name == new_name:
            return True  # 이미 정리됨
        rel_dir = os.path.relpath(os.path.dirname(image_path), BASE_FOLDER).replace(os.sep, "/")
        old_path = old_name if rel_dir in (".", "") else f"{rel_dir}/{old_name}"
        new_path = new_name if rel_dir in (".", "") else f"{rel_dir}/{new_name}"
        headers = {
            "Authorization": f"Bearer {gh_pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        api = f"https://api.github.com/repos/{gh_repo}/contents/"
        g = requests.get(api + quote(old_path), headers=headers, params={"ref": "main"}, timeout=20)
        if g.status_code != 200:
            return False
        info = g.json()
        sha = info.get("sha")
        content_b64 = info.get("content")
        if not (sha and content_b64):
            return False
        p = requests.put(api + quote(new_path), headers=headers, timeout=20, json={
            "message": f"match: {old_name} -> {new_name} ({content_owner})",
            "content": content_b64.replace("\n", ""),
            "branch": "main",
        })
        if p.status_code not in (200, 201):
            return False
        requests.delete(api + quote(old_path), headers=headers, timeout=20, json={
            "message": f"match cleanup: remove {old_name}",
            "sha": sha,
            "branch": "main",
        })
        return True
    except Exception:
        return False

def extract_section_from_filename(image_filename):
    """'1-3.png' → '1', '11-2.png' → '11'. 추출 실패 시 None."""
    try:
        name = os.path.splitext(os.path.basename(image_filename))[0]
        if "-" in name:
            first = name.split("-")[0].strip()
            if first.isdigit():
                return first
    except Exception:
        pass
    return None

def get_audio_relative_path(chapter, section, owner):
    return os.path.join("audio", str(chapter), f"{section}_{owner}.mp3")

def get_audio_absolute_path(chapter, section, owner):
    return os.path.join(BASE_FOLDER, get_audio_relative_path(chapter, section, owner))

def render_audio_player(audio_abs_path, label="🔊 강세 잡기"):
    """녹음 락 + 강세 잡기 + 처음부터 위젯.
    흐름:
      [🎤 녹음 시작] → [⏺ 녹음 중 (탭=정지)] → [▶ 내 녹음 듣기 | 🎤 다시]
      녹음 완료 시점에 강세 잡기 버튼이 활성화됨.
    녹음 데이터:
      - MediaRecorder API (브라우저 표준)
      - Blob URL 로 메모리에만 존재, 페이지 이동/새로고침 시 자동 폐기
      - 서버로 전송 없음
    """
    try:
        with open(audio_abs_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
    except Exception:
        components.html(
            '<div style="margin:0;color:#bbb;font-size:13px;padding:10px 12px;'
            'border:1px dashed #ddd;border-radius:6px;'
            'font-family:-apple-system,system-ui,sans-serif;">'
            '음원 파일을 불러오지 못했습니다.</div>',
            height=48, scrolling=False
        )
        return

    uid = base64.b64encode(os.urandom(6)).decode().replace("/", "_").replace("+", "-").rstrip("=")
    hold_label = "⏸ 떼면 재개"
    hint_default = "👆 꾹 누르면 일시정지"
    hint_hold = "계속 누르고 있으세요"
    locked_label = "🔒 정답 듣기"
    locked_hint = "먼저 내 목소리를 녹음하세요"

    html = f"""
    <div style="margin:0;font-family:-apple-system,system-ui,'Noto Sans KR',sans-serif;">
      <!-- 정답 mp3 (선생님이 만들어둔 강세 음원) -->
      <audio id="aud_{uid}" src="data:audio/mp3;base64,{audio_b64}" preload="auto"></audio>
      <!-- 학생 녹음 (Blob URL로 in-memory) -->
      <audio id="myaud_{uid}"></audio>

      <!-- 1단: 녹음 컨트롤 (state-based innerHTML 교체) -->
      <div id="recBar_{uid}" style="margin-bottom:6px;">
        <button id="recBtn_{uid}"
          style="width:100%;background:#E74C3C;color:white;border:none;border-radius:8px;
                 padding:10px 14px;font-size:15px;font-weight:600;cursor:pointer;
                 user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;
                 transition:background 0.12s;">
          🎤 녹음 시작
        </button>
      </div>

      <!-- 2단: 정답 듣기 (초기 lock 상태) -->
      <div style="display:flex;gap:6px;align-items:stretch;">
        <button id="btn_{uid}" disabled
          data-default="{label}" data-hold="{hold_label}"
          data-hint-default="{hint_default}" data-hint-hold="{hint_hold}"
          data-locked="{locked_label}" data-locked-hint="{locked_hint}"
          style="flex:1;background:#BDC3C7;color:white;border:none;border-radius:8px;
                 padding:8px 12px;cursor:not-allowed;text-align:center;opacity:0.75;
                 user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;
                 transition:background 0.12s, opacity 0.12s;">
          <div style="font-size:15px;font-weight:600;line-height:1.15;">{locked_label}</div>
          <div style="font-size:10.5px;font-weight:400;opacity:0.9;margin-top:3px;line-height:1;">{locked_hint}</div>
        </button>
        <button id="rst_{uid}" disabled
          title="처음부터 재생" aria-label="처음부터 재생"
          style="width:52px;background:#BDC3C7;color:white;border:none;border-radius:8px;
                 padding:0;cursor:not-allowed;font-size:22px;line-height:1;opacity:0.75;
                 user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;
                 transition:background 0.12s, opacity 0.12s;">
          ↻
        </button>
      </div>

      <script>
        (function(){{
          var aud = document.getElementById('aud_{uid}');
          var myAud = document.getElementById('myaud_{uid}');
          var recBar = document.getElementById('recBar_{uid}');
          var btn = document.getElementById('btn_{uid}');
          var rst = document.getElementById('rst_{uid}');

          // ══════════ 정답 듣기 (강세 잡기) ══════════
          var isHolding = false;
          var BG_DEFAULT = '#2980B9';
          var BG_HOLD = '#7F8C8D';
          var BG_LOCKED = '#BDC3C7';
          var BG_RST_ACTIVE = '#5DADE2';

          function paintMain(labelText, hintText, bg){{
            btn.innerHTML =
              '<div style="font-size:15px;font-weight:600;line-height:1.15;">' + labelText + '</div>' +
              '<div style="font-size:10.5px;font-weight:400;opacity:0.85;margin-top:3px;line-height:1;">' + hintText + '</div>';
            btn.style.background = bg;
          }}
          function resetVisual(){{ paintMain(btn.dataset.default, btn.dataset.hintDefault, BG_DEFAULT); }}
          function holdVisual(){{ paintMain(btn.dataset.hold, btn.dataset.hintHold, BG_HOLD); }}
          function lockedVisual(){{ paintMain(btn.dataset.locked, btn.dataset.lockedHint, BG_LOCKED); }}

          function unlockAnswer(){{
            btn.disabled = false;
            btn.style.cursor = 'pointer';
            btn.style.opacity = '1';
            rst.disabled = false;
            rst.style.cursor = 'pointer';
            rst.style.opacity = '1';
            rst.style.background = BG_RST_ACTIVE;
            resetVisual();
          }}
          function lockAnswer(){{
            if (!aud.paused) aud.pause();
            aud.currentTime = 0;
            btn.disabled = true;
            btn.style.cursor = 'not-allowed';
            btn.style.opacity = '0.75';
            rst.disabled = true;
            rst.style.cursor = 'not-allowed';
            rst.style.opacity = '0.75';
            rst.style.background = BG_LOCKED;
            isHolding = false;
            lockedVisual();
          }}

          aud.addEventListener('ended', function(){{
            aud.currentTime = 0;
            isHolding = false;
            if (!btn.disabled) resetVisual();
          }});

          function pressDown(e){{
            if (btn.disabled) return;
            if (e && e.cancelable) e.preventDefault();
            if (aud.paused && (aud.currentTime === 0 || aud.currentTime >= (aud.duration - 0.05))) {{
              if (!myAud.paused) myAud.pause();  // 내 녹음 재생 중이면 정지
              aud.currentTime = 0;
              aud.volume = 1;
              aud.play().catch(function(err){{ console.error(err); }});
              isHolding = false;
              resetVisual();
            }} else if (!aud.paused) {{
              aud.volume = 0;
              aud.pause();
              isHolding = true;
              holdVisual();
            }}
          }}
          function pressUp(e){{
            if (btn.disabled) return;
            if (e && e.cancelable) e.preventDefault();
            if (isHolding && aud.paused) {{
              aud.volume = 1;
              aud.play().catch(function(err){{ console.error(err); }});
            }}
            isHolding = false;
            resetVisual();
          }}
          function restart(e){{
            if (rst.disabled) return;
            if (e && e.cancelable) e.preventDefault();
            if (!myAud.paused) myAud.pause();
            aud.currentTime = 0;
            aud.volume = 1;
            aud.play().catch(function(err){{ console.error(err); }});
            isHolding = false;
            resetVisual();
          }}
          btn.addEventListener('mousedown', pressDown);
          btn.addEventListener('mouseup', pressUp);
          btn.addEventListener('mouseleave', pressUp);
          btn.addEventListener('touchstart', pressDown, {{passive:false}});
          btn.addEventListener('touchend', pressUp, {{passive:false}});
          btn.addEventListener('touchcancel', pressUp, {{passive:false}});
          btn.addEventListener('contextmenu', function(e){{ e.preventDefault(); }});
          rst.addEventListener('click', restart);
          rst.addEventListener('contextmenu', function(e){{ e.preventDefault(); }});

          // ══════════ 녹음 ══════════
          var mediaRecorder = null;
          var audioChunks = [];
          var myRecordingUrl = null;
          var recordingStartTime = 0;
          var recordingTimer = null;
          var micStream = null;

          function setIdleState(){{
            recBar.innerHTML =
              '<button id="recBtn_{uid}" ' +
              'style="width:100%;background:#E74C3C;color:white;border:none;border-radius:8px;' +
              'padding:10px 14px;font-size:15px;font-weight:600;cursor:pointer;' +
              'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;' +
              'transition:background 0.12s;">🎤 녹음 시작</button>';
            document.getElementById('recBtn_{uid}').addEventListener('click', startRecording);
            lockAnswer();
          }}
          function setRecordingState(){{
            recBar.innerHTML =
              '<button id="recBtn_{uid}" ' +
              'style="width:100%;background:#922B21;color:white;border:none;border-radius:8px;' +
              'padding:9px 14px;font-size:15px;font-weight:600;cursor:pointer;text-align:center;' +
              'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;' +
              'animation:pulse_{uid} 1.2s ease-in-out infinite;">' +
              '<div>⏺ 녹음 중 · <span class="timer" style="font-variant-numeric:tabular-nums;">0:00</span></div>' +
              '<div style="font-size:10.5px;font-weight:400;opacity:0.85;margin-top:2px;line-height:1;">탭하면 정지</div>' +
              '</button>';
            document.getElementById('recBtn_{uid}').addEventListener('click', stopRecording);
            lockAnswer();
          }}
          function setRecordedState(){{
            recBar.innerHTML =
              '<div style="display:flex;gap:6px;">' +
              '<button id="playMine_{uid}" ' +
              'style="flex:1;background:#16A085;color:white;border:none;border-radius:8px;' +
              'padding:10px 12px;font-size:14px;font-weight:600;cursor:pointer;' +
              'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;">' +
              '<span id="playMineLbl_{uid}">▶ 내 녹음 듣기</span>' +
              '</button>' +
              '<button id="reRec_{uid}" ' +
              'style="width:100px;background:#E67E22;color:white;border:none;border-radius:8px;' +
              'padding:10px 6px;font-size:13px;font-weight:600;cursor:pointer;' +
              'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;">🎤 다시 녹음</button>' +
              '</div>';
            document.getElementById('playMine_{uid}').addEventListener('click', togglePlayMine);
            document.getElementById('reRec_{uid}').addEventListener('click', startRecording);
            unlockAnswer();
          }}

          async function startRecording(){{
            try {{
              // 진행 중인 재생 모두 멈춤
              if (!aud.paused) aud.pause();
              if (!myAud.paused) myAud.pause();

              micStream = await navigator.mediaDevices.getUserMedia({{audio: true}});
              mediaRecorder = new MediaRecorder(micStream);
              audioChunks = [];
              mediaRecorder.ondataavailable = function(e){{
                if (e.data.size > 0) audioChunks.push(e.data);
              }};
              mediaRecorder.onstop = function(){{
                var blob = new Blob(audioChunks, {{type: mediaRecorder.mimeType || 'audio/webm'}});
                if (myRecordingUrl) URL.revokeObjectURL(myRecordingUrl);
                myRecordingUrl = URL.createObjectURL(blob);
                myAud.src = myRecordingUrl;
                if (micStream){{
                  micStream.getTracks().forEach(function(t){{ t.stop(); }});
                  micStream = null;
                }}
                stopTimer();
                setRecordedState();
              }};
              mediaRecorder.start();
              recordingStartTime = Date.now();
              setRecordingState();
              startTimer();
            }} catch (err){{
              console.error('Mic access error:', err);
              alert('마이크 권한이 필요합니다. 브라우저 주소창 옆 자물쇠 → 마이크 허용으로 설정해 주세요.');
            }}
          }}
          function stopRecording(){{
            if (mediaRecorder && mediaRecorder.state === 'recording'){{
              mediaRecorder.stop();
            }}
          }}
          function startTimer(){{
            recordingTimer = setInterval(function(){{
              var elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
              var mins = Math.floor(elapsed / 60);
              var secs = elapsed % 60;
              var el = document.querySelector('#recBtn_{uid} .timer');
              if (el) el.textContent = mins + ':' + (secs < 10 ? '0' + secs : secs);
            }}, 250);
          }}
          function stopTimer(){{
            if (recordingTimer){{
              clearInterval(recordingTimer);
              recordingTimer = null;
            }}
          }}

          function togglePlayMine(){{
            var lbl = document.getElementById('playMineLbl_{uid}');
            if (myAud.paused){{
              if (!aud.paused) aud.pause();  // 정답 재생 중이면 멈춤
              myAud.currentTime = 0;
              myAud.play().catch(function(err){{ console.error(err); }});
              if (lbl) lbl.textContent = '■ 정지';
            }} else {{
              myAud.pause();
              if (lbl) lbl.textContent = '▶ 내 녹음 듣기';
            }}
          }}
          myAud.addEventListener('ended', function(){{
            var lbl = document.getElementById('playMineLbl_{uid}');
            if (lbl) lbl.textContent = '▶ 내 녹음 듣기';
          }});

          // 페이지 떠날 때 마지막 정리 (확정적 폐기)
          window.addEventListener('beforeunload', function(){{
            if (myRecordingUrl) URL.revokeObjectURL(myRecordingUrl);
            if (micStream) micStream.getTracks().forEach(function(t){{ t.stop(); }});
          }});

          // 초기 바인딩 (idle 상태로 시작)
          document.getElementById('recBtn_{uid}').addEventListener('click', startRecording);
        }})();
      </script>

      <style>
        @keyframes pulse_{uid} {{
          0%, 100% {{ box-shadow: 0 0 0 0 rgba(231,76,60,0.5); }}
          50%      {{ box-shadow: 0 0 0 6px rgba(231,76,60,0); }}
        }}
      </style>
    </div>
    """
    components.html(html, height=132, scrolling=False)


def render_section_audio_grid(current_image_path, image_student, chapter, sentence_bank, chapter_mapping, image_matchings):
    """구간 단위 멀티 그림칸 녹음·재생 그리드 위젯 (계산기 스타일).

    [레이아웃]
        Row 1 (빨강): [녹음 1] [녹음 2] [녹음 3] [녹음 4] | [🎤 다시]
        Row 2 (파랑): [정답 1] [정답 2] [정답 3] [정답 4] | [🔊 전체 듣기]

    [동작]
    - 빨강 N: 그림칸 N의 학생 녹음 (탭=시작/정지)
    - 파랑 N: 그림칸 N 의 [내 녹음 → 정답] 시퀀스 재생 (녹음 후 unlock)
    - 다시: 모든 녹음 초기화 + 파랑 버튼 전부 lock
    - 전체 듣기: 녹음된 모든 칸 [내 녹음 1→2→…→N] → [정답 1→2→…→N] 순차 재생
    - 어떤 듣기 버튼이든 누르면 직전 재생 즉시 중단 후 새로 시작
    - 매칭 안된/음원 없는 칸: 회색으로 잠금. 구간보다 적은 그림칸은 회색.
    - 매칭/녹음 상태 그대로 페이지 이동 시 휘발 (서버 전송 0).
    """
    image_filename = match_image_key(os.path.basename(current_image_path))
    section, _ = extract_section_slot_from_filename(image_filename)
    if section is None:
        return

    chapter_str = str(chapter)
    panes = chapter_mapping.get((chapter_str, section))
    if not panes:
        st.warning(f"⚠️ 챕터 {chapter_str} 구간 {section} 매핑이 빙고판 DB에 없습니다.")
        return

    # 한 파일 = 한 학생의 한 구간 답안 전체.
    # 화면에 표시된 그 파일의 owner 가, 이 구간 전체 panes 의 owner.
    matched_owner = image_matchings.get((image_student, chapter_str, image_filename))

    # pane 번호 낮은 순으로 정렬된 panes 를 버튼 1, 2, 3, ... 에 순차 배정.
    # owner 의 mp3 가 있는 pane 만 활성화, 없으면 잠금.
    pane_infos = []
    for slot_idx, pane in enumerate(sorted(panes), start=1):
        audio_b64 = None
        if matched_owner:
            mp3_path = get_audio_path_pane(chapter_str, pane, matched_owner)
            if os.path.exists(mp3_path):
                try:
                    with open(mp3_path, "rb") as f:
                        audio_b64 = base64.b64encode(f.read()).decode()
                except Exception:
                    pass
        pane_infos.append({
            "slot": slot_idx,
            "pane": pane,
            "ready": bool(audio_b64),
            "audio_b64": audio_b64,
        })

    # 그리드 컬럼: 실제 그림칸 수만큼만 (회색 padding 안 함). +1 = 특수 버튼 컬럼.
    n_pane_cols = len(pane_infos)
    n_total_cols = n_pane_cols + 1

    # JS 에 넘길 데이터
    js_panes = []
    for p in pane_infos:
        js_panes.append({
            "slot": p["slot"],
            "ready": p["ready"],
            "audio": f"data:audio/mp3;base64,{p['audio_b64']}" if p["audio_b64"] else None,
        })
    panes_json = json.dumps(js_panes)

    uid = base64.b64encode(os.urandom(6)).decode().replace("/", "_").replace("+", "-").rstrip("=")

    # 숨겨진 audio 엘리먼트 (각 그림칸마다 정답·내녹음 2개씩)
    audio_tags = ""
    for p in pane_infos:
        if p["audio_b64"]:
            audio_tags += f'<audio id="aud_answer_{p["slot"]}_{uid}" src="data:audio/mp3;base64,{p["audio_b64"]}" preload="auto"></audio>'
        audio_tags += f'<audio id="aud_mine_{p["slot"]}_{uid}" preload="auto"></audio>'

    # 그리드 row 1: 녹음 버튼들
    rec_buttons_html = ""
    for slot_idx in range(1, n_pane_cols + 1):
        if slot_idx <= len(pane_infos) and pane_infos[slot_idx - 1]["ready"]:
            # 실제 활성 녹음 버튼
            rec_buttons_html += (
                f'<button id="rec_btn_{slot_idx}_{uid}" data-slot="{slot_idx}" '
                f'style="background:#E74C3C;color:white;border:none;border-radius:8px;'
                f'padding:14px 0;font-size:18px;font-weight:700;cursor:pointer;'
                f'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;'
                f'transition:background 0.12s;">{slot_idx}</button>'
            )
        else:
            # 비활성: 회색 disabled
            rec_buttons_html += (
                f'<button disabled '
                f'style="background:#D5D8DC;color:#7F8C8D;border:none;border-radius:8px;'
                f'padding:14px 0;font-size:18px;font-weight:700;cursor:not-allowed;opacity:0.6;'
                f'user-select:none;">{slot_idx}</button>'
            )
    rec_buttons_html += (
        f'<button id="reset_btn_{uid}" '
        f'style="background:#E67E22;color:white;border:none;border-radius:8px;'
        f'padding:14px 0;font-size:13px;font-weight:600;cursor:pointer;'
        f'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;">🎙️ 다시</button>'
    )

    # 그리드 row 2 (NEW): 🔈 내 녹음 듣기 버튼들 + 🎙️ 합본 듣기 (초기 잠금, 녹음 완료 후 해당 슬롯만 unlock)
    play_mine_buttons_html = ""
    for slot_idx in range(1, n_pane_cols + 1):
        if slot_idx <= len(pane_infos) and pane_infos[slot_idx - 1]["ready"]:
            play_mine_buttons_html += (
                f'<button id="play_mine_{slot_idx}_{uid}" data-slot="{slot_idx}" disabled '
                f'style="background:#BDC3C7;color:white;border:none;border-radius:8px;'
                f'padding:11px 0;font-size:17px;font-weight:600;cursor:not-allowed;opacity:0.5;'
                f'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;'
                f'transition:background 0.12s, opacity 0.12s;">🔈</button>'
            )
        else:
            play_mine_buttons_html += (
                f'<button disabled '
                f'style="background:#D5D8DC;color:#7F8C8D;border:none;border-radius:8px;'
                f'padding:11px 0;font-size:17px;font-weight:600;cursor:not-allowed;opacity:0.6;'
                f'user-select:none;">🔈</button>'
            )
    play_mine_buttons_html += (
        f'<button id="play_all_{uid}" disabled '
        f'style="background:#BDC3C7;color:white;border:none;border-radius:8px;'
        f'padding:11px 0;font-size:13px;font-weight:600;cursor:not-allowed;opacity:0.5;'
        f'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;">🎙️ 합본 듣기</button>'
    )

    # 그리드 row 3: 정답 듣기 버튼들 — 5번째 컬럼은 비움 (행 1/2 와 정렬 유지 위해 grid template 은 동일)
    play_buttons_html = ""
    for slot_idx in range(1, n_pane_cols + 1):
        if slot_idx <= len(pane_infos) and pane_infos[slot_idx - 1]["ready"]:
            play_buttons_html += (
                f'<button id="play_btn_{slot_idx}_{uid}" data-slot="{slot_idx}" disabled '
                f'style="background:#BDC3C7;color:white;border:none;border-radius:8px;'
                f'padding:14px 0;font-size:18px;font-weight:700;cursor:not-allowed;opacity:0.5;'
                f'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;'
                f'transition:background 0.12s, opacity 0.12s;">{slot_idx}</button>'
            )
        else:
            play_buttons_html += (
                f'<button disabled '
                f'style="background:#D5D8DC;color:#7F8C8D;border:none;border-radius:8px;'
                f'padding:14px 0;font-size:18px;font-weight:700;cursor:not-allowed;opacity:0.6;'
                f'user-select:none;">{slot_idx}</button>'
            )
    # 5번째 컬럼은 비움 — 시각적으로 1, 2번 row 와 align 만 맞추기

    # 미매칭(ContentOwner 없음): 빨강 버튼 전부 잠긴 이유를 아주 작게 안내
    unmatched_notice_html = ""
    if not matched_owner:
        unmatched_notice_html = (
            '<div style="font-size:10px;color:#AEB4BC;text-align:center;'
            'line-height:1.3;margin-bottom:4px;user-select:none;">'
            '아직 그림 주인 매칭 전이라 잠겨 있어요</div>'
        )

    html = f"""
    <div style="font-family:-apple-system,system-ui,'Noto Sans KR',sans-serif;margin:0;position:relative;">
      {audio_tags}
      <!-- 녹음 중 오버레이 배너 — 손가락이 버튼 가려도 보이도록 그리드 위에 띄움 -->
      <div id="rec_banner_{uid}"
           style="display:none;position:absolute;top:0;left:0;right:0;bottom:0;
                  background:rgba(231,76,60,0.95);color:white;border-radius:8px;
                  z-index:10;flex-direction:column;align-items:center;justify-content:center;
                  text-align:center;animation:recpulse_{uid} 1.1s ease-in-out infinite;
                  pointer-events:none;">
        <div style="font-size:17px;font-weight:600;line-height:1.2;">
          ⏺ 녹음 중 · 슬롯 <span id="banner_slot_{uid}">-</span>
        </div>
        <div id="banner_timer_{uid}"
             style="font-size:38px;font-weight:700;margin:6px 0;
                    font-variant-numeric:tabular-nums;line-height:1;">0:00</div>
        <div style="font-size:13px;opacity:0.92;font-weight:400;">손가락 떼면 정지</div>
      </div>
      <style>
        @keyframes recpulse_{uid} {{
          0%, 100% {{ box-shadow: inset 0 0 0 0 rgba(255,255,255,0.0); opacity:1; }}
          50%      {{ box-shadow: inset 0 0 0 8px rgba(255,255,255,0.15); opacity:0.95; }}
        }}
      </style>
      {unmatched_notice_html}
      <div style="display:grid;grid-template-columns:repeat({n_total_cols},1fr);gap:5px;margin-bottom:5px;">
        {rec_buttons_html}
      </div>
      <div style="display:grid;grid-template-columns:repeat({n_total_cols},1fr);gap:5px;margin-bottom:5px;">
        {play_mine_buttons_html}
      </div>
      <div style="display:grid;grid-template-columns:repeat({n_total_cols},1fr);gap:5px;">
        {play_buttons_html}
      </div>
      <script>
      (function(){{
        var PANES = {panes_json};
        var UID = '{uid}';
        var recordings = {{}};   // {{slot: BlobURL}}
        var mediaRecorder = null;
        var micStream = null;
        var currentRecSlot = null;
        var isRecording = false;
        var recTimer = null;
        var mineAudioUnlocked = {{}};  // {{slot: true}} — Safari unlock 완료된 슬롯

        // 짧은 무음 WAV — Safari 의 mine audio element 첫 unlock 용 (user gesture 안에서 play 가능하도록)
        function _makeSilentUrl(){{
          var sr=8000, samples=80, ds=samples*2;
          var b = new ArrayBuffer(44+ds);
          var dv = new DataView(b);
          function w(o,s){{ for (var i=0;i<s.length;i++) dv.setUint8(o+i, s.charCodeAt(i)); }}
          w(0,'RIFF'); dv.setUint32(4, 36+ds, true);
          w(8,'WAVE'); w(12,'fmt ');
          dv.setUint32(16,16,true); dv.setUint16(20,1,true); dv.setUint16(22,1,true);
          dv.setUint32(24,sr,true); dv.setUint32(28,sr*2,true);
          dv.setUint16(32,2,true); dv.setUint16(34,16,true);
          w(36,'data'); dv.setUint32(40, ds, true);
          return URL.createObjectURL(new Blob([b], {{type:'audio/wav'}}));
        }}
        var SILENT_URL = _makeSilentUrl();

        function primeMineAudio(slot){{
          // user gesture 안에서 호출되어야 함. Safari 에서 해당 mine element 를 unlock.
          if (mineAudioUnlocked[slot]) return;
          var a = $('aud_mine_' + slot + '_' + UID);
          if (!a) return;
          try {{
            a.src = SILENT_URL;
            a.muted = true;
            var pr = a.play();
            if (pr && pr.then) {{
              pr.then(function(){{
                a.pause();
                a.muted = false;
                mineAudioUnlocked[slot] = true;
              }}).catch(function(){{
                a.muted = false;
              }});
            }} else {{
              a.pause();
              a.muted = false;
              mineAudioUnlocked[slot] = true;
            }}
          }} catch(e) {{ a.muted = false; }}
        }}
        var recStart = 0;
        var activeAudio = null;
        var playQueue = [];

        function $(id) {{ return document.getElementById(id); }}

        // 녹음 버튼 라벨 복원 / 변경
        function resetRecButtonVisual(slot) {{
          var btn = $('rec_btn_' + slot + '_' + UID);
          if (!btn) return;
          btn.style.background = '#E74C3C';
          btn.innerHTML = slot;
        }}
        function recordingVisual(slot) {{
          var btn = $('rec_btn_' + slot + '_' + UID);
          if (!btn) return;
          btn.style.background = '#922B21';
          btn.innerHTML = '<div style="font-size:10px;font-weight:400;opacity:0.85;">⏺ <span class="rec-timer">0:00</span></div><div style="font-size:13px;font-weight:700;">정지</div>';
        }}

        // 파랑(정답) 버튼 lock/unlock
        function unlockPlay(slot) {{
          var btn = $('play_btn_' + slot + '_' + UID);
          if (!btn) return;
          btn.disabled = false;
          btn.style.background = '#2980B9';
          btn.style.opacity = '1';
          btn.style.cursor = 'pointer';
        }}
        function lockPlay(slot) {{
          var btn = $('play_btn_' + slot + '_' + UID);
          if (!btn) return;
          btn.disabled = true;
          btn.style.background = '#BDC3C7';
          btn.style.opacity = '0.5';
          btn.style.cursor = 'not-allowed';
        }}
        // 🔈 (내 녹음) 버튼 lock/unlock — 색은 위 row 의 녹음 버튼과 동일한 빨강
        function unlockPlayMine(slot) {{
          var btn = $('play_mine_' + slot + '_' + UID);
          if (!btn) return;
          btn.disabled = false;
          btn.style.background = '#E74C3C';
          btn.style.opacity = '1';
          btn.style.cursor = 'pointer';
        }}
        function lockPlayMine(slot) {{
          var btn = $('play_mine_' + slot + '_' + UID);
          if (!btn) return;
          btn.disabled = true;
          btn.style.background = '#BDC3C7';
          btn.style.opacity = '0.5';
          btn.style.cursor = 'not-allowed';
        }}

        // 합본 듣기 활성 — 활성 슬롯 모두 녹음되어야만 unlock
        function updatePlayAll() {{
          var btn = $('play_all_' + UID);
          if (!btn) return;
          var activeCount = PANES.filter(function(p){{ return p.ready; }}).length;
          var recordedCount = Object.keys(recordings).length;
          var allDone = activeCount > 0 && recordedCount >= activeCount;
          btn.disabled = !allDone;
          btn.style.background = allDone ? '#E67E22' : '#BDC3C7';  // 주황 = 내 녹음 테마
          btn.style.opacity = allDone ? '1' : '0.5';
          btn.style.cursor = allDone ? 'pointer' : 'not-allowed';
        }}

        // 재생 시퀀스
        function stopAllPlayback() {{
          if (activeAudio) {{
            try {{ activeAudio.pause(); activeAudio.currentTime = 0; }} catch(e){{}}
            activeAudio = null;
          }}
          playQueue = [];
          clearHighlight();
        }}
        function highlightSlot(slot, kind) {{
          clearHighlight();
          var id = (kind === 'mine' ? 'rec_btn_' : 'play_btn_') + slot + '_' + UID;
          var b = $(id);
          if (b) b.style.boxShadow = '0 0 0 3px #FFE082';
        }}
        function clearHighlight() {{
          document.querySelectorAll('button').forEach(function(b){{
            if (b.style.boxShadow && b.style.boxShadow.indexOf('FFE082') >= 0) {{
              b.style.boxShadow = '';
            }}
          }});
        }}
        function playNext() {{
          if (activeAudio) {{
            try {{ activeAudio.pause(); activeAudio.currentTime = 0; }} catch(e){{}}
            activeAudio = null;
          }}
          if (playQueue.length === 0) {{ clearHighlight(); return; }}
          var item = playQueue.shift();
          var elemId = (item.kind === 'mine' ? 'aud_mine_' : 'aud_answer_') + item.slot + '_' + UID;
          var a = $(elemId);
          if (!a || !a.src) {{ playNext(); return; }}
          activeAudio = a;
          highlightSlot(item.slot, item.kind);
          a.currentTime = 0;
          var p = a.play();
          if (p && p.catch) p.catch(function(err){{ console.error('play err', err); playNext(); }});
        }}

        // 모든 audio ended 리스너
        PANES.forEach(function(p){{
          var m = $('aud_mine_' + p.slot + '_' + UID);
          if (m) m.addEventListener('ended', playNext);
          var a = $('aud_answer_' + p.slot + '_' + UID);
          if (a) a.addEventListener('ended', playNext);
        }});

        // 녹음 동작
        function startRecording(slot) {{
          stopAllPlayback();
          if (isRecording) {{
            stopRecording();
            // 같은 칸 다시 누른 케이스: 일단 중단만 하고 종료
            if (currentRecSlot === slot) return;
          }}
          navigator.mediaDevices.getUserMedia({{audio:true}}).then(function(stream){{
            // mic 준비되기 전에 user 가 이미 손 뗐으면 즉시 중단
            if (wantToStop) {{
              wantToStop = false;
              stream.getTracks().forEach(function(t){{ t.stop(); }});
              isRecording = false;
              currentRecSlot = null;
              hideRecBanner();
              return;
            }}
            micStream = stream;
            mediaRecorder = new MediaRecorder(stream);
            var chunks = [];
            mediaRecorder.ondataavailable = function(e){{ if (e.data.size > 0) chunks.push(e.data); }};
            mediaRecorder.onstop = function(){{
              var blob = new Blob(chunks, {{type: mediaRecorder.mimeType || 'audio/webm'}});
              if (recordings[slot]) URL.revokeObjectURL(recordings[slot]);
              var url = URL.createObjectURL(blob);
              recordings[slot] = url;
              var mineAudio = $('aud_mine_' + slot + '_' + UID);
              if (mineAudio) mineAudio.src = url;
              if (micStream) {{
                micStream.getTracks().forEach(function(t){{ t.stop(); }});
                micStream = null;
              }}
              isRecording = false;
              resetRecButtonVisual(slot);
              if (recTimer) {{ clearInterval(recTimer); recTimer = null; }}

              unlockPlay(slot);
              unlockPlayMine(slot);   // 🔈 버튼도 같이 활성화
              updatePlayAll();
              currentRecSlot = null;
              // 손가락 떼서 종료된 경우: 내 녹음 자동 재생 (정답은 재생 X — 파란 버튼에서)
              // 250ms 기다림 — mine blob 디코드 시간 확보
              if (autoPlayAfterStop) {{
                autoPlayAfterStop = false;
                setTimeout(function(){{
                  stopAllPlayback();
                  playQueue = [{{kind:'mine', slot: slot}}];
                  playNext();
                }}, 250);
              }}
            }};
            mediaRecorder.start();
            isRecording = true;
            currentRecSlot = slot;
            recStart = Date.now();
            recordingVisual(slot);
            recTimer = setInterval(function(){{
              var elapsed = Math.floor((Date.now() - recStart) / 1000);
              var mm = Math.floor(elapsed / 60);
              var ss = elapsed % 60;
              var timeStr = mm + ':' + (ss < 10 ? '0' + ss : ss);
              // 버튼 안 작은 타이머
              var el = document.querySelector('#rec_btn_' + slot + '_' + UID + ' .rec-timer');
              if (el) el.textContent = timeStr;
              // 배너 큰 타이머
              var bt = $('banner_timer_' + UID);
              if (bt) bt.textContent = timeStr;
            }}, 250);
          }}).catch(function(err){{
            console.error('mic err', err);
            alert('마이크 권한이 필요합니다.');
          }});
        }}
        function stopRecording() {{
          if (mediaRecorder && mediaRecorder.state === 'recording') {{
            mediaRecorder.stop();
          }}
        }}

        // 빨간 버튼 — 누르자마자 즉시 녹음 시작, 떼면 정지 + 자동 재생
        //   임계 시간 0. 모든 누름은 녹음.
        //   짧은 release 의 케이스: getUserMedia 가 아직 안 끝났으면 wantToStop 플래그로 처리.
        var pressedSlot = null;
        var wantToStop = false;
        var autoPlayAfterStop = false;

        function showRecBanner(slot){{
          var b = $('rec_banner_' + UID);
          var s = $('banner_slot_' + UID);
          var t = $('banner_timer_' + UID);
          if (b) b.style.display = 'flex';
          if (s) s.textContent = slot;
          if (t) t.textContent = '0:00';
        }}
        function hideRecBanner(){{
          var b = $('rec_banner_' + UID);
          if (b) b.style.display = 'none';
        }}

        function onPressStart(slot, e){{
          if (e && e.cancelable) e.preventDefault();
          if (isRecording) return;  // 이미 녹음 중이면 무시
          pressedSlot = slot;
          wantToStop = false;
          // Safari 대응: user gesture 안에서 mine audio element 를 silent 로 unlock
          primeMineAudio(slot);
          showRecBanner(slot);     // 즉시 시각 피드백 (배너)
          startRecording(slot);    // 임계 없이 바로 시작
        }}

        function onPressEnd(slot, e){{
          if (e && e.cancelable) e.preventDefault();
          pressedSlot = null;
          if (isRecording && currentRecSlot === slot) {{
            autoPlayAfterStop = true;
            stopRecording();
            hideRecBanner();
          }} else {{
            // mic 가 아직 준비 중일 때 release — 시작되면 즉시 중단되도록 플래그
            wantToStop = true;
            hideRecBanner();
          }}
        }}

        PANES.forEach(function(p){{
          if (!p.ready) return;
          var btn = $('rec_btn_' + p.slot + '_' + UID);
          if (!btn) return;
          btn.addEventListener('mousedown', function(e){{ onPressStart(p.slot, e); }});
          btn.addEventListener('mouseup', function(e){{ onPressEnd(p.slot, e); }});
          btn.addEventListener('mouseleave', function(e){{
            if (pressedSlot === p.slot || (isRecording && currentRecSlot === p.slot)) {{
              onPressEnd(p.slot, e);
            }}
          }});
          btn.addEventListener('touchstart', function(e){{ onPressStart(p.slot, e); }}, {{passive:false}});
          btn.addEventListener('touchend', function(e){{ onPressEnd(p.slot, e); }}, {{passive:false}});
          btn.addEventListener('touchcancel', function(e){{ onPressEnd(p.slot, e); }}, {{passive:false}});
          btn.addEventListener('contextmenu', function(e){{ e.preventDefault(); }});
        }});

        // 파란 버튼 클릭: 정답 mp3 만 재생 (내 녹음 X)
        PANES.forEach(function(p){{
          var btn = $('play_btn_' + p.slot + '_' + UID);
          if (!btn) return;
          btn.addEventListener('click', function(){{
            if (btn.disabled) return;
            stopAllPlayback();
            playQueue = [{{kind:'answer', slot:p.slot}}];
            playNext();
          }});
        }});

        // 🔈 내 녹음 듣기 버튼 — 해당 슬롯의 내 녹음 재생
        PANES.forEach(function(p){{
          var btn = $('play_mine_' + p.slot + '_' + UID);
          if (!btn) return;
          btn.addEventListener('click', function(){{
            if (btn.disabled) return;
            stopAllPlayback();
            playQueue = [{{kind:'mine', slot: p.slot}}];
            playNext();
          }});
        }});

        // 합본 듣기 — 자기 녹음 1→2→…→N 순차 재생 (베스트 합본)
        var allBtn = $('play_all_' + UID);
        if (allBtn) {{
          allBtn.addEventListener('click', function(){{
            if (allBtn.disabled) return;
            stopAllPlayback();
            var recorded = PANES.filter(function(p){{ return p.ready && recordings[p.slot]; }});
            playQueue = [];
            recorded.forEach(function(p){{ playQueue.push({{kind:'mine', slot:p.slot}}); }});
            playNext();
          }});
        }}

        // 다시 (모든 녹음 초기화)
        var resetBtn = $('reset_btn_' + UID);
        if (resetBtn) {{
          resetBtn.addEventListener('click', function(){{
            stopAllPlayback();
            if (isRecording) stopRecording();
            Object.keys(recordings).forEach(function(slot){{
              try {{ URL.revokeObjectURL(recordings[slot]); }} catch(e){{}}
              delete recordings[slot];
              var mineAudio = $('aud_mine_' + slot + '_' + UID);
              if (mineAudio) mineAudio.src = '';
              lockPlay(slot);
              lockPlayMine(slot);  // 🔈 버튼도 잠금 복귀
            }});
            updatePlayAll();
          }});
        }}

        // 페이지 이탈 시 모든 리소스 정리
        window.addEventListener('beforeunload', function(){{
          Object.values(recordings).forEach(function(url){{
            try {{ URL.revokeObjectURL(url); }} catch(e){{}}
          }});
          if (micStream) micStream.getTracks().forEach(function(t){{ t.stop(); }});
        }});
      }})();
      </script>
    </div>
    """
    components.html(html, height=160, scrolling=False)


def render_match_picker(image_path, image_student, chapter, all_students, image_matchings, client, key_suffix=""):
    """매칭 안 된 그림에 대해 학생 선택 드롭다운을 표시. (이미지 위쪽 위젯)
    매칭이 이미 되어있으면 아무것도 표시하지 않음."""
    image_filename = match_image_key(os.path.basename(image_path))
    key = (image_student, str(chapter), image_filename)
    if key in image_matchings:
        return  # 매칭 완료 → 위쪽엔 표시 안 함

    st.markdown(
        '<div style="background:#FFF3E0;border:1px solid #FFB74D;border-radius:8px;'
        'padding:12px 14px;margin-bottom:10px;">'
        '<div style="font-size:15px;font-weight:600;color:#E65100;margin-bottom:8px;">'
        '누구의 내용인지 알려주세요!</div></div>',
        unsafe_allow_html=True
    )
    sel_key = f"matchpick_{image_student}_{chapter}_{image_filename}_{key_suffix}"
    sel = st.selectbox(
        "이 그림은 누구의 내용인가요?",
        [""] + sorted(all_students),
        key=sel_key,
        label_visibility="collapsed",
    )
    if sel:
        ok = save_image_matching(client, image_student, str(chapter), image_filename, sel)
        if ok:
            # 세션 캐시 즉시 갱신 (rerun 후 새 매칭이 보이게)
            st.session_state.setdefault('image_matchings', {})
            st.session_state['image_matchings'][(image_student, str(chapter), image_filename)] = sel
            try_rename_image_on_github(image_path, sel)  # GitHub 파일명에 주인 표기(비차단)
            st.toast(f"✅ '{sel}' 으로 매칭 저장됨")
            st.rerun()
        else:
            st.error("매칭 저장 실패 — 잠시 후 다시 시도해 주세요.")


def render_image_answer_widget(image_path, image_student, chapter, all_students, sentence_bank, chapter_mapping, image_matchings, client, key_suffix="", match_only=False):
    """이미지 아래에 표시되는 위젯 (SentenceBank · pane 단위).
    매칭됨 + 음원 있음                → 🔊 정답 듣기
    매칭됨 + 정답 있음 + 음원 없음   → 🕐 음원 생성 대기 중
    매칭됨 + 정답 자체 없음           → ⚠️ 정답 미입력
    매칭 안됨                          → 표시 안 함 (위쪽 picker 가 처리)

    match_only=True 인 경우 — 오디오/메시지 영역 생략하고 매칭 수정 UI만 노출.
      (playing 모드에서 render_section_audio_grid 가 이미 오디오를 처리하므로 중복 방지)
    """
    image_filename = match_image_key(os.path.basename(image_path))
    chapter_str = str(chapter)
    key = (image_student, chapter_str, image_filename)
    content_owner = image_matchings.get(key)

    if not content_owner:
        return  # 매칭 안됨 → picker 가 위에서 처리

    # 이미지 파일명 → 그림칸(pane) 번호 변환 (챕터 매핑 활용)
    pane = image_to_pane(image_filename, chapter_str, chapter_mapping)
    sentence = ""
    audio_abs = None
    if pane is not None:
        sentence = sentence_bank.get((chapter_str, str(pane), content_owner), "")
        audio_abs = get_audio_path_pane(chapter_str, pane, content_owner)
    audio_exists = bool(audio_abs and os.path.exists(audio_abs))
    has_sentences = bool(sentence and sentence.strip())

    if not match_only:
        if audio_exists:
            render_audio_player(audio_abs)
        elif has_sentences:
            # 정답은 있는데 음원만 아직 안 만든 상태 (다음 TTS 트리거에서 만들어짐)
            st.markdown(
                '<div style="margin:0;color:#7B6F00;background:#FFF8E1;font-size:14px;'
                'padding:12px 14px;border:1px solid #F0D070;border-radius:6px;'
                'text-align:center;font-family:-apple-system,system-ui,sans-serif;">'
                '🕐 음원 생성 대기 중</div>',
                unsafe_allow_html=True
            )
        else:
            # 정답 자체가 등록 안 됨
            st.markdown(
                '<div style="margin:0;color:#999;background:#fafafa;font-size:14px;'
                'padding:12px 14px;border:1px dashed #ddd;border-radius:6px;'
                'text-align:center;font-family:-apple-system,system-ui,sans-serif;">'
                '⚠️ 정답 미입력</div>',
                unsafe_allow_html=True
            )

    # 매칭 수정 UI
    edit_key = f"edit_match_{image_student}_{chapter_str}_{image_filename}_{key_suffix}"
    if st.session_state.get(edit_key):
        st.markdown(
            f"<div style='font-size:13px;color:#666;margin-top:8px;margin-bottom:4px;'>매칭 수정 (현재: <b>{content_owner}</b>)</div>",
            unsafe_allow_html=True
        )
        current_idx = 0
        students_sorted = sorted(all_students)
        if content_owner in students_sorted:
            current_idx = students_sorted.index(content_owner) + 1
        new_sel = st.selectbox(
            "올바른 학생 선택",
            [""] + students_sorted,
            index=current_idx,
            key=f"{edit_key}_select",
            label_visibility="collapsed",
        )
        cc1, cc2 = st.columns([1, 1])
        with cc1:
            if st.button("적용", key=f"{edit_key}_apply", use_container_width=True):
                if new_sel and new_sel != content_owner:
                    if save_image_matching(client, image_student, chapter_str, image_filename, new_sel):
                        # 세션 캐시 즉시 갱신
                        st.session_state.setdefault('image_matchings', {})
                        st.session_state['image_matchings'][(image_student, chapter_str, image_filename)] = new_sel
                        try_rename_image_on_github(image_path, new_sel)  # GitHub 파일명 갱신(비차단)
                        st.toast(f"매칭이 '{new_sel}' 으로 수정됨")
                        st.session_state.pop(edit_key, None)
                        st.rerun()
                else:
                    st.session_state.pop(edit_key, None)
                    st.rerun()
        with cc2:
            if st.button("취소", key=f"{edit_key}_cancel", use_container_width=True):
                st.session_state.pop(edit_key, None)
                st.rerun()
    else:
        st.markdown(
            f"<div style='margin-top:6px;'></div>",
            unsafe_allow_html=True
        )
        if st.button(f"그림 매칭 수정 (현재: {content_owner})", key=f"toggle_{edit_key}",
                     use_container_width=True, type="secondary"):
            st.session_state[edit_key] = True
            st.rerun()


def get_all_student_names():
    """모든 폴더의 학생 이름 목록 (중복 제거)."""
    names = set()
    for folder_name in TARGET_FOLDERS:
        target_path = os.path.join(BASE_FOLDER, folder_name)
        if os.path.exists(target_path):
            try:
                for d in os.listdir(target_path):
                    full = os.path.join(target_path, d)
                    if os.path.isdir(full) and not d.startswith('.'):
                        names.add(d)
            except Exception:
                continue
    return sorted(names)


@st.cache_data(ttl=300, show_spinner=False)
def get_students_with_chapter_folder(chapter):
    """특정 챕터(예: '602') 폴더가 현행/지난/보류/보관 하위에 있는 학생 이름 목록.
    페어 챕터 처리: '602' 검색 시 '602S' 폴더 가진 학생도 포함 (그 반대도 동일).
    602와 602S는 자매 코스로 묶여있어 매칭 후보로 동일하게 취급.
    보류·보관 폴더에 챕터가 있는 학생도 매칭 후보로 포함 (수업 잠시 쉬는 중인 학생의 그림도 매칭됨)."""
    chapter = str(chapter)

    # 페어 챕터 자동 확장
    chapters_to_check = {chapter}
    if chapter.endswith('S'):
        chapters_to_check.add(chapter[:-1])
    else:
        chapters_to_check.add(chapter + 'S')

    students = set()
    for folder_name in TARGET_FOLDERS:
        target_path = os.path.join(BASE_FOLDER, folder_name)
        if not os.path.exists(target_path):
            continue
        try:
            for student_d in os.listdir(target_path):
                if student_d.startswith('.'):
                    continue
                for sub in MATCHING_SUBFOLDERS:
                    sub_path = os.path.join(target_path, student_d, sub)
                    if not os.path.exists(sub_path):
                        continue
                    for ch in chapters_to_check:
                        if os.path.exists(os.path.join(sub_path, ch)):
                            students.add(student_d)
                            break
                    if student_d in students:
                        break
        except Exception:
            continue
    return sorted(students)


def get_attendance(client, student_name, year, month):
    df = get_data_from_sheet(client)
    if df.empty: return set()
    att_df = df[(df['Student'] == student_name) & (df['Chapter'] == 'Attendance') & (df['Result'] == 'DONE')]
    if att_df.empty: return set()
    
    attended_days = set()
    for ts in att_df['Timestamp']:
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            if dt.year == year and dt.month == month:
                attended_days.add(dt.day)
        except: pass
    return attended_days

def get_random_question(client, student_name):
    try:
        sheet_questions = client.open(SHEET_NAME).worksheet("Questions")
        all_qs = [v for v in sheet_questions.col_values(1) if v.strip()]
        if not all_qs: return None

        sheet_asked = client.open(SHEET_NAME).worksheet("Asked_Questions")
        all_rows = sheet_asked.get_all_values()
        
        if not all_rows:
            sheet_asked.append_row(["Timestamp", "Student", "Question"])
            asked_qs = []
        else:
            asked_qs = [row[2] for row in all_rows[1:] if len(row) >= 3 and row[1] == student_name]
            
        available_qs = [q for q in all_qs if q not in asked_qs]
        if not available_qs: available_qs = all_qs 
            
        selected_q = random.choice(available_qs)
        timestamp = get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
        sheet_asked.append_row([timestamp, student_name, selected_q])
        
        return selected_q
    except Exception as e:
        try:
            sheet_q = client.open(SHEET_NAME).worksheet("Questions")
            vals = [v for v in sheet_q.col_values(1) if v.strip()]
            return random.choice(vals) if vals else None
        except:
            return None

@st.cache_data(show_spinner=False)
def get_image_base64(image_path):
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

def display_responsive_image(image_path, is_grid=False):
    try:
        abs_path = os.path.abspath(image_path)
        img = Image.open(abs_path)
        w, h = img.size
        actual_ratio = w / h
        target_ratio = (3 * 2.69) / 2.45
        width_pct = min(100, (actual_ratio / target_ratio) * 100)
        img_b64 = get_image_base64(abs_path)
        
        min_h = "200px" if is_grid else "50vh"
        max_h = "100%" if is_grid else "80vh"

        html_code = f"""
        <div style="display: flex; justify-content: center; align-items: center; width: 100%; min-height: {min_h};">
            <img src="data:image/png;base64,{img_b64}" 
                 style="width: {width_pct}%; max-width: 100%; max-height: {max_h}; height: auto; border-radius: 5px;">
        </div>
        """
        st.markdown(html_code, unsafe_allow_html=True)
    except Exception as e:
        st.image(image_path, use_container_width=True)

# ==========================================
# [로직] 탐색 및 통계
# ==========================================
def get_all_students():
    student_list = []
    for folder_name in TARGET_FOLDERS:
        target_path = os.path.join(BASE_FOLDER, folder_name)
        if os.path.exists(target_path):
            try:
                students = [d for d in os.listdir(target_path) if os.path.isdir(os.path.join(target_path, d)) and not d.startswith('.')]
                for s in students: student_list.append((folder_name, s))
            except: continue
    student_list.sort(key=lambda x: x[1])
    return student_list

def get_chapters(folder_name, student_name):
    student_path = os.path.join(BASE_FOLDER, folder_name, student_name)
    chapters = []
    if not os.path.exists(student_path): return []
    for sub in ALLOWED_SUBFOLDERS:
        sub_path = os.path.join(student_path, sub)
        if os.path.exists(sub_path):
            try:
                subs = [d for d in os.listdir(sub_path) if os.path.isdir(os.path.join(sub_path, d)) and not d.startswith('.')]
                for ch in subs: chapters.append((os.path.join(sub, ch), ch))
            except: continue
    chapters.sort(key=lambda x: x[1])
    return chapters

def get_images(folder_name, student_name, chapter_rel_path):
    full_path = os.path.join(BASE_FOLDER, folder_name, student_name, chapter_rel_path)
    images = []
    try:
        for f in os.listdir(full_path):
            if f.lower().endswith(('.png', '.jpg', '.jpeg')): images.append(os.path.join(full_path, f))
    except: pass
    return sorted(images)

def calculate_batting_average(df, student, image_path):
    if df.empty: return 0.0, []
    img_name = os.path.basename(image_path)
    target_df = df[(df['Student'] == student) & (df['Image'] == img_name)]
    if target_df.empty: return 0.0, []
    recent_records = target_df.tail(5)['Result'].tolist()
    return recent_records.count('O') / len(recent_records), recent_records

def get_daily_target_images(folder_name, student_name, subfolder, n, db_df):
    target_path = os.path.join(BASE_FOLDER, folder_name, student_name, subfolder)
    if not os.path.exists(target_path): return []

    all_imgs = []
    for root, _, files in os.walk(target_path):
        root_nfc = unicodedata.normalize('NFC', root)
        if "보류" in root_nfc: continue
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                all_imgs.append(os.path.join(root, f))

    if not all_imgs: return []

    counts = {}
    batting_avgs = {}
    if not db_df.empty:
        student_data = db_df[db_df['Student'] == student_name]
        counts = student_data['Image'].value_counts().to_dict()
        # 이미지별 최근 5회 타율 계산
        for img_path in all_imgs:
            img_name = os.path.basename(img_path)
            img_results = student_data[student_data['Image'] == img_name]['Result'].tail(5).tolist()
            if img_results:
                batting_avgs[img_name] = img_results.count('O') / len(img_results)

    max_count = max(counts.values()) if counts else 1

    def priority_score(img_path):
        img_name = os.path.basename(img_path)
        count = counts.get(img_name, 0)

        # 5회 미만 출제 → 타율 계산 신뢰도 없음 → 데이터 수집 우선 구간
        # 점수: 0회=-1.0, 1회=-0.9, 2회=-0.8, 3회=-0.7, 4회=-0.6 → 무조건 상위권
        if count < 5:
            return -1 + (count * 0.1)

        # 5회 이상 → 타율 유효 → 정상 가중치 적용
        avg = batting_avgs.get(img_name, 0.5)
        norm_count = count / max_count                  # 0.0 ~ 1.0 정규화
        return avg * 0.7 + norm_count * 0.3             # 타율 70%, 출제횟수 30% 가중치

    random.shuffle(all_imgs)                            # 동점 처리용 사전 셔플
    all_imgs.sort(key=priority_score)                   # 점수 낮을수록(약점+미출제) 우선
    return all_imgs[:n]

# ==========================================
# [로직] 결과 인증 이미지 생성
# ==========================================
def get_label_bg_rgba(label_text: str):
    if label_text.startswith('1'): return (214, 82, 75, 180) 
    if label_text.endswith('S'): return (199, 142, 43, 180) 
    return (62, 129, 97, 180) 

def create_summary_image_base64(student_name, results_list, db_df, question_text, current_year, current_month, attended_days):
    """인증 이미지 — 단일 컬럼 양식.
    - 헤더 (제목)
    - 달력 (전폭, 출석 표시)
    - 구간별 이미지 1열 × N행 (각 행 = 한 구간의 스토리보드)
    - (있다면) Open-ended Question 전폭
    """
    TOTAL_WIDTH = 1140
    HEADER_HEIGHT = 90
    SIDE_PAD = 30  # 좌우 여백

    try:
        font_title = ImageFont.truetype(FONT_PATH, 48)
        font_cal = ImageFont.truetype(FONT_PATH, 24)
        font_q = ImageFont.truetype(FONT_PATH, 42)
        font_info = ImageFont.truetype(FONT_PATH, 24)
    except:
        font_title = font_cal = font_q = font_info = ImageFont.load_default()

    # 이미지 영역: 가로 전폭 활용
    max_img_w = TOTAL_WIDTH - 2 * SIDE_PAD  # 1080
    TARGET_HEIGHT = 240          # 전폭으로 늘어났으니 비율 맞춰 키움 (옛 120 의 2배)
    CELL_HEADER_H = 30           # 배지 + O/X 행 높이
    CELL_H = TARGET_HEIGHT + CELL_HEADER_H

    # 이미지 데이터 준비 — 각 결과에 대해 한 행
    row_data = []
    for r in results_list:
        p = r['file']
        res = r['result']
        try:
            img = Image.open(p).convert("RGBA")
            scale = TARGET_HEIGHT / img.size[1]
            new_w = int(img.size[0] * scale)
            if new_w > max_img_w:
                # 너무 넓으면 가로 cap
                img = img.resize((max_img_w, TARGET_HEIGHT), resample=Image.LANCZOS)
            else:
                img = img.resize((new_w, TARGET_HEIGHT), resample=Image.LANCZOS)
            bg = Image.new("RGB", img.size, "WHITE")
            bg.paste(img, (0, 0), img)
            if res == 'X':
                bg = bg.convert("L").convert("RGB")
            label = os.path.basename(os.path.dirname(p))
            _, hist = calculate_batting_average(db_df, student_name, p)
            hist.append(res)
            hist = hist[-5:]
            row_data.append({'img': bg, 'label': label, 'hist': hist})
        except:
            continue

    # 달력 — 전폭으로 확장
    calendar.setfirstweekday(calendar.SUNDAY)
    cal_matrix = calendar.monthcalendar(current_year, current_month)
    cal_row_height = 45
    CALENDAR_HEIGHT = cal_row_height + (len(cal_matrix) * cal_row_height) + 15

    GRID_HEIGHT = len(row_data) * CELL_H

    q_lines = []
    q_height = 0
    if question_text:
        wrapped = textwrap.fill(question_text, width=60)
        q_lines = wrapped.split('\n')
        q_height = len(q_lines) * 60 + 50

    TOTAL_HEIGHT = HEADER_HEIGHT + CALENDAR_HEIGHT + GRID_HEIGHT + q_height

    final_image = Image.new("RGB", (TOTAL_WIDTH, TOTAL_HEIGHT), "white")
    draw = ImageDraw.Draw(final_image)

    # [헤더]
    today = get_kst_now()
    today_display = today.strftime('%m/%d').lstrip("0").replace("/0", "/")
    title_text = f"{student_name} {today_display} 숙제 완료 ✔"
    draw.text((SIDE_PAD, 22), title_text, fill="black", font=font_title)

    # [달력 — 전폭]
    cal_start_y = HEADER_HEIGHT
    days_header = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
    cal_width = TOTAL_WIDTH - 2 * SIDE_PAD  # 1080
    col_spacing = cal_width / 7.0

    for i, day_str in enumerate(days_header):
        tw = draw.textlength(day_str, font=font_cal)
        dx = SIDE_PAD + i * col_spacing + (col_spacing - tw) / 2
        draw.text((dx, cal_start_y), day_str, fill="#95A5A6", font=font_cal)

    cal_y = cal_start_y + cal_row_height
    for week in cal_matrix:
        for i, day in enumerate(week):
            if day != 0:
                dx = SIDE_PAD + i * col_spacing
                dy = cal_y
                day_str = str(day)
                tw = draw.textlength(day_str, font=font_cal)
                txt_x = dx + (col_spacing - tw) / 2
                txt_y = dy + 7
                is_today = (day == today.day and current_month == today.month and current_year == today.year)
                if day in attended_days:
                    bg_color = "#E74C3C" if is_today else "#95A5A6"
                    draw.rectangle([dx, dy, dx + col_spacing, dy + cal_row_height], fill=bg_color)
                    draw.text((txt_x, txt_y), day_str, fill="white", font=font_cal)
                else:
                    draw.text((txt_x, txt_y), day_str, fill="black", font=font_cal)
        cal_y += cal_row_height

    # [그리드 — 단일 컬럼, 각 행 = 한 구간 스토리보드]
    grid_y_start = HEADER_HEIGHT + CALENDAR_HEIGHT

    for i, item in enumerate(row_data):
        x_off = SIDE_PAD
        y_off = grid_y_start + i * CELL_H
        badge_text = str(item['label'])
        text_y_align = y_off - 2

        # 1) 배지 (챕터 번호)
        bg_rgba = get_label_bg_rgba(badge_text)
        bw = draw.textlength(badge_text, font=font_info) + 16
        draw.rectangle([x_off, y_off, x_off + bw, y_off + CELL_HEADER_H], fill=bg_rgba)
        draw.text((x_off + 8, text_y_align), badge_text, fill="white", font=font_info)

        # 2) O/X 히스토리
        hist_start_x = x_off + bw + 15
        hist_list = item['hist']
        current_x = hist_start_x
        for idx_h, char in enumerate(hist_list):
            is_last_item = (idx_h == len(hist_list) - 1)
            char_color = "#E74C3C" if (is_last_item and char == 'X') else "#95A5A6"
            draw.text((current_x, text_y_align), char, fill=char_color, font=font_info)
            current_x += draw.textlength(char, font=font_info) + 6

        # 3) 이미지 — 좌측 정렬 (배지·OX 와 시작점 동일)
        final_image.paste(item['img'], (x_off, y_off + CELL_HEADER_H))

    # [질문]
    y_offset = grid_y_start + GRID_HEIGHT
    if question_text:
        text_y = y_offset + 15
        for line in q_lines:
            draw.text((SIDE_PAD, text_y), line, fill="black", font=font_q)
            text_y += 60

    buffered = BytesIO()
    final_image.save(buffered, format="JPEG", quality=95)
    return base64.b64encode(buffered.getvalue()).decode()

# ==========================================
# [화면] 사이드바
# ==========================================
client = init_connection()

st.sidebar.markdown('<div class="sidebar-title">Syntax Pitching™</div>', unsafe_allow_html=True)

query_params = st.query_params
url_student = query_params.get("student")

all_students_info = get_all_students()
selected_data = None
if all_students_info:
    if url_student:
        match = [s for s in all_students_info if s[1] == url_student]
        if match:
            selected_data = match[0]
            st.sidebar.markdown(f'<div style="font-size: 20px; font-weight: 600; margin-bottom: 20px;">{url_student} 님</div>', unsafe_allow_html=True)
        else:
            st.sidebar.error(f"'{url_student}' 미등록")
            selected_data = st.sidebar.selectbox("수강생 선택", all_students_info, format_func=lambda x: x[1])
    else:
        selected_data = st.sidebar.selectbox("수강생 선택", all_students_info, format_func=lambda x: x[1])

    if selected_data:
        folder_name, student_name = selected_data
        chapter_list = get_chapters(folder_name, student_name)
        if chapter_list:
            selected_chapters = st.sidebar.multiselect("챕터 선택 (복수 선택 가능)", chapter_list, format_func=lambda x: x[1])

            # 타율 필터 드롭다운 (기본값: 전체 출제 = 필터 없음)
            batting_filter_options = {
                "전체 출제": None,
                "80% 이하": 0.8,
                "60% 이하": 0.6,
                "40% 이하": 0.4,
                "20% 이하": 0.2,
            }
            batting_filter_label = st.sidebar.selectbox(
                "타율 필터",
                list(batting_filter_options.keys()),
                index=0,
                help="선택한 타율 이하의 이미지만 출제됩니다. 타율은 최근 5회 기준이며, 5회 미만 출제된 이미지는 제외됩니다."
            )

            if st.sidebar.button("훈련 시작 (Start)", use_container_width=True) and selected_chapters:
                all_images = []
                for ch_path, ch_name in selected_chapters:
                    all_images.extend(get_images(folder_name, student_name, ch_path))

                # 타율 필터 적용
                db_df = get_data_from_sheet(client) if client else pd.DataFrame()
                threshold = batting_filter_options[batting_filter_label]
                if threshold is not None:
                    filtered = []
                    for img in all_images:
                        avg, records = calculate_batting_average(db_df, student_name, img)
                        if len(records) >= 5 and avg <= threshold:
                            filtered.append(img)
                    all_images = filtered

                if not all_images:
                    st.sidebar.warning("조건에 맞는 이미지가 없습니다.")
                else:
                    random.shuffle(all_images)
                    st.session_state.update({
                        'folder_name': folder_name, 'student_name': student_name, 'selected_chapters': selected_chapters,
                        'original_playlist': all_images.copy(), 'playlist': all_images, 'current_index': 0, 'results': [],
                        'is_practice_mode': False, 'mode': 'playing', 'is_daily': False
                    })
                    st.session_state['db_data'] = db_df
                    # 정답/매칭 캐시 새로고침 (훈련 세션 시작 시 항상 최신 데이터로)
                    st.session_state.pop('answers_map', None)
                    st.session_state.pop('answer_bank', None)        # 레거시
                    st.session_state.pop('sentence_bank', None)
                    st.session_state.pop('chapter_mapping', None)
                    st.session_state.pop('image_matchings', None)
                    st.rerun()

            if st.sidebar.button("피칭 기록 보기", use_container_width=True) and selected_chapters:
                st.session_state.update({'folder_name': folder_name, 'student_name': student_name, 'selected_chapters': selected_chapters, 'mode': 'records'})
                if client: st.session_state['db_data'] = get_data_from_sheet(client)
                st.rerun()


# ==========================================
# [화면] 메인 로직
# ==========================================
if 'mode' not in st.session_state: st.session_state['mode'] = 'setup'

# URL ?view=manual → 매뉴얼 페이지로 진입 (setup 상태에서만 자동 라우팅)
if query_params.get("view") == "manual" and st.session_state['mode'] == 'setup':
    st.session_state['mode'] = 'help'

if st.session_state['mode'] == 'setup':
    st.title("Welcome to Syntax Pitching™")
    if url_student and selected_data:
        st.markdown(f"### {url_student} 님, 환영합니다!")
        
        if st.button("오늘의 Daily Homework 시작"):
            if 'daily_summary_img' in st.session_state: del st.session_state['daily_summary_img']
            if 'daily_question' in st.session_state: del st.session_state['daily_question']
                
            if client: st.session_state['db_data'] = get_data_from_sheet(client)
            db_df = st.session_state.get('db_data', pd.DataFrame())
            
            curr_imgs = get_daily_target_images(folder_name, student_name, "현행 챕터", 2, db_df)
            curr_shortfall = 2 - len(curr_imgs)  # 현행 부족분 → 지난에서 보충

            past_target = 1 + curr_shortfall
            past_imgs = get_daily_target_images(folder_name, student_name, "지난 챕터", past_target, db_df)
            past_shortfall = past_target - len(past_imgs)  # 지난도 부족하면 → 현행에서 추가 보충

            if past_shortfall > 0:
                curr_imgs = get_daily_target_images(folder_name, student_name, "현행 챕터", 2 + past_shortfall, db_df)
            
            daily_playlist = curr_imgs + past_imgs
            random.shuffle(daily_playlist)
            
            if daily_playlist:
                st.session_state.update({
                    'folder_name': folder_name, 'student_name': student_name,
                    'original_playlist': daily_playlist.copy(), 'playlist': daily_playlist,
                    'current_index': 0, 'results': [], 'is_practice_mode': False,
                    'mode': 'daily_playing', 'is_daily': True
                })
                # 정답/매칭 캐시 새로고침
                st.session_state.pop('answers_map', None)
                st.session_state.pop('answer_bank', None)        # 레거시
                st.session_state.pop('sentence_bank', None)
                st.session_state.pop('chapter_mapping', None)
                st.session_state.pop('image_matchings', None)
                st.rerun()
            else:
                st.warning("출제할 이미지가 없습니다. 폴더 구성을 확인해 주세요.")
        
        st.write("")
        st.markdown("👈 특정 챕터만 골라서 연습하려면 왼쪽에서 챕터를 선택하세요.")
    else:
        st.markdown("### 👈 왼쪽 사이드바에서 수강생을 선택해주세요.")

    # 사용법 진입 — 인라인 텍스트 링크 (기존 안내 문구와 동일 양식)
    _existing_qs = "&".join(f"{k}={v}" for k, v in query_params.items() if k != "view")
    _manual_href = (f"?{_existing_qs}&view=manual") if _existing_qs else "?view=manual"
    st.markdown(
        f'<p style="margin-top:8px;"><a href="{_manual_href}" target="_self" '
        f'style="text-decoration:underline;color:inherit;">Syntax Pitching Manual</a></p>',
        unsafe_allow_html=True
    )

    st.markdown('<div class="footer-text">© Powered by Kusukban | All Rights Reserved.</div>', unsafe_allow_html=True)

elif st.session_state['mode'] in ['playing', 'daily_playing']:
    playlist = st.session_state['playlist']
    idx = st.session_state['current_index']
    is_practice = st.session_state.get('is_practice_mode', False)
    is_daily = st.session_state.get('is_daily', False)

    if is_practice: st.warning("현재 '틀린 구간 반복 모드'입니다. (기록되지 않음)")
    elif is_daily: st.info("오늘의 Daily Homework 진행 중")
    
    st.progress(idx / len(playlist) if len(playlist) > 0 else 0)
    st.caption(f"Progress: {idx + 1} / {len(playlist)}")

    if idx < len(playlist):
        current_img_path = playlist[idx]
        current_chapter = os.path.basename(os.path.dirname(current_img_path))

        # 정답 데이터 로드 (세션 캐시) — SentenceBank (pane 단위) + 챕터 매핑
        if 'sentence_bank' not in st.session_state:
            st.session_state['sentence_bank'] = load_sentence_bank(client) if client else {}
        if 'chapter_mapping' not in st.session_state:
            st.session_state['chapter_mapping'] = load_chapter_mapping(client) if client else {}
        if 'image_matchings' not in st.session_state:
            st.session_state['image_matchings'] = load_image_matchings(client) if client else {}

        # 챕터별 학생 후보 (해당 챕터 폴더가 있는 학생만)
        _chapter_students = get_students_with_chapter_folder(current_chapter)

        # 매칭 안된 그림이면 이미지 위에 picker 노출
        render_match_picker(
            current_img_path,
            st.session_state['student_name'],
            current_chapter,
            _chapter_students,
            st.session_state['image_matchings'],
            client,
            key_suffix="play",
        )

        display_responsive_image(current_img_path, is_grid=False)

        # ── 구간 단위 멀티 그림칸 녹음·재생 그리드 ──
        render_section_audio_grid(
            current_img_path,
            st.session_state['student_name'],
            current_chapter,
            st.session_state['sentence_bank'],
            st.session_state['chapter_mapping'],
            st.session_state['image_matchings'],
        )

        # ── 활성 그림칸(음원 있는 칸) 수 계산 — 통과/미통과 안내 표시용 ──
        _active_pane_count = 0
        _cur_section_str, _ = extract_section_slot_from_filename(os.path.basename(current_img_path))
        if _cur_section_str:
            _panes_in_sec = st.session_state.get('chapter_mapping', {}).get(
                (str(current_chapter), _cur_section_str), []
            )
            _img_match_key = (st.session_state['student_name'], str(current_chapter),
                              match_image_key(os.path.basename(current_img_path)))
            _owner_for_image = st.session_state.get('image_matchings', {}).get(_img_match_key)
            if _owner_for_image and _panes_in_sec:
                for _pn in _panes_in_sec:
                    _mp3 = get_audio_path_pane(str(current_chapter), _pn, _owner_for_image)
                    if os.path.exists(_mp3):
                        _active_pane_count += 1

        # 활성 그림칸이 있으면 안내 표시 (녹음 후 진행 유도). 0개면 안내 없이 바로 진행 가능.
        if _active_pane_count > 0:
            st.markdown(
                '<div style="background:#FEF3E2;border-left:4px solid #E67E22;padding:10px 14px;'
                'border-radius:6px;font-size:14px;color:#7E4A0E;margin:8px 0 12px 0;'
                'font-family:-apple-system,system-ui,sans-serif;">'
                f'🎙️ 빨간 버튼 <b>꾹 눌러서 떼기</b>로 그림칸 {_active_pane_count}개 모두 녹음한 후 진행해주세요.'
                '</div>',
                unsafe_allow_html=True
            )

        # ── 통과/미통과 (그리드 하단) — 파일 단위(=한 학생의 한 구간) 마킹 + 한 칸 진행 ──
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🙅 미통과", key='fail', use_container_width=True):
                if not is_practice and client:
                    save_to_sheet(client, st.session_state['student_name'], current_chapter,
                                  os.path.basename(current_img_path), "X")
                st.session_state['results'].append({'file': current_img_path, 'result': 'X'})
                st.session_state['current_index'] += 1
                st.rerun()
        with col2:
            if st.button("🙆 통과", key='pass', use_container_width=True):
                if not is_practice and client:
                    save_to_sheet(client, st.session_state['student_name'], current_chapter,
                                  os.path.basename(current_img_path), "O")
                st.session_state['results'].append({'file': current_img_path, 'result': 'O'})
                st.session_state['current_index'] += 1
                st.rerun()

        # ── 매칭 수정 (현재 그림 owner 확인/변경) — 그리드가 오디오 다 처리하므로 여기선 매칭 수정 UI만 ──
        render_image_answer_widget(
            current_img_path,
            st.session_state['student_name'],
            current_chapter,
            _chapter_students,
            st.session_state['sentence_bank'],
            st.session_state['chapter_mapping'],
            st.session_state['image_matchings'],
            client,
            key_suffix="play",
            match_only=True,
        )

        if idx > 0 and not is_practice:
            st.write("")
            if st.button("⬅️ 이전 취소 (Undo)", use_container_width=True):
                st.session_state['current_index'] -= 1
                st.session_state['results'].pop()
                st.rerun()

        if is_practice:
            st.write("")
            if st.button("연습 종료 후 결과로 돌아가기", use_container_width=True):
                st.session_state['mode'] = 'daily_result' if is_daily else 'setup'
                st.rerun()

    else:
        if is_practice:
            random.shuffle(st.session_state['playlist'])
            st.session_state['current_index'] = 0
            st.rerun()
        else:
            if is_daily:
                st.session_state['mode'] = 'daily_result'
                st.rerun()
            else:
                st.success("훈련 완료!")
                results = st.session_state['results']
                failed_items = [r['file'] for r in results if r['result'] == 'X']
                st.markdown(f"### 결과: {len([r for r in results if r['result'] == 'O'])} / {len(results)}")

                # 결과 목록: 이미지 + O/X + 정답 듣기 (매칭/음원 기반)
                _sent_bank = st.session_state.get('sentence_bank') or (load_sentence_bank(client) if client else {})
                _chap_map = st.session_state.get('chapter_mapping') or (load_chapter_mapping(client) if client else {})
                _img_match = st.session_state.get('image_matchings') or (load_image_matchings(client) if client else {})
                st.markdown("#### 📋 라운드 복기")
                r_cols = st.columns(2)
                for _ri, _r in enumerate(results):
                    with r_cols[_ri % 2]:
                        _fname = os.path.basename(_r['file'])
                        _chapter = os.path.basename(os.path.dirname(_r['file']))
                        _chapter_students = get_students_with_chapter_folder(_chapter)
                        _mark = "🟢 O" if _r['result'] == 'O' else "🔴 X"
                        st.markdown(f"**{_mark}** · `{_fname}`")
                        display_responsive_image(_r['file'], is_grid=True)
                        render_match_picker(
                            _r['file'], st.session_state['student_name'], _chapter,
                            _chapter_students, _img_match, client, key_suffix=f"result_{_ri}"
                        )
                        render_image_answer_widget(
                            _r['file'], st.session_state['student_name'], _chapter,
                            _chapter_students, _sent_bank, _chap_map, _img_match, client, key_suffix=f"result_{_ri}"
                        )
                        st.markdown("&nbsp;", unsafe_allow_html=True)

                st.markdown("---")
                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("재도전", use_container_width=True):
                        st.session_state.update({'playlist': random.sample(st.session_state['original_playlist'], len(st.session_state['original_playlist'])), 'current_index': 0, 'results': [], 'is_practice_mode': False})
                        st.rerun()
                with c2:
                    if failed_items and st.button("틀린 구간 반복", use_container_width=True):
                        st.session_state.update({'playlist': random.sample(failed_items, len(failed_items)), 'current_index': 0, 'results': [], 'is_practice_mode': True})
                        st.rerun()
                with c3:
                    if st.button("처음으로", use_container_width=True): st.session_state['mode'] = 'setup'; st.rerun()

elif st.session_state['mode'] == 'daily_result':
    st.success("🎉 오늘의 Daily Homework 완료!")
    results = st.session_state['results']
    failed_items = [r['file'] for r in results if r['result'] == 'X']
    
    st.markdown("### 📸 카카오톡 인증하기")
    st.info("👇 아래 이미지를 꾸욱 눌러서 **'복사'**한 뒤, 카카오톡 단톡방에 붙여넣어 인증해 주세요!")
    
    if 'daily_summary_img' not in st.session_state:
        with st.spinner("인증용 이미지를 굽고 있습니다..."):
            if client: save_to_sheet(client, st.session_state['student_name'], "Attendance", "Daily", "DONE")
            
            question = None
            if "Syntax + Open-ended Question" in st.session_state['folder_name']:
                question = get_random_question(client, st.session_state['student_name'])
                st.session_state['daily_question'] = question
            
            today = get_kst_now()
            attended_days = get_attendance(client, st.session_state['student_name'], today.year, today.month)
            
            db_df = st.session_state.get('db_data', pd.DataFrame())
            b64_img = create_summary_image_base64(st.session_state['student_name'], results, db_df, question, today.year, today.month, attended_days)
            st.session_state['daily_summary_img'] = b64_img

    b64_img = st.session_state['daily_summary_img']
    st.markdown(f'<img src="data:image/jpeg;base64,{b64_img}" style="width:100%; max-width:800px; border-radius:8px;">', unsafe_allow_html=True)

    # 정답 복기 (음원 + 매칭)
    st.markdown("---")
    with st.expander("📋 오늘의 라운드 복기 · 정답 듣기", expanded=False):
        _sent_bank_d = st.session_state.get('sentence_bank') or (load_sentence_bank(client) if client else {})
        _chap_map_d = st.session_state.get('chapter_mapping') or (load_chapter_mapping(client) if client else {})
        _img_match_d = st.session_state.get('image_matchings') or (load_image_matchings(client) if client else {})
        d_cols = st.columns(2)
        for _di, _dr in enumerate(results):
            with d_cols[_di % 2]:
                _dfname = os.path.basename(_dr['file'])
                _dchapter = os.path.basename(os.path.dirname(_dr['file']))
                _dchapter_students = get_students_with_chapter_folder(_dchapter)
                _dmark = "🟢 O" if _dr['result'] == 'O' else "🔴 X"
                st.markdown(f"**{_dmark}** · `{_dfname}`")
                display_responsive_image(_dr['file'], is_grid=True)
                render_match_picker(
                    _dr['file'], st.session_state['student_name'], _dchapter,
                    _dchapter_students, _img_match_d, client, key_suffix=f"daily_{_di}"
                )
                render_image_answer_widget(
                    _dr['file'], st.session_state['student_name'], _dchapter,
                    _dchapter_students, _sent_bank_d, _chap_map_d, _img_match_d, client, key_suffix=f"daily_{_di}"
                )
                st.markdown("&nbsp;", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if failed_items and st.button("틀린 구간 반복", use_container_width=True):
            st.session_state.update({'playlist': [r['file'] for r in results if r['result'] == 'X'], 'current_index': 0, 'is_practice_mode': True, 'mode': 'daily_playing'})
            st.rerun()
    with c2:
        if st.button("홈 화면으로", use_container_width=True):
            st.session_state['mode'] = 'setup'
            st.rerun()

elif st.session_state['mode'] == 'records':
    chapter_names = ", ".join([ch_name for ch_path, ch_name in st.session_state['selected_chapters']])
    st.title(f"피칭 기록: {st.session_state['student_name']} - {chapter_names}")
    if st.button("뒤로가기"): st.session_state['mode'] = 'setup'; st.rerun()

    all_imgs = []
    for ch_path, ch_name in st.session_state['selected_chapters']:
        all_imgs.extend(get_images(st.session_state['folder_name'], st.session_state['student_name'], ch_path))

    # 새 정답 시스템 데이터 로드 (SentenceBank + chapter mapping)
    sentence_bank_rec = load_sentence_bank(client) if client else {}
    chapter_map_rec = load_chapter_mapping(client) if client else {}
    img_match_rec = load_image_matchings(client) if client else {}

    if all_imgs and 'db_data' in st.session_state:
        cols = st.columns(3)
        for i, img_path in enumerate(all_imgs):
            with cols[i % 3]:
                display_responsive_image(img_path, is_grid=True)
                avg, history = calculate_batting_average(st.session_state['db_data'], st.session_state['student_name'], img_path)
                color = "green" if avg >= 0.8 else "orange" if avg >= 0.5 else "red"
                hist_str = " ".join([f"{h}" for h in history])
                st.caption(f"타율: :{color}[{avg*100:.0f}%] | {hist_str}")
                ch_name_rec = os.path.basename(os.path.dirname(img_path))
                chapter_students_rec = get_students_with_chapter_folder(ch_name_rec)
                render_match_picker(
                    img_path, st.session_state['student_name'], ch_name_rec,
                    chapter_students_rec, img_match_rec, client, key_suffix=f"rec_{i}"
                )
                render_image_answer_widget(
                    img_path, st.session_state['student_name'], ch_name_rec,
                    chapter_students_rec, sentence_bank_rec, chapter_map_rec, img_match_rec, client, key_suffix=f"rec_{i}"
                )

elif st.session_state['mode'] == 'help':
    # 상단 돌아가기
    if st.button("처음으로", key="help_back_top"):
        st.session_state['mode'] = 'setup'
        if 'view' in st.query_params:
            del st.query_params['view']
        st.rerun()

    st.markdown("""
# Syntax Pitching Manual

<p style="font-size:17px;font-weight:700;margin-top:32px;margin-bottom:10px;">소개</p>

Syntax Pitching은 쿠숙반의 Syntax 커리큘럼에서 익힌 구문 패턴을 혼자서 반복 연습할 수 있도록 만든 도구입니다. 야구장의 피칭 머신이 공을 쏘듯, 그간 작성한 손그림들이 무작위 순서로 날아올 거예요. 여러분은 타자가 되어 날아든 공을 받아쳐 보세요.

<p style="font-size:17px;font-weight:700;margin-top:32px;margin-bottom:10px;">피칭 패턴</p>

피칭 시 [미통과], [통과] 버튼을 적극적으로 활용하세요. 손그림의 출제 방식은 무작위이지만, 여러분이 기록하는 통과 여부에 따라 Daily Homework의 출제 패턴이 달라집니다.

- 수업 후 새로 추가된 그림은 5회 피칭 데이터가 쌓일 때까지 우선 출제됩니다.
- 최근 5회 기록 중 미통과 비율이 높은 손그림일수록 우선 출제됩니다.
- Daily Homework는 매일 현행 챕터에서 6장, 지난 챕터에서 4장으로 구성되며, 한쪽이 부족하면 다른 쪽에서 자동으로 보충해 총 10장이 채워집니다.
- 같은 조건이라면 덜 노출된 그림이 먼저 출제되어, 손그림 간 출제 빈도가 자연스럽게 균형을 잡습니다.

<p style="font-size:17px;font-weight:700;margin-top:32px;margin-bottom:10px;">연습 시</p>

피칭 연습 시 항상 '두더지(강세)'를 꼼꼼히 잡아주세요. 영어 문장의 각 소리 단위에서 강조점을 살리거나 떨어뜨려야 듣는 사람이 여러분의 의도를 정확히 읽을 수 있습니다.

<p style="font-size:17px;font-weight:700;margin-top:32px;margin-bottom:10px;">정답 듣기</p>

피칭 중 정답 문장이 기억나지 않을 때 더 이상 교재나 Notion을 열어볼 필요가 없습니다. 그림 아래의 '정답 듣기' 버튼을 누르면 선생님이 미리 등록해둔 원어민 음성으로 해당 구간의 정답 문장이 재생됩니다.

다만 처음 보는 그림은 누구의 내용인지 시스템이 알지 못합니다. 그래서 그림 상단에 '누구의 내용인지 알려주세요!' 라는 안내가 뜨면 드롭다운에서 해당 학생 이름을 골라주세요. 한 번 매칭해두면 다음부터는 안내가 사라지고 정답 듣기만 보이게 됩니다.

혹시 잘못 매칭하셨다면 그림 하단의 '그림 매칭 수정' 버튼으로 언제든 변경할 수 있습니다.

<p style="font-size:17px;font-weight:700;margin-top:32px;margin-bottom:10px;">에러가 났을 때</p>

혹시 피칭 이용에 문제가 생긴다면 언제든지 San에게 톡으로 알려주세요. 참고로 본 웹앱은 일정 시간 동안 수강생 방문이 없으면 수면 모드로 진입하는 특성이 있습니다. 간혹 접속 시 'Web is sleeping' 문구가 뜨더라도 약 30초 정도 기다려 주시면 정상 작동합니다.
""", unsafe_allow_html=True)

    st.write("")
    st.write("")
    if st.button("처음으로 돌아가기", key="help_back_bottom"):
        st.session_state['mode'] = 'setup'
        if 'view' in st.query_params:
            del st.query_params['view']
        st.rerun()

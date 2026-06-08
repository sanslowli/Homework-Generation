import streamlit as st
import streamlit.components.v1 as components
import os
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
LEGACY_BACKFILL_CHAPTER = "602"  # 마이그레이션 당시 모든 데이터가 602였음

def get_or_create_answers_sheet(client):
    """Answers 워크시트 반환. 없으면 생성, 옛 4-col 포맷이면 Chapter 컬럼 자동 백필."""
    try:
        spreadsheet = client.open(SHEET_NAME)
        try:
            ws = spreadsheet.worksheet("Answers")
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title="Answers", rows=1000, cols=5)
            ws.append_row(ANSWERS_HEADER)
            return ws

        # 빈 시트 방어
        header = ws.row_values(1)
        if not header:
            ws.append_row(ANSWERS_HEADER)
            return ws

        # 헤더에 Chapter가 없으면 → 옛 [Student, Image, Answer, Updated] 포맷
        # 모든 행에 Chapter='602' 삽입해서 5-col 포맷으로 변환
        if "Chapter" not in header:
            all_vals = ws.get_all_values()
            new_rows = [ANSWERS_HEADER]
            for row in all_vals[1:]:
                padded = list(row) + [""] * (4 - len(row))
                new_rows.append([
                    padded[0],                          # Student
                    LEGACY_BACKFILL_CHAPTER,            # Chapter (백필)
                    padded[1],                          # Image
                    padded[2],                          # Answer
                    padded[3],                          # Updated
                ])
            ws.clear()
            ws.update("A1", new_rows)
        return ws
    except Exception as e:
        return None

@st.cache_data(ttl=60, show_spinner=False)
def load_answers_for_student(_client, student):
    """{(chapter, image_filename): answer_text} 반환. 60초 캐시."""
    if _client is None:
        return {}
    try:
        ws = get_or_create_answers_sheet(_client)
        if ws is None:
            return {}
        rows = ws.get_all_records()
        return {
            (str(r.get("Chapter", "")), r["Image"]): r["Answer"]
            for r in rows
            if r.get("Student") == student and r.get("Image") and r.get("Answer")
        }
    except Exception:
        return {}

def save_answer(client, student, chapter, image, answer):
    """학생-챕터-이미지 키로 upsert. 같은 (Student, Chapter, Image) 행이 있으면 업데이트, 없으면 append."""
    if client is None:
        return False
    try:
        ws = get_or_create_answers_sheet(client)
        if ws is None:
            return False
        rows = ws.get_all_values()
        timestamp = get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
        found_row = None
        for i, r in enumerate(rows[1:], start=2):  # 1행은 헤더
            # 5-col 포맷: [Student, Chapter, Image, Answer, Updated]
            if len(r) >= 3 and r[0] == student and r[1] == str(chapter) and r[2] == image:
                found_row = i
                break
        if found_row:
            # Answer(D) + Updated(E) 열만 업데이트
            ws.update(f"D{found_row}:E{found_row}", [[answer, timestamp]])
        else:
            ws.append_row([student, str(chapter), image, answer, timestamp])
        # 캐시 무효화
        load_answers_for_student.clear()
        return True
    except Exception:
        return False

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
ANSWER_BANK_HEADER = ["Chapter", "Section", "Owner", "Sentences", "Updated"]
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
    """'1-3.png' → ('1', 3), '11-2.png' → ('11', 2). 실패 시 (None, None)."""
    try:
        name = os.path.splitext(os.path.basename(image_filename))[0]
        if "-" in name:
            parts = name.split("-", 1)
            section = parts[0].strip()
            slot_part = parts[1].strip()
            if section.isdigit() and slot_part.isdigit():
                return section, int(slot_part)
    except Exception:
        pass
    return None, None


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

def get_or_create_answer_bank_sheet(client):
    """AnswerBank 워크시트 반환. 없으면 생성."""
    try:
        spreadsheet = client.open(SHEET_NAME)
        try:
            ws = spreadsheet.worksheet("AnswerBank")
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title="AnswerBank", rows=1000, cols=5)
            ws.append_row(ANSWER_BANK_HEADER)
            return ws
        header = ws.row_values(1)
        if not header:
            ws.append_row(ANSWER_BANK_HEADER)
        return ws
    except Exception as e:
        # APIError 429(quota) 는 일시적이므로 무시; 그 외만 표시
        if "429" not in str(e):
            st.error(f"[디버그] get_or_create_answer_bank_sheet 에러: {type(e).__name__}: {e}")
        return None

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

@st.cache_data(ttl=120, show_spinner=False)
def load_answer_bank(_client):
    """{(chapter, section, owner): sentences} 반환. 2분 캐시."""
    if _client is None:
        return {}
    try:
        ws = get_or_create_answer_bank_sheet(_client)
        if ws is None:
            st.error("[디버그] load_answer_bank: 워크시트를 가져오지 못함")
            return {}
        rows = ws.get_all_records()
        result = {}
        for r in rows:
            chapter = str(r.get("Chapter", "")).strip()
            section = str(r.get("Section", "")).strip()
            owner = str(r.get("Owner", "")).strip()
            sentences = r.get("Sentences", "")
            if chapter and section and owner and sentences:
                result[(chapter, section, owner)] = sentences
        return result
    except Exception as e:
        if "429" not in str(e):
            st.error(f"[디버그] load_answer_bank 에러: {type(e).__name__}: {e}")
        return {}

def save_answer_bank(client, chapter, section, owner, sentences):
    """(Chapter, Section, Owner) 키로 upsert."""
    if client is None:
        st.error("[디버그] client 가 None 입니다 — 구글 시트 인증 실패")
        return False
    try:
        ws = get_or_create_answer_bank_sheet(client)
        if ws is None:
            st.error("[디버그] AnswerBank 워크시트를 가져오지 못했습니다")
            return False
        rows = ws.get_all_values()
        timestamp = get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
        found_row = None
        for i, r in enumerate(rows[1:], start=2):
            if len(r) >= 3 and r[0] == str(chapter) and r[1] == str(section) and r[2] == owner:
                found_row = i
                break
        if found_row:
            ws.update(f"D{found_row}:E{found_row}", [[sentences, timestamp]])
        else:
            ws.append_row([str(chapter), str(section), owner, sentences, timestamp])
        load_answer_bank.clear()
        return True
    except Exception as e:
        if "429" not in str(e):
            st.error(f"[디버그] save_answer_bank 에러: {type(e).__name__}: {e}")
        return False

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
            image = str(r.get("Image", "")).strip()
            owner = str(r.get("ContentOwner", "")).strip()
            if img_student and chapter and image and owner:
                result[(img_student, chapter, image)] = owner
        return result
    except Exception:
        return {}

def save_image_matching(client, image_student, chapter, image, content_owner):
    """(ImageStudent, Chapter, Image) 키로 upsert. 빈 ContentOwner면 매칭 해제."""
    if client is None:
        return False
    try:
        ws = get_or_create_image_matching_sheet(client)
        if ws is None:
            return False
        rows = ws.get_all_values()
        timestamp = get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
        found_row = None
        for i, r in enumerate(rows[1:], start=2):
            if len(r) >= 3 and r[0] == image_student and r[1] == str(chapter) and r[2] == image:
                found_row = i
                break
        if found_row:
            ws.update(f"D{found_row}:E{found_row}", [[content_owner, timestamp]])
        else:
            ws.append_row([image_student, str(chapter), image, content_owner, timestamp])
        load_image_matchings.clear()
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

def render_answer_reveal(answer_text, reveal_label="🔒 정답 보기 (꾹 누르기)", speak_label="🔊 정답 듣기 (한 번 탭)"):
    """press-and-hold 텍스트 reveal + 단일 탭 TTS 재생 위젯.
    Streamlit은 st.markdown 의 인라인 JS 핸들러를 제거하므로
    components.v1.html (iframe) 로 실제 JS 이벤트가 동작하게 한다."""

    # ── 정답이 없는 경우: 짧은 플레이스홀더 ──
    if not answer_text:
        placeholder_html = """
        <div style="margin:0;color:#bbb;font-size:13px;padding:10px 12px;
                    border:1px dashed #ddd;border-radius:6px;
                    font-family:-apple-system,system-ui,'Noto Sans KR',sans-serif;">
          정답 미등록 — '📝 정답 입력' 메뉴에서 등록 가능
        </div>
        """
        components.html(placeholder_html, height=48, scrolling=False)
        return

    # ── HTML 이스케이프 + 개행 → <br> ──
    raw = str(answer_text)
    safe = (
        raw.replace("&", "&amp;")
           .replace("<", "&lt;")
           .replace(">", "&gt;")
           .replace('"', "&quot;")
           .replace("'", "&#39;")
           .replace("\n", "<br>")
    )
    # JS에서 안전하게 쓰일 JSON 인코딩 문자열 (따옴표·이스케이프 포함)
    js_text = json.dumps(raw)

    # ── 표시 줄 수 추정 (iframe 높이 동적 계산) ──
    # 14px 폰트 기준: 좁은 모바일에서 ~45자/줄
    est_lines = 0
    for ln in raw.split("\n"):
        est_lines += max(1, (len(ln) + 44) // 45)
    est_lines = max(1, min(est_lines, 12))  # 상한 12줄

    # 듣기 버튼(45) + gap(8) + 보기 버튼(45) + margin(10) + 박스 padding 30 + line 23px * n + 버퍼 12
    total_h = 45 + 8 + 45 + 10 + 30 + est_lines * 23 + 12

    uid = base64.b64encode(os.urandom(6)).decode().replace("/", "_").replace("+", "-").rstrip("=")

    html = f"""
    <div style="margin:0;font-family:-apple-system,system-ui,'Noto Sans KR',sans-serif;">
      <button id="play_{uid}"
        style="background:#2980B9;color:white;border:none;border-radius:8px;
               padding:10px 16px;font-size:15px;font-weight:600;cursor:pointer;
               width:100%;user-select:none;-webkit-user-select:none;
               margin-bottom:8px;">
        {speak_label}
      </button>
      <button id="btn_{uid}"
        style="background:#34495E;color:white;border:none;border-radius:8px;
               padding:10px 16px;font-size:15px;font-weight:600;cursor:pointer;
               width:100%;user-select:none;-webkit-user-select:none;touch-action:none;">
        {reveal_label}
      </button>
      <div id="ans_{uid}"
        style="opacity:0;transition:opacity 0.1s;margin-top:10px;padding:14px;
               background:#FFF8E1;border:1px solid #F0D070;border-radius:8px;
               font-size:14px;line-height:1.6;color:#333;pointer-events:none;
               word-wrap:break-word;overflow-wrap:break-word;">
        {safe}
      </div>
      <script>
        (function(){{
          // ── press-and-hold 텍스트 reveal ──
          var btn = document.getElementById('btn_{uid}');
          var ans = document.getElementById('ans_{uid}');
          var show = function(){{ ans.style.opacity = '1'; }};
          var hide = function(){{ ans.style.opacity = '0'; }};
          if (btn) {{
            btn.addEventListener('mousedown', show);
            btn.addEventListener('mouseup', hide);
            btn.addEventListener('mouseleave', hide);
            btn.addEventListener('touchstart', function(e){{ e.preventDefault(); show(); }}, {{passive:false}});
            btn.addEventListener('touchend', hide);
            btn.addEventListener('touchcancel', hide);
          }}

          // ── TTS 재생 (lazy: 클릭 시점에만 voice 조회. Safari resetVoiceList 레이스 회피) ──
          var playBtn = document.getElementById('play_{uid}');
          var answerText = {js_text};
          function speak() {{
            if (!('speechSynthesis' in window)) {{
              alert('이 브라우저는 음성 재생을 지원하지 않습니다.');
              return;
            }}
            try {{
              window.speechSynthesis.cancel();
              var utter = new SpeechSynthesisUtterance(answerText);
              utter.lang = 'en-US';
              utter.rate = 0.9;
              utter.pitch = 1.0;
              // voice 선택: en-US 한정 + 미국 여성 음성 우선
              try {{
                var voices = window.speechSynthesis.getVoices() || [];
                // 1단계: lang이 en-US 인 음성만 추림
                var enUS = [];
                for (var i = 0; i < voices.length; i++) {{
                  var lng = (voices[i].lang || '').toLowerCase();
                  if (lng === 'en-us' || lng === 'en_us' || lng.indexOf('en-us') === 0) {{
                    enUS.push(voices[i]);
                  }}
                }}
                // 2단계: en-US 안에서 알려진 미국 여성 이름 우선순위로 매칭
                var femaleNames = ['Samantha', 'Ava', 'Allison', 'Susan', 'Zoe', 'Joanna', 'Salli', 'Princess'];
                var preferred = null;
                for (var k = 0; k < femaleNames.length && !preferred; k++) {{
                  for (var m = 0; m < enUS.length; m++) {{
                    if (enUS[m].name && enUS[m].name.indexOf(femaleNames[k]) >= 0) {{
                      preferred = enUS[m]; break;
                    }}
                  }}
                }}
                // 3단계: en-US 여성을 못 찾으면 그냥 en-US 아무거나
                if (!preferred && enUS.length > 0) preferred = enUS[0];
                // 4단계: en-US가 아예 없으면 그 어떤 en- 음성이라도 (영국식 가능성 있음)
                if (!preferred) {{
                  for (var n = 0; n < voices.length; n++) {{
                    if (voices[n].lang && voices[n].lang.toLowerCase().indexOf('en') === 0) {{
                      preferred = voices[n]; break;
                    }}
                  }}
                }}
                if (preferred) utter.voice = preferred;
              }} catch (vErr) {{ /* voice 선택 실패 시 기본값으로 진행 */ }}
              window.speechSynthesis.speak(utter);
            }} catch (e) {{
              console.error('TTS error', e);
            }}
          }}
          if (playBtn) {{
            playBtn.addEventListener('click', speak);
            playBtn.addEventListener('touchstart', function(e){{ e.preventDefault(); speak(); }}, {{passive:false}});
          }}
        }})();
      </script>
    </div>
    """
    components.html(html, height=total_h, scrolling=False)

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
    image_filename = os.path.basename(current_image_path)
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

    # 그리드 컬럼: 최소 4 + 실제 패네 수가 더 많으면 그만큼 확장
    n_pane_cols = max(4, len(pane_infos))
    n_total_cols = n_pane_cols + 1  # +1 = 특수 버튼 컬럼

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
        f'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;">🎤 다시</button>'
    )

    # 그리드 row 2: 정답 듣기 버튼들 (초기 잠금)
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
    play_buttons_html += (
        f'<button id="play_all_{uid}" disabled '
        f'style="background:#BDC3C7;color:white;border:none;border-radius:8px;'
        f'padding:14px 0;font-size:13px;font-weight:600;cursor:not-allowed;opacity:0.5;'
        f'user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;">🔊 전체 듣기</button>'
    )

    html = f"""
    <div style="font-family:-apple-system,system-ui,'Noto Sans KR',sans-serif;margin:0;">
      {audio_tags}
      <div style="display:grid;grid-template-columns:repeat({n_total_cols},1fr);gap:5px;margin-bottom:5px;">
        {rec_buttons_html}
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

        // 파랑 버튼 lock/unlock
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

        // 전체듣기 활성
        function updatePlayAll() {{
          var btn = $('play_all_' + UID);
          if (!btn) return;
          var any = Object.keys(recordings).length > 0;
          btn.disabled = !any;
          btn.style.background = any ? '#2980B9' : '#BDC3C7';
          btn.style.opacity = any ? '1' : '0.5';
          btn.style.cursor = any ? 'pointer' : 'not-allowed';
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
              updatePlayAll();
              currentRecSlot = null;
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
              var el = document.querySelector('#rec_btn_' + slot + '_' + UID + ' .rec-timer');
              if (el) el.textContent = mm + ':' + (ss < 10 ? '0' + ss : ss);
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

        // 녹음 버튼 클릭 핸들러
        PANES.forEach(function(p){{
          if (!p.ready) return;
          var btn = $('rec_btn_' + p.slot + '_' + UID);
          if (!btn) return;
          btn.addEventListener('click', function(){{
            if (isRecording && currentRecSlot === p.slot) {{
              stopRecording();
            }} else {{
              startRecording(p.slot);
            }}
          }});
        }});

        // 정답 듣기 버튼 클릭 (내 녹음 → 정답)
        PANES.forEach(function(p){{
          var btn = $('play_btn_' + p.slot + '_' + UID);
          if (!btn) return;
          btn.addEventListener('click', function(){{
            if (btn.disabled) return;
            stopAllPlayback();
            playQueue = [{{kind:'mine', slot:p.slot}}, {{kind:'answer', slot:p.slot}}];
            playNext();
          }});
        }});

        // 전체 듣기
        var allBtn = $('play_all_' + UID);
        if (allBtn) {{
          allBtn.addEventListener('click', function(){{
            if (allBtn.disabled) return;
            stopAllPlayback();
            var recorded = PANES.filter(function(p){{ return p.ready && recordings[p.slot]; }});
            playQueue = [];
            recorded.forEach(function(p){{ playQueue.push({{kind:'mine', slot:p.slot}}); }});
            recorded.forEach(function(p){{ playQueue.push({{kind:'answer', slot:p.slot}}); }});
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
    image_filename = os.path.basename(image_path)
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
    image_filename = os.path.basename(image_path)
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

        # 3) 이미지 — 전폭의 가로 중앙 정렬
        img_w = item['img'].size[0]
        img_x = x_off + (max_img_w - img_w) // 2 if img_w < max_img_w else x_off
        final_image.paste(item['img'], (img_x, y_off + CELL_HEADER_H))

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
url_teacher = query_params.get("teacher")

all_students_info = get_all_students()
selected_data = None

# ==========================================
# [Teacher Mode] 선생님용 대시보드 (?teacher=1)
# ==========================================
if url_teacher == "1":
    st.sidebar.markdown(
        '<div style="background:#E74C3C;color:white;padding:8px 12px;border-radius:6px;'
        'font-weight:700;text-align:center;margin-bottom:20px;">🎓 TEACHER MODE</div>',
        unsafe_allow_html=True
    )

    # 사이드바 — 페이지 전환
    teacher_view = query_params.get("view", "dashboard")
    st.sidebar.markdown("### 페이지")
    _existing_qs_t = "&".join(f"{k}={v}" for k, v in query_params.items() if k not in ("view",))
    _qbase = (f"?{_existing_qs_t}") if _existing_qs_t else "?teacher=1"
    if not _existing_qs_t:
        _qbase = "?teacher=1"
    _dash_link = _qbase
    _ans_link = (f"{_qbase}&view=answers")
    st.sidebar.markdown(
        f'<div style="margin-bottom:6px;"><a href="{_dash_link}" target="_self" '
        f'style="text-decoration:{"none" if teacher_view!="answers" else "underline"};'
        f'color:{"#E74C3C" if teacher_view!="answers" else "#666"};'
        f'font-weight:{"700" if teacher_view!="answers" else "400"};">📊 수강생 대시보드</a></div>'
        f'<div><a href="{_ans_link}" target="_self" '
        f'style="text-decoration:{"none" if teacher_view=="answers" else "underline"};'
        f'color:{"#E74C3C" if teacher_view=="answers" else "#666"};'
        f'font-weight:{"700" if teacher_view=="answers" else "400"};">📝 정답 입력</a></div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown("---")

    # ── 정답 입력 페이지 ──
    if teacher_view == "answers":
        st.title("📝 AnswerBank — 정답 입력")
        st.caption("챕터·학생 선택 후 각 구간의 문장을 입력합니다. 저장된 데이터는 GitHub Actions 의 'Generate TTS Audio' 워크플로우가 mp3 로 변환합니다.")

        if not client:
            st.error("구글 시트 연결 실패")
            st.stop()

        # 전체 챕터 목록 + 폴더 인덱스 (chapter → list of (folder, student, sub) tuples)
        chapter_index = {}  # {chapter_name: [(folder, student, sub), ...]}
        for folder_name in TARGET_FOLDERS:
            target_path = os.path.join(BASE_FOLDER, folder_name)
            if not os.path.exists(target_path):
                continue
            for student_d in os.listdir(target_path):
                if student_d.startswith('.'):
                    continue
                for sub in ALLOWED_SUBFOLDERS:
                    sub_path = os.path.join(target_path, student_d, sub)
                    if os.path.exists(sub_path):
                        try:
                            for ch in os.listdir(sub_path):
                                if not ch.startswith('.') and os.path.isdir(os.path.join(sub_path, ch)):
                                    chapter_index.setdefault(ch, []).append((folder_name, student_d, sub))
                        except Exception:
                            pass
        all_chapters = set(chapter_index.keys())
        if not all_chapters:
            st.warning("챕터를 찾을 수 없습니다.")
            st.stop()

        # 챕터 그룹핑: "602"와 "602S"가 둘 다 있으면 "602(S)" 로 묶음
        # 명명 규칙: S 접미사 = 기초, 접미사 없음 = 심화
        # display_name -> {"basic": "602S" or None, "advanced": "602" or None}
        chapter_groups = {}
        for ch in all_chapters:
            if ch.endswith('S'):
                # S 붙은 것 = 기초
                base = ch[:-1]
                if base in all_chapters:
                    display = f"{base}(S)"
                    chapter_groups.setdefault(display, {"basic": None, "advanced": None})["basic"] = ch
                else:
                    chapter_groups.setdefault(ch, {"basic": None, "advanced": None})["basic"] = ch
            else:
                # S 안 붙은 것 = 심화
                s_variant = ch + "S"
                if s_variant in all_chapters:
                    display = f"{ch}(S)"
                    chapter_groups.setdefault(display, {"basic": None, "advanced": None})["advanced"] = ch
                else:
                    chapter_groups.setdefault(ch, {"basic": None, "advanced": None})["advanced"] = ch

        # 정렬 키: 숫자 부분으로 정렬, 같은 숫자면 (S) 우선
        def _ch_sort_key(d):
            digits = ''.join(c for c in d if c.isdigit())
            return (int(digits) if digits else 0, d)
        chapter_display_names = sorted(chapter_groups.keys(), key=_ch_sort_key)

        ans_bank_t = load_answer_bank(client)

        col_ch, col_stu = st.columns([1, 1])
        with col_ch:
            ans_chapter_display = st.selectbox("챕터", chapter_display_names, key="t_ans_chapter")

        group_info = chapter_groups[ans_chapter_display]
        ch_basic = group_info["basic"]       # 기초 챕터명 (예: "602"), 없으면 None
        ch_advanced = group_info["advanced"] # 심화 챕터명 (예: "602S"), 없으면 None

        # 학생 후보: basic 또는 advanced 폴더 중 하나라도 있는 학생 합집합
        students_with_chapter = set()
        for ch_name in (ch_basic, ch_advanced):
            if not ch_name:
                continue
            for (_f, stu, _sub) in chapter_index.get(ch_name, []):
                students_with_chapter.add(stu)
        students_with_chapter_sorted = sorted(students_with_chapter)

        with col_stu:
            if not students_with_chapter_sorted:
                st.warning(f"챕터 {ans_chapter_display} 폴더를 가진 학생이 없습니다.")
                ans_student = None
            else:
                ans_student = st.selectbox("학생", students_with_chapter_sorted, key="t_ans_student")

        if not ans_student:
            st.stop()

        # 각 변형(basic/advanced)별로 구간 1-4 항상 노출 + 실제 그림이 있으면 샘플로 표시
        # 그림 파일 존재 여부와 무관하게 입력 항상 가능
        DEFAULT_SECTIONS = ["1", "2", "3", "4"]

        def collect_sections_for_variant(ch_name):
            """{section: sample_image_path or None} 반환.
            구간 1~4는 무조건 포함, 파일에서 더 큰 번호가 발견되면 추가로 포함.
            샘플 이미지: 본인 폴더 우선, 없으면 다른 학생 폴더."""
            if not ch_name:
                return {}
            sections_map = {sec: None for sec in DEFAULT_SECTIONS}

            own_sections = {}
            other_sections = {}
            for (folder_n, stu, sub) in chapter_index.get(ch_name, []):
                ch_path = os.path.join(BASE_FOLDER, folder_n, stu, sub, ch_name)
                if not os.path.exists(ch_path):
                    continue
                try:
                    for f in sorted(os.listdir(ch_path)):
                        if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                            sec = extract_section_from_filename(f)
                            if sec:
                                full_path = os.path.join(ch_path, f)
                                if stu == ans_student:
                                    own_sections.setdefault(sec, full_path)
                                else:
                                    other_sections.setdefault(sec, full_path)
                except Exception:
                    pass

            # 본인 폴더 우선으로 샘플 이미지 매핑, 본인에 없으면 다른 학생 거 사용
            for sec, path in own_sections.items():
                sections_map[sec] = path
            for sec, path in other_sections.items():
                if sections_map.get(sec) is None:
                    sections_map[sec] = path

            # 이미 AnswerBank에 저장된 섹션도 노출 (사용자가 이전에 추가했던 5, 6, 7… 보존)
            for (ch_key, sec_key, stu_key) in ans_bank_t.keys():
                if str(ch_key) == str(ch_name) and stu_key == ans_student:
                    if sec_key not in sections_map:
                        sections_map[sec_key] = None

            return sections_map

        advanced_sections = collect_sections_for_variant(ch_advanced)
        basic_sections = collect_sections_for_variant(ch_basic)

        def _with_extras(sections_map, ch_name):
            """파일/저장 기반 섹션 + 사용자가 추가한 구간(session_state)을 합쳐 정렬."""
            sorted_secs = sorted(sections_map.keys(), key=lambda x: int(x) if x.isdigit() else 0)
            if not ch_name or not sorted_secs:
                return sorted_secs
            max_n = max((int(s) for s in sorted_secs if s.isdigit()), default=0)
            extra_n = int(st.session_state.get(f"extra_sec_{ch_name}_{ans_student}", 0))
            return sorted_secs + [str(max_n + i + 1) for i in range(extra_n)]

        adv_sorted = _with_extras(advanced_sections, ch_advanced)
        bas_sorted = _with_extras(basic_sections, ch_basic)

        if not adv_sorted and not bas_sorted:
            st.warning(f"{ans_student}의 {ans_chapter_display} 에 인식 가능한 구간이 없습니다.")
            st.stop()

        st.markdown(f"### 📘 {ans_chapter_display} · {ans_student}")
        _info_parts = []
        if adv_sorted:
            _info_parts.append(f"심화({ch_advanced}) 구간 {len(adv_sorted)}개")
        if bas_sorted:
            _info_parts.append(f"기초({ch_basic}) 구간 {len(bas_sorted)}개")
        st.caption(" · ".join(_info_parts))

        with st.form(key=f"answer_form_{ans_chapter_display}_{ans_student}"):
            new_values = []  # [(chapter_name, section, label_for_msg, value)]

            # ── 심화(S) 먼저 ──
            if ch_advanced and adv_sorted:
                st.markdown(
                    '<div style="background:#FFEBEE;border-left:4px solid #E74C3C;padding:8px 14px;'
                    'margin:8px 0 4px 0;border-radius:4px;">'
                    f'<b>심화 — {ch_advanced}</b></div>',
                    unsafe_allow_html=True
                )
                for sec in adv_sorted:
                    existing = ans_bank_t.get((str(ch_advanced), str(sec), ans_student), "")
                    _lines = max(3, min(8, existing.count("\n") + 2)) if existing else 4
                    _icon = '✅' if existing else '⚪'
                    st.markdown(f"**심화 구간 {sec}** {_icon}")
                    sample_img = advanced_sections.get(sec)
                    if sample_img and os.path.exists(sample_img):
                        with st.expander(f"🖼️ 심화 구간 {sec} 그림 보기", expanded=False):
                            display_responsive_image(sample_img, is_grid=True)
                            st.caption(os.path.basename(sample_img))
                    val = st.text_area(
                        label=f"심화 {sec}",
                        value=existing,
                        key=f"t_ans_adv_{ch_advanced}_{ans_student}_{sec}",
                        height=_lines * 28 + 20,
                        label_visibility="collapsed",
                        placeholder="심화 문장 입력...",
                    )
                    new_values.append((ch_advanced, sec, f"심화 {sec}", val))
                    st.markdown("&nbsp;", unsafe_allow_html=True)

            # ── 기초(non-S) ──
            if ch_basic and bas_sorted:
                st.markdown(
                    '<div style="background:#E3F2FD;border-left:4px solid #2980B9;padding:8px 14px;'
                    'margin:12px 0 4px 0;border-radius:4px;">'
                    f'<b>기초 — {ch_basic}</b></div>',
                    unsafe_allow_html=True
                )
                for sec in bas_sorted:
                    existing = ans_bank_t.get((str(ch_basic), str(sec), ans_student), "")
                    _lines = max(3, min(8, existing.count("\n") + 2)) if existing else 4
                    _icon = '✅' if existing else '⚪'
                    st.markdown(f"**기초 구간 {sec}** {_icon}")
                    sample_img = basic_sections.get(sec)
                    if sample_img and os.path.exists(sample_img):
                        with st.expander(f"🖼️ 기초 구간 {sec} 그림 보기", expanded=False):
                            display_responsive_image(sample_img, is_grid=True)
                            st.caption(os.path.basename(sample_img))
                    val = st.text_area(
                        label=f"기초 {sec}",
                        value=existing,
                        key=f"t_ans_bas_{ch_basic}_{ans_student}_{sec}",
                        height=_lines * 28 + 20,
                        label_visibility="collapsed",
                        placeholder="기초 문장 입력...",
                    )
                    new_values.append((ch_basic, sec, f"기초 {sec}", val))
                    st.markdown("&nbsp;", unsafe_allow_html=True)

            submitted = st.form_submit_button("💾 모두 저장", use_container_width=True, type="primary")

        if submitted:
            saved_count = 0
            skipped_count = 0
            for ch_name, sec, label, val in new_values:
                trimmed = val.strip()
                existing = ans_bank_t.get((str(ch_name), str(sec), ans_student), "")
                if trimmed == existing:
                    continue
                if save_answer_bank(client, ch_name, sec, ans_student, trimmed):
                    saved_count += 1
                else:
                    skipped_count += 1
            if saved_count > 0:
                st.success(f"✅ 항목 {saved_count}개 정답 저장 완료")
            if skipped_count > 0:
                st.warning(f"⚠️ {skipped_count}개 저장 실패")
            if saved_count == 0 and skipped_count == 0:
                st.toast("변경 사항이 없습니다.")
            else:
                st.rerun()

        # ── 구간 추가/제거 (Matcha 같은 예외 챕터용) ──
        st.markdown("---")
        st.markdown("##### ➕ 구간 추가 (예외 챕터용)")
        st.caption("Matcha처럼 구간을 5번 이후로 늘려야 하는 챕터에서 사용. 빙고 챕터는 손대지 않으면 영향 없음. 저장 안 한 상태에서 제거하면 입력값은 사라짐.")

        _extras_variants = []
        if ch_advanced:
            _extras_variants.append(("심화", ch_advanced))
        if ch_basic:
            _extras_variants.append(("기초", ch_basic))

        if _extras_variants:
            _ex_cols = st.columns(len(_extras_variants))
            for _ei, (_label, _ch_name) in enumerate(_extras_variants):
                with _ex_cols[_ei]:
                    _ex_key = f"extra_sec_{_ch_name}_{ans_student}"
                    _cur_extra = int(st.session_state.get(_ex_key, 0))
                    st.markdown(f"**{_label} — {_ch_name}** · 추가된 구간 {_cur_extra}개")
                    _bc1, _bc2 = st.columns(2)
                    with _bc1:
                        if st.button("➕ 구간 추가", key=f"add_{_label}_{_ch_name}_{ans_student}",
                                     use_container_width=True):
                            st.session_state[_ex_key] = _cur_extra + 1
                            st.rerun()
                    with _bc2:
                        if st.button("↩️ 마지막 제거", key=f"rm_{_label}_{_ch_name}_{ans_student}",
                                     disabled=(_cur_extra == 0), use_container_width=True):
                            st.session_state[_ex_key] = max(0, _cur_extra - 1)
                            st.rerun()

        # ── TTS 생성 트리거 (GitHub Actions) ──
        st.markdown("---")
        st.markdown("##### 🎙️ TTS 음원 생성")
        st.caption("정답을 입력·수정한 뒤 이 버튼을 누르면 GitHub Actions 워크플로우가 새 mp3 파일을 생성하고 자동으로 커밋합니다. 보통 1~3분 소요.")

        gh_pat = ""
        gh_repo = ""
        try:
            gh_pat = st.secrets.get("github_pat", "")
            gh_repo = st.secrets.get("github_repo", "")
        except Exception:
            pass

        tts_c1, tts_c2 = st.columns([2, 1])
        with tts_c1:
            tts_trigger_clicked = st.button("🎙️ TTS 생성 시작", type="primary", use_container_width=True,
                                            disabled=not (gh_pat and gh_repo))
        with tts_c2:
            if gh_repo:
                actions_url = f"https://github.com/{gh_repo}/actions/workflows/generate_tts.yml"
                st.link_button("Actions 보기", actions_url, use_container_width=True)

        if not (gh_pat and gh_repo):
            st.caption("⚠️ Streamlit secrets 에 `github_pat` 과 `github_repo` 가 설정되지 않아 버튼이 비활성화되어 있습니다.")

        if tts_trigger_clicked:
            try:
                import requests
                url = f"https://api.github.com/repos/{gh_repo}/actions/workflows/generate_tts.yml/dispatches"
                r = requests.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {gh_pat}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json={"ref": "main"},
                    timeout=15,
                )
                if r.status_code == 204:
                    st.success("✅ TTS 생성 워크플로우가 시작되었습니다. 1~3분 후 새 mp3 파일이 자동 커밋됩니다.")
                    st.session_state["last_tts_trigger"] = get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    st.error(f"실패 (HTTP {r.status_code}): {r.text[:300]}")
            except Exception as e:
                st.error(f"요청 실패: {e}")

        if "last_tts_trigger" in st.session_state:
            st.caption(f"마지막 트리거 시각: {st.session_state['last_tts_trigger']}")

        # ── AnswerBank 전체 상태 ──
        st.markdown("---")
        st.markdown("##### 📋 현재 AnswerBank 상태 (전체)")
        bank_rows = []
        for (ch, sec, owner), txt in sorted(ans_bank_t.items()):
            preview = (txt[:60] + "...") if len(txt) > 60 else txt
            bank_rows.append({
                "Chapter": ch, "Section": sec, "Owner": owner,
                "문장(미리보기)": preview, "줄 수": txt.count("\n") + 1
            })
        if bank_rows:
            st.dataframe(pd.DataFrame(bank_rows), use_container_width=True, hide_index=True)
        else:
            st.caption("아직 등록된 정답이 없습니다.")

        st.stop()

    st.title("🎓 Teacher Dashboard")
    st.caption("Syntax Pitching™ — 수강생 진도 · 타율 · 출석 현황")

    if not client:
        st.error("구글 시트 연결 실패")
        st.stop()
    if not all_students_info:
        st.warning("등록된 학생이 없습니다.")
        st.stop()

    db_df_t = get_data_from_sheet(client)

    # 학생 선택
    t_selected = st.selectbox(
        "학생 선택",
        all_students_info,
        format_func=lambda x: f"{x[1]}  ·  {x[0]}"
    )

    if t_selected:
        t_folder, t_student = t_selected
        t_chapters = get_chapters(t_folder, t_student)

        # 학생 전체 통계
        s_df = db_df_t[(db_df_t['Student'] == t_student) & (db_df_t['Result'].isin(['O', 'X']))] if not db_df_t.empty else pd.DataFrame()
        total_attempts = len(s_df)
        total_O = int((s_df['Result'] == 'O').sum()) if total_attempts else 0
        overall_avg = (total_O / total_attempts * 100) if total_attempts else 0.0
        last_ts = s_df['Timestamp'].max() if total_attempts else None
        last_activity = last_ts[:10] if last_ts else "기록 없음"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 시도", f"{total_attempts}회")
        c2.metric("평균 타율", f"{overall_avg:.1f}%")
        c3.metric("O / X", f"{total_O} / {total_attempts - total_O}")
        c4.metric("마지막 활동", last_activity)

        st.markdown("---")

        tab_ch, tab_img, tab_weak, tab_att = st.tabs(
            ["📊 챕터별 집계", "🖼️ 이미지별 상세", "🎯 약점 TOP 10", "📅 출석 현황"]
        )

        # ── 탭 1: 챕터별 집계 ──
        with tab_ch:
            if not t_chapters:
                st.info("챕터가 없습니다.")
            else:
                ch_rows = []
                for ch_path, ch_name in t_chapters:
                    imgs = get_images(t_folder, t_student, ch_path)
                    img_names = [os.path.basename(p) for p in imgs]
                    ch_df = s_df[s_df['Image'].isin(img_names)] if not s_df.empty else pd.DataFrame()
                    total = len(ch_df)
                    o_cnt = int((ch_df['Result'] == 'O').sum()) if total else 0
                    avg = (o_cnt / total * 100) if total else 0.0

                    # 약점 이미지 개수 (5회 이상 + 타율 60% 이하)
                    weak_cnt = 0
                    for p in imgs:
                        a, recs = calculate_batting_average(db_df_t, t_student, p)
                        if len(recs) >= 5 and a <= 0.6:
                            weak_cnt += 1

                    ch_rows.append({
                        "챕터": ch_name,
                        "이미지 수": len(imgs),
                        "총 시도": total,
                        "평균 타율": f"{avg:.1f}%" if total else "-",
                        "약점(≤60%)": weak_cnt
                    })
                st.dataframe(pd.DataFrame(ch_rows), use_container_width=True, hide_index=True)

        # ── 탭 2: 이미지별 상세 ──
        with tab_img:
            if not t_chapters:
                st.info("챕터가 없습니다.")
            else:
                ch_pick = st.selectbox(
                    "챕터 선택",
                    t_chapters,
                    format_func=lambda x: x[1],
                    key="teacher_ch_pick"
                )
                if ch_pick:
                    imgs = get_images(t_folder, t_student, ch_pick[0])
                    if not imgs:
                        st.info("이미지가 없습니다.")
                    else:
                        rows = []
                        for p in imgs:
                            name = os.path.basename(p)
                            total_img = len(s_df[s_df['Image'] == name]) if not s_df.empty else 0
                            avg, recs = calculate_batting_average(db_df_t, t_student, p)
                            rows.append({
                                "파일명": name,
                                "총 시도": total_img,
                                "최근 5회 타율": f"{avg*100:.0f}%" if recs else "-",
                                "최근 기록": " ".join(recs) if recs else "-"
                            })
                        rows.sort(key=lambda r: (r["총 시도"] == 0, r["최근 5회 타율"]))
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # ── 탭 3: 약점 TOP 10 ──
        with tab_weak:
            weak = []
            for ch_path, ch_name in t_chapters:
                for p in get_images(t_folder, t_student, ch_path):
                    avg, recs = calculate_batting_average(db_df_t, t_student, p)
                    if len(recs) >= 5:
                        weak.append({
                            "챕터": ch_name,
                            "파일명": os.path.basename(p),
                            "_avg": avg,
                            "타율": f"{avg*100:.0f}%",
                            "최근 기록": " ".join(recs)
                        })
            weak.sort(key=lambda x: x["_avg"])
            top10 = weak[:10]
            if top10:
                df_w = pd.DataFrame(top10).drop(columns=["_avg"])
                st.dataframe(df_w, use_container_width=True, hide_index=True)
                st.caption("※ 5회 이상 출제된 이미지만 포함 (타율 신뢰도 확보)")
            else:
                st.info("5회 이상 출제된 이미지가 없어 약점 분석이 불가능합니다. 데이터가 더 쌓이면 자동으로 표시됩니다.")

        # ── 탭 4: 출석 현황 ──
        with tab_att:
            today = get_kst_now()
            cc1, cc2 = st.columns([1, 1])
            with cc1:
                t_year = st.selectbox("연도", [today.year, today.year - 1], index=0)
            with cc2:
                t_month = st.selectbox("월", list(range(1, 13)), index=today.month - 1)

            attended = get_attendance(client, t_student, t_year, t_month)
            st.markdown(f"#### {t_year}년 {t_month}월 · 출석 {len(attended)}일")

            calendar.setfirstweekday(calendar.SUNDAY)
            cal_matrix = calendar.monthcalendar(t_year, t_month)
            header = ['일', '월', '화', '수', '목', '금', '토']
            h_cols = st.columns(7)
            for i, h in enumerate(header):
                color = "#E74C3C" if i == 0 else "#3498DB" if i == 6 else "#888"
                h_cols[i].markdown(
                    f"<div style='text-align:center;color:{color};font-weight:600;font-size:13px;padding:6px 0;'>{h}</div>",
                    unsafe_allow_html=True
                )
            for week in cal_matrix:
                w_cols = st.columns(7)
                for i, day in enumerate(week):
                    if day == 0:
                        w_cols[i].markdown("&nbsp;", unsafe_allow_html=True)
                    elif day in attended:
                        is_today = (day == today.day and t_month == today.month and t_year == today.year)
                        bg = "#E74C3C" if is_today else "#4CAF50"
                        w_cols[i].markdown(
                            f"<div style='text-align:center;background:{bg};color:white;"
                            f"border-radius:6px;padding:10px 0;font-weight:700;'>{day}</div>",
                            unsafe_allow_html=True
                        )
                    else:
                        w_cols[i].markdown(
                            f"<div style='text-align:center;padding:10px 0;color:#999;'>{day}</div>",
                            unsafe_allow_html=True
                        )

    st.markdown('<div class="footer-text">© Teacher Dashboard · Syntax Pitching™</div>', unsafe_allow_html=True)
    st.stop()

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
            
            curr_imgs = get_daily_target_images(folder_name, student_name, "현행 챕터", 6, db_df)
            curr_shortfall = 6 - len(curr_imgs)  # 현행 부족분 → 지난에서 보충

            past_target = 4 + curr_shortfall
            past_imgs = get_daily_target_images(folder_name, student_name, "지난 챕터", past_target, db_df)
            past_shortfall = past_target - len(past_imgs)  # 지난도 부족하면 → 현행에서 추가 보충

            if past_shortfall > 0:
                curr_imgs = get_daily_target_images(folder_name, student_name, "현행 챕터", 6 + past_shortfall, db_df)
            
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

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
# [정답 시트 v2] AnswerBank · ImageMatching
# ──────────────────────────────────────────
# AnswerBank   : (Chapter, Section, Owner) → Sentences  (선생님이 입력)
# ImageMatching: (ImageStudent, Chapter, Image) → ContentOwner (학생이 매칭)
# 오디오 파일  : audio/{Chapter}/{Section}_{Owner}.mp3 (generate_tts.py 로 생성)
# ==========================================
ANSWER_BANK_HEADER = ["Chapter", "Section", "Owner", "Sentences", "Updated"]
IMAGE_MATCHING_HEADER = ["ImageStudent", "Chapter", "Image", "ContentOwner", "Updated"]

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

def render_audio_player(audio_abs_path, label="🔊 정답 듣기"):
    """mp3 파일을 base64 임베드해서 단일 탭 재생 버튼으로 렌더링."""
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
    html = f"""
    <div style="margin:0;font-family:-apple-system,system-ui,'Noto Sans KR',sans-serif;">
      <audio id="aud_{uid}" src="data:audio/mp3;base64,{audio_b64}" preload="auto"></audio>
      <button id="btn_{uid}"
        style="background:#2980B9;color:white;border:none;border-radius:8px;
               padding:10px 16px;font-size:15px;font-weight:600;cursor:pointer;
               width:100%;user-select:none;-webkit-user-select:none;">
        {label}
      </button>
      <script>
        (function(){{
          var aud = document.getElementById('aud_{uid}');
          var btn = document.getElementById('btn_{uid}');
          function play() {{
            try {{
              aud.pause();
              aud.currentTime = 0;
              aud.play();
            }} catch (e) {{ console.error('audio play err', e); }}
          }}
          if (btn) {{
            btn.addEventListener('click', play);
            btn.addEventListener('touchstart', function(e){{ e.preventDefault(); play(); }}, {{passive:false}});
          }}
        }})();
      </script>
    </div>
    """
    components.html(html, height=60, scrolling=False)


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
            st.toast(f"✅ '{sel}' 으로 매칭 저장됨")
            st.rerun()
        else:
            st.error("매칭 저장 실패 — 잠시 후 다시 시도해 주세요.")


def render_image_answer_widget(image_path, image_student, chapter, all_students, answer_bank, image_matchings, client, key_suffix=""):
    """이미지 아래에 표시되는 위젯.
    매칭된 경우: 🔊 정답 듣기 (음원 있을 때) + '그림 매칭 수정' 작은 버튼
    매칭 안된 경우: 표시 안 함 (위쪽 picker 가 처리)
    음원이 아직 없는 경우: 등록된 텍스트가 있으면 fallback 으로 reveal 버튼 노출."""
    image_filename = os.path.basename(image_path)
    chapter_str = str(chapter)
    key = (image_student, chapter_str, image_filename)
    content_owner = image_matchings.get(key)

    if not content_owner:
        return  # 매칭 안됨 → picker 가 위에서 처리

    section = extract_section_from_filename(image_filename)
    sentences = ""
    audio_abs = None
    if section:
        sentences = answer_bank.get((chapter_str, section, content_owner), "")
        audio_abs = get_audio_absolute_path(chapter_str, section, content_owner)
    audio_exists = bool(audio_abs and os.path.exists(audio_abs))

    if audio_exists:
        render_audio_player(audio_abs)
    elif sentences:
        # 음원 준비되기 전까지는 텍스트 reveal 폴백 제공
        render_answer_reveal(sentences, reveal_label="🔒 정답 보기 (꾹 누르기)", speak_label="🔊 정답 듣기 (브라우저 TTS)")
        st.caption("※ 고품질 음원 준비 중 — 텍스트로 임시 제공")
    else:
        st.caption(f"⚪ 정답 미등록 ({content_owner}의 구간 {section}) — 선생님께 등록 요청")

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
    TOTAL_WIDTH = 1140 
    TARGET_HEIGHT = 120   
    CELL_HEADER_H = 30    
    CELL_H = TARGET_HEIGHT + CELL_HEADER_H 
    HEADER_HEIGHT = 90
    CENTER_X = TOTAL_WIDTH // 2  
    
    try:
        font_title = ImageFont.truetype(FONT_PATH, 48)
        font_cal = ImageFont.truetype(FONT_PATH, 24)
        font_overall = ImageFont.truetype(FONT_PATH, 30) 
        font_q = ImageFont.truetype(FONT_PATH, 42) 
        font_info = ImageFont.truetype(FONT_PATH, 24) 
    except:
        font_title = font_cal = font_overall = font_q = font_info = ImageFont.load_default()

    overall_counts = {}
    if not db_df.empty:
        student_df = db_df[(db_df['Student'] == student_name) & (db_df['Result'].isin(['O', 'X']))]
        for ch, group in student_df.groupby('Chapter'):
            ch_str = str(ch) 
            if ch_str == 'Attendance': continue
            o_count = (group['Result'] == 'O').sum()
            total = len(group)
            overall_counts[ch_str] = {'o': o_count, 'tot': total}
            
    for r in results_list:
        ch_str = str(os.path.basename(os.path.dirname(r['file'])))
        res = r['result']
        if ch_str not in overall_counts:
            overall_counts[ch_str] = {'o': 0, 'tot': 0}
        overall_counts[ch_str]['tot'] += 1
        if res == 'O':
            overall_counts[ch_str]['o'] += 1

    overall_stats = {ch: int((data['o'] / data['tot']) * 100) for ch, data in overall_counts.items() if data['tot'] > 0}
    sorted_chs = sorted(overall_stats.keys())

    max_col_w = CENTER_X - 30  
    row_data = []
    
    for r in results_list:
        p = r['file']
        res = r['result'] 
        try:
            img = Image.open(p).convert("RGBA")
            scale = TARGET_HEIGHT / img.size[1]
            new_w = int(img.size[0] * scale)
            
            if new_w > max_col_w:
                img = img.resize((max_col_w, TARGET_HEIGHT), resample=Image.LANCZOS)
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
            
            row_data.append({
                'img': bg, 'label': label, 'hist': hist
            })
        except: continue
    
    calendar.setfirstweekday(calendar.SUNDAY)
    cal_matrix = calendar.monthcalendar(current_year, current_month)
    cal_row_height = 45 
    CALENDAR_HEIGHT = cal_row_height + (len(cal_matrix) * cal_row_height) + 15 
    
    overall_stat_rows = ((len(sorted_chs) - 1) // 2) + 1 if sorted_chs else 0
    OVERALL_HEIGHT = max(CALENDAR_HEIGHT, 50 + overall_stat_rows * 45) 

    grid_rows = (len(row_data) + 1) // 2
    GRID_HEIGHT = grid_rows * CELL_H

    q_lines = []
    q_height = 0
    if question_text:
        wrapped = textwrap.fill(question_text, width=60) 
        q_lines = wrapped.split('\n')
        q_height = len(q_lines) * 60 + 50 

    TOTAL_HEIGHT = HEADER_HEIGHT + OVERALL_HEIGHT + GRID_HEIGHT + q_height

    final_image = Image.new("RGB", (TOTAL_WIDTH, TOTAL_HEIGHT), "white")
    draw = ImageDraw.Draw(final_image)
    
    # [헤더]
    today = get_kst_now()
    today_display = today.strftime('%m/%d').lstrip("0").replace("/0", "/")
    # 제목에 숙제 완료 및 체크 마크 추가
    title_text = f"{student_name} {today_display} 숙제 완료 ✔"
    draw.text((30, 22), title_text, fill="black", font=font_title)

    # [달력 - 좌측]
    cal_start_y = HEADER_HEIGHT
    days_header = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
    cal_width = CENTER_X - 30 
    col_spacing = cal_width / 7.0
    
    for i, day_str in enumerate(days_header):
        tw = draw.textlength(day_str, font=font_cal)
        dx = 30 + i * col_spacing + (col_spacing - tw) / 2
        draw.text((dx, cal_start_y), day_str, fill="#95A5A6", font=font_cal)
        
    cal_y = cal_start_y + cal_row_height
    for week in cal_matrix:
        for i, day in enumerate(week):
            if day != 0:
                dx = 30 + i * col_spacing
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

    # [종합 타율 - 우측 2열]
    stat_start_x = CENTER_X + 30
    stat_start_y = HEADER_HEIGHT
    
    draw.text((stat_start_x, stat_start_y), "Batting Average", fill="#95A5A6", font=font_overall)
    
    stat_data_y = stat_start_y + 50
    for idx, ch in enumerate(sorted_chs):
        col = idx % 2 
        row = idx // 2
        x = stat_start_x + col * 240 
        y = stat_data_y + row * 45 
        
        pct = overall_stats[ch]
        pct_color = "#E74C3C" if pct <= 20 else "#F39C12" if pct <= 60 else "black"
        
        ch_text = str(ch)
        tw = draw.textlength(ch_text, font=font_overall)
        draw.text((x, y), ch_text, fill="#95A5A6", font=font_overall)
        draw.text((x + tw + 15, y), f"{pct}%", fill=pct_color, font=font_overall)

    # [그리드 이미지 렌더링]
    grid_y_start = HEADER_HEIGHT + OVERALL_HEIGHT 
    
    for i, item in enumerate(row_data):
        r = i // 2
        c = i % 2
        x_off = 30 if c == 0 else CENTER_X
        y_off = grid_y_start + r * CELL_H
        
        badge_text = str(item['label'])
        
        # [수정] 텍스트가 위로 너무 붙어보이는 현상 교정: y_off - 3 에서 y_off - 2로 1픽셀 하강
        text_y_align = y_off - 2
        
        # 1) 배지(챕터 번호) 그리기
        bg_rgba = get_label_bg_rgba(badge_text)
        bw = draw.textlength(badge_text, font=font_info) + 16
        draw.rectangle([x_off, y_off, x_off + bw, y_off + CELL_HEADER_H], fill=bg_rgba)
        draw.text((x_off + 8, text_y_align), badge_text, fill="white", font=font_info)
        
        # 2) O/X 히스토리 그리기 (구간 타율 삭제, 배지 바로 옆 15px 여백 후 밀착)
        hist_start_x = x_off + bw + 15
        hist_list = item['hist']
        current_x = hist_start_x
        
        for idx_h, char in enumerate(hist_list):
            is_last_item = (idx_h == len(hist_list) - 1)
            char_color = "#E74C3C" if (is_last_item and char == 'X') else "#95A5A6"
            
            draw.text((current_x, text_y_align), char, fill=char_color, font=font_info)
            current_x += draw.textlength(char, font=font_info) + 6

        # 3) 이미지 붙여넣기 
        final_image.paste(item['img'], (x_off, y_off + CELL_HEADER_H))

    # [질문 렌더링]
    y_offset = grid_y_start + GRID_HEIGHT
    if question_text:
        text_y = y_offset + 15 
        for line in q_lines:
            draw.text((30, text_y), line, fill="black", font=font_q)
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

        # 각 변형(basic/advanced)별로 구간과 샘플 이미지 추출
        # 우선순위: 해당 학생 본인 폴더 → 없으면 다른 학생들 폴더의 합집합 (등록 누락 방지)
        def collect_sections_for_variant(ch_name):
            """{section: sample_image_path} 반환. 학생 본인 폴더 우선, 없으면 다른 학생들 폴더 합집합."""
            if not ch_name:
                return {}
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
            # 본인 폴더가 있으면 본인 것만 사용, 없으면 다른 학생들 합집합
            return own_sections if own_sections else other_sections

        advanced_sections = collect_sections_for_variant(ch_advanced)
        basic_sections = collect_sections_for_variant(ch_basic)

        adv_sorted = sorted(advanced_sections.keys(), key=lambda x: int(x) if x.isdigit() else 0)
        bas_sorted = sorted(basic_sections.keys(), key=lambda x: int(x) if x.isdigit() else 0)

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
                    st.session_state.pop('answer_bank', None)
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
                st.session_state.pop('answer_bank', None)
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

        # 정답 데이터 로드 (세션 캐시)
        if 'answer_bank' not in st.session_state:
            st.session_state['answer_bank'] = load_answer_bank(client) if client else {}
        if 'image_matchings' not in st.session_state:
            st.session_state['image_matchings'] = load_image_matchings(client) if client else {}
        if 'all_student_names' not in st.session_state:
            st.session_state['all_student_names'] = get_all_student_names()

        # 매칭 안된 그림이면 이미지 위에 picker 노출
        render_match_picker(
            current_img_path,
            st.session_state['student_name'],
            current_chapter,
            st.session_state['all_student_names'],
            st.session_state['image_matchings'],
            client,
            key_suffix="play",
        )

        display_responsive_image(current_img_path, is_grid=False)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🙅 미통과", key='fail', use_container_width=True):
                if not is_practice and client: save_to_sheet(client, st.session_state['student_name'], current_chapter, os.path.basename(current_img_path), "X")
                st.session_state['results'].append({'file': current_img_path, 'result': 'X'})
                st.session_state['current_index'] += 1
                st.rerun()
        with col2:
            if st.button("🙆 통과", key='pass', use_container_width=True):
                if not is_practice and client: save_to_sheet(client, st.session_state['student_name'], current_chapter, os.path.basename(current_img_path), "O")
                st.session_state['results'].append({'file': current_img_path, 'result': 'O'})
                st.session_state['current_index'] += 1
                st.rerun()

        # 매칭된 경우: 🔊 정답 듣기 + 매칭 수정 (이미지 아래)
        render_image_answer_widget(
            current_img_path,
            st.session_state['student_name'],
            current_chapter,
            st.session_state['all_student_names'],
            st.session_state['answer_bank'],
            st.session_state['image_matchings'],
            client,
            key_suffix="play",
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
                _ans_bank = st.session_state.get('answer_bank') or (load_answer_bank(client) if client else {})
                _img_match = st.session_state.get('image_matchings') or (load_image_matchings(client) if client else {})
                _all_names = st.session_state.get('all_student_names') or get_all_student_names()
                st.markdown("#### 📋 라운드 복기")
                r_cols = st.columns(2)
                for _ri, _r in enumerate(results):
                    with r_cols[_ri % 2]:
                        _fname = os.path.basename(_r['file'])
                        _chapter = os.path.basename(os.path.dirname(_r['file']))
                        _mark = "🟢 O" if _r['result'] == 'O' else "🔴 X"
                        st.markdown(f"**{_mark}** · `{_fname}`")
                        display_responsive_image(_r['file'], is_grid=True)
                        render_match_picker(
                            _r['file'], st.session_state['student_name'], _chapter,
                            _all_names, _img_match, client, key_suffix=f"result_{_ri}"
                        )
                        render_image_answer_widget(
                            _r['file'], st.session_state['student_name'], _chapter,
                            _all_names, _ans_bank, _img_match, client, key_suffix=f"result_{_ri}"
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
        _ans_bank_d = st.session_state.get('answer_bank') or (load_answer_bank(client) if client else {})
        _img_match_d = st.session_state.get('image_matchings') or (load_image_matchings(client) if client else {})
        _all_names_d = st.session_state.get('all_student_names') or get_all_student_names()
        d_cols = st.columns(2)
        for _di, _dr in enumerate(results):
            with d_cols[_di % 2]:
                _dfname = os.path.basename(_dr['file'])
                _dchapter = os.path.basename(os.path.dirname(_dr['file']))
                _dmark = "🟢 O" if _dr['result'] == 'O' else "🔴 X"
                st.markdown(f"**{_dmark}** · `{_dfname}`")
                display_responsive_image(_dr['file'], is_grid=True)
                render_match_picker(
                    _dr['file'], st.session_state['student_name'], _dchapter,
                    _all_names_d, _img_match_d, client, key_suffix=f"daily_{_di}"
                )
                render_image_answer_widget(
                    _dr['file'], st.session_state['student_name'], _dchapter,
                    _all_names_d, _ans_bank_d, _img_match_d, client, key_suffix=f"daily_{_di}"
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

    # 새 정답 시스템 데이터 로드
    answer_bank_rec = load_answer_bank(client) if client else {}
    img_match_rec = load_image_matchings(client) if client else {}
    all_names_rec = get_all_student_names()

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
                render_match_picker(
                    img_path, st.session_state['student_name'], ch_name_rec,
                    all_names_rec, img_match_rec, client, key_suffix=f"rec_{i}"
                )
                render_image_answer_widget(
                    img_path, st.session_state['student_name'], ch_name_rec,
                    all_names_rec, answer_bank_rec, img_match_rec, client, key_suffix=f"rec_{i}"
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

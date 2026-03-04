import streamlit as st
import os
import random
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

# [NEW] 학생의 모든 챕터 누적 타율 계산 함수
def get_overall_stats(db_df, student_name):
    if db_df.empty: return {}
    df = db_df[(db_df['Student'] == student_name) & (db_df['Chapter'] != 'Attendance')]
    stats = {}
    for ch in df['Chapter'].unique():
        cdf = df[df['Chapter'] == ch]
        total = len(cdf)
        if total > 0:
            stats[ch] = int((len(cdf[cdf['Result'] == 'O']) / total) * 100)
    return dict(sorted(stats.items()))

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
    if not db_df.empty:
        student_data = db_df[db_df['Student'] == student_name]
        counts = student_data['Image'].value_counts().to_dict()
        
    def get_count(img_path): return counts.get(os.path.basename(img_path), 0)
    random.shuffle(all_imgs) 
    all_imgs.sort(key=get_count) 
    return all_imgs[:n]

# ==========================================
# [로직] 결과 인증 이미지 생성 (극강의 실속 레이아웃)
# ==========================================
def get_label_bg_rgba(label_text: str):
    if label_text.startswith('1'): return (214, 82, 75, 230) 
    if label_text.endswith('S'): return (199, 142, 43, 230) 
    return (62, 129, 97, 230) 

def create_summary_image_base64(student_name, results_list, db_df, question_text, current_year, current_month, attended_days):
    TOTAL_WIDTH = 760
    TARGET_HEIGHT = 80 # 이미지 높이 80px 압축
    HEADER_HEIGHT = 60
    COL_W = TOTAL_WIDTH // 2 # 열당 380px 꽉 채움 (여백 0)
    
    try:
        font_title = ImageFont.truetype(FONT_PATH, 32)
        font_cal_title = ImageFont.truetype(FONT_PATH, 20)
        font_cal = ImageFont.truetype(FONT_PATH, 16)
        font_stat_pct = ImageFont.truetype(FONT_PATH, 15) 
        font_stat_hist = ImageFont.truetype(FONT_PATH, 14)
        font_label = ImageFont.truetype(FONT_PATH, 13)
        font_q = ImageFont.truetype(FONT_PATH, 28) 
    except:
        font_title = font_cal_title = font_cal = font_stat_pct = font_stat_hist = font_label = font_q = ImageFont.load_default()

    row_data = []
    for r in results_list:
        p = r['file']
        res = r['result']
        _, hist = calculate_batting_average(db_df, student_name, p)
        hist.append(res)
        hist = hist[-5:] 
        avg = hist.count('O') / len(hist)
        
        try:
            img = Image.open(p).convert("RGBA")
            # 비율 유지하며 리사이즈 (COL_W 넘어가면 컷팅 안되게 스케일 조정)
            scale = min(TARGET_HEIGHT / img.size[1], COL_W / img.size[0])
            new_w = int(img.size[0] * scale)
            new_h = int(img.size[1] * scale)
            img = img.resize((new_w, new_h), resample=Image.LANCZOS)
            
            # 셀 공간 전체를 흰색으로 채우고 이미지는 가운데 정렬
            bg = Image.new("RGBA", (COL_W, TARGET_HEIGHT), "WHITE")
            bg.paste(img, ((COL_W - new_w)//2, (TARGET_HEIGHT - new_h)//2), img)
            
            label = os.path.basename(os.path.dirname(p))
            row_data.append({
                'img': bg.convert("RGB"), 'label': label, 
                'res': res, 'avg': avg, 'hist': hist
            })
        except: continue
    
    # 1. 달력 및 종합 타율 공간 계산
    calendar.setfirstweekday(calendar.SUNDAY)
    cal_matrix = calendar.monthcalendar(current_year, current_month)
    row_height = 35
    CALENDAR_HEIGHT = row_height + (len(cal_matrix) * row_height) + 30 

    # 2. 이미지 2열 분할 높이 계산
    grid_rows = (len(row_data) + 1) // 2
    GRID_HEIGHT = grid_rows * TARGET_HEIGHT

    # 3. 질문 박스 높이
    q_lines = []
    q_height = 0
    if question_text:
        wrapped = textwrap.fill(question_text, width=60) 
        q_lines = wrapped.split('\n')
        q_height = len(q_lines) * 40 + 20 

    TOTAL_HEIGHT = HEADER_HEIGHT + CALENDAR_HEIGHT + GRID_HEIGHT + q_height

    final_image = Image.new("RGB", (TOTAL_WIDTH, TOTAL_HEIGHT), "white")
    draw = ImageDraw.Draw(final_image)
    
    # [헤더]
    today = get_kst_now()
    today_display = today.strftime('%m/%d').lstrip("0").replace("/0", "/")
    title_text = f"{student_name} {today_display} 숙제 완료"
    draw.text((20, 15), title_text, fill="black", font=font_title)

    # [좌측: 달력 원상복구 (작게)]
    cal_start_y = HEADER_HEIGHT
    days_header = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
    cal_width = 320 # 달력 가로 사이즈 축소
    col_spacing = cal_width / 7.0
    
    for i, day_str in enumerate(days_header):
        tb = draw.textbbox((0, 0), day_str, font=font_cal)
        tw = tb[2] - tb[0]
        dx = 20 + i * col_spacing + (col_spacing - tw) / 2
        draw.text((dx, cal_start_y + 10), day_str, fill="#95A5A6", font=font_cal)
        
    cal_y = cal_start_y + row_height
    for week in cal_matrix:
        for i, day in enumerate(week):
            if day != 0:
                dx = 20 + i * col_spacing
                dy = cal_y

                day_str = str(day)
                tb = draw.textbbox((0, 0), day_str, font=font_cal)
                tw = tb[2] - tb[0]
                th = tb[3] - tb[1]
                txt_x = dx + (col_spacing - tw) / 2
                txt_y = dy + (row_height - th) / 2 - 2

                if day in attended_days:
                    draw.rectangle([dx+2, dy+2, dx + col_spacing - 2, dy + row_height - 2], fill="#555555")
                    draw.text((txt_x, txt_y), day_str, fill="white", font=font_cal)
                else:
                    draw.text((txt_x, txt_y), day_str, fill="black", font=font_cal)
        cal_y += row_height

    # [우측: 전체 챕터 종합 타율 대시보드]
    overall_stats = get_overall_stats(db_df, student_name)
    stat_start_x = 380
    draw.text((stat_start_x, cal_start_y + 5), "누적 챕터별 타율", fill="#34495E", font=font_cal_title)
    
    stat_y = cal_start_y + 40
    for i, (ch, pct) in enumerate(overall_stats.items()):
        # 챕터 개수가 많을 것을 대비해 우측 공간 내에서 2열 배치
        cx = stat_start_x if i % 2 == 0 else stat_start_x + 160
        cy = stat_y + (i // 2) * 30
        draw.text((cx, cy), f"{ch}:", fill="#7F8C8D", font=font_cal)
        
        pct_color = "#E74C3C" if pct <= 20 else "#F39C12" if pct <= 60 else "black"
        draw.text((cx + 50, cy), f"{pct}%", fill=pct_color, font=font_cal)

    # [하단: 여백 0, 구분선 0의 정중앙 분할 2열 이미지 그리드]
    grid_y_start = cal_y + 15
    
    for i, item in enumerate(row_data):
        r = i // 2
        c = i % 2
        x_off = c * COL_W # 여백 0으로 딱 붙임
        y_off = grid_y_start + r * TARGET_HEIGHT
        
        avg_pct = int(item['avg'] * 100)
        pct_color = "#E74C3C" if avg_pct <= 20 else "#E67E22" if avg_pct <= 60 else "black"
        hist_str = " ".join(item['hist'])
        
        # 이미지 전체를 칸에 맞게 붙여넣기
        final_image.paste(item['img'], (x_off, y_off))
        
        # [스마트 오버레이 뱃지] 좌측 상단 반투명 스트립
        badge_h = 24
        bg_rgba = get_label_bg_rgba(str(item['label']))
        
        # 전체 스트립 배경 (반투명 흰색)
        draw.rectangle([x_off, y_off, x_off + 175, y_off + badge_h], fill=(255, 255, 255, 230))
        
        # 챕터명 색상 박스
        tb_label = draw.textbbox((0, 0), str(item['label']), font=font_label)
        label_w = tb_label[2] - tb_label[0]
        draw_rect = ImageDraw.Draw(final_image, "RGBA")
        draw_rect.rectangle((x_off, y_off, x_off + label_w + 10, y_off + badge_h), fill=bg_rgba)
        draw_rect.text((x_off + 5, y_off + 4), str(item['label']), fill="white", font=font_label)
        
        # 타율 텍스트 오버레이
        stat_x = x_off + label_w + 16
        draw.text((stat_x, y_off + 3), f"{avg_pct}%", fill=pct_color, font=font_stat_pct)
        draw.text((stat_x + 40, y_off + 4), hist_str, fill="#95A5A6", font=font_stat_hist)

    # [질문 렌더링]
    y_offset = grid_y_start + GRID_HEIGHT
    if question_text:
        q_y_start = y_offset + 10 
        text_y = q_y_start
        for line in q_lines:
            draw.text((20, text_y), line, fill="black", font=font_q)
            text_y += 40

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
            selected_chapters = st.sidebar.multiselect("챕터 선택 (일반 연습용)", chapter_list, format_func=lambda x: x[1])
            
            if st.sidebar.button("훈련 시작 (Start)", use_container_width=True) and selected_chapters:
                all_images = []
                for ch_path, ch_name in selected_chapters:
                    all_images.extend(get_images(folder_name, student_name, ch_path))
                random.shuffle(all_images)
                st.session_state.update({
                    'folder_name': folder_name, 'student_name': student_name, 'selected_chapters': selected_chapters, 
                    'original_playlist': all_images.copy(), 'playlist': all_images, 'current_index': 0, 'results': [], 
                    'is_practice_mode': False, 'mode': 'playing', 'is_daily': False
                })
                if client: st.session_state['db_data'] = get_data_from_sheet(client)
                st.rerun()

            if st.sidebar.button("피칭 기록 보기", use_container_width=True) and selected_chapters:
                st.session_state.update({'folder_name': folder_name, 'student_name': student_name, 'selected_chapters': selected_chapters, 'mode': 'records'})
                if client: st.session_state['db_data'] = get_data_from_sheet(client)
                st.rerun()

# ==========================================
# [화면] 메인 로직
# ==========================================
if 'mode' not in st.session_state: st.session_state['mode'] = 'setup'

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
            past_imgs = get_daily_target_images(folder_name, student_name, "지난 챕터", 4, db_df)
            
            daily_playlist = curr_imgs + past_imgs
            random.shuffle(daily_playlist)
            
            if daily_playlist:
                st.session_state.update({
                    'folder_name': folder_name, 'student_name': student_name, 
                    'original_playlist': daily_playlist.copy(), 'playlist': daily_playlist, 
                    'current_index': 0, 'results': [], 'is_practice_mode': False, 
                    'mode': 'daily_playing', 'is_daily': True
                })
                st.rerun()
            else:
                st.warning("출제할 이미지가 없습니다. 폴더 구성을 확인해 주세요.")
        
        st.write("") 
        st.markdown("👈 특정 챕터만 골라서 연습하려면 왼쪽에서 챕터를 선택하세요.")
    else:
        st.markdown("### 👈 왼쪽 사이드바에서 수강생을 선택해주세요.")
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
            st.session_state['mode'] = 'daily_result' if is_daily else 'setup'
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
    st.markdown(f'<img src="data:image/jpeg;base64,{b64_img}" style="width:100%; max-width:600px; border-radius:8px;">', unsafe_allow_html=True)

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
        
    if all_imgs and 'db_data' in st.session_state:
        cols = st.columns(3)
        for i, img_path in enumerate(all_imgs):
            with cols[i % 3]:
                display_responsive_image(img_path, is_grid=True)
                avg, history = calculate_batting_average(st.session_state['db_data'], st.session_state['student_name'], img_path)
                color = "green" if avg >= 0.8 else "orange" if avg >= 0.5 else "red"
                hist_str = " ".join([f"{h}" for h in history])
                st.caption(f"타율: :{color}[{avg*100:.0f}%] | {hist_str}")

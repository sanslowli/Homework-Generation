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
# [로직] 결과 인증 이미지 생성 (흑백 필터 & 초밀착 대칭 레이아웃)
# ==========================================
def get_label_bg_rgba(label_text: str):
    if label_text.startswith('1'): return (214, 82, 75, 180) 
    if label_text.endswith('S'): return (199, 142, 43, 180) 
    return (62, 129, 97, 180) 

def create_summary_image_base64(student_name, results_list, db_df, question_text, current_year, current_month, attended_days):
    TOTAL_WIDTH = 1140 
    TARGET_HEIGHT = 120   
    CELL_HEADER_H = 30    # (개선) 정보줄 높이를 36에서 30으로 압축하여 위아래 여백 최소화
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
        res = r['result'] # 현재 결과가 X인지 확인용
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
            
            # (개선) 틀린(X) 이미지는 흑백(Grayscale) 처리! 흰 바탕은 그대로 흰색 유지
            if res == 'X':
                bg = bg.convert("L").convert("RGB")
            
            label = os.path.basename(os.path.dirname(p))
            _, hist = calculate_batting_average(db_df, student_name, p)
            hist.append(res)
            hist = hist[-5:] 
            avg = hist.count('O') / len(hist)
            
            row_data.append({
                'img': bg, 'label': label, 
                'avg': avg, 'hist': hist
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
    title_text = f"{student_name} {today_display} 숙제 완료"
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

    # [그리드 이미지 렌더링 - 챕터/타율/OX 정보줄 포함]
    grid_y_start = HEADER_HEIGHT + OVERALL_HEIGHT 
    
    for i, item in enumerate(row_data):
        r = i // 2
        c = i % 2
        x_off = 30 if c == 0 else CENTER_X
        y_off = grid_y_start + r * CELL_H
        
        badge_text = str(item['label'])
        avg_pct = int(item['avg'] * 100)
        
        # 1) 배지(챕터 번호) 그리기 (높이 30px 적용, y_off+1 로 상하 정중앙 밸런스 완벽 교정)
        bg_rgba = get_label_bg_rgba(badge_text)
        bw = draw.textlength(badge_text, font=font_info) + 16
        draw.rectangle([x_off, y_off, x_off + bw, y_off + CELL_HEADER_H], fill=bg_rgba)
        draw.text((x_off + 8, y_off + 1), badge_text, fill="white", font=font_info)
        
        # 2) 타율 (%) 그리기
        pct_str = f"{avg_pct}%"
        pct_w = draw.textlength(pct_str, font=font_info)
        draw.text((x_off + bw + 15, y_off + 3), pct_str, fill="#95A5A6", font=font_info)
        
        # 3) O/X 히스토리 그리기 
        hist_start_x = x_off + bw + 15 + pct_w + 20
        hist_list = item['hist']
        current_x = hist_start_x
        
        for idx_h, char in enumerate(hist_list):
            is_last_item = (idx_h == len(hist_list) - 1)
            # 마지막 글자가 X일 때만 붉은색, 나머지는 연회색
            char_color = "#E74C3C" if (is_last_item and char == 'X') else "#95A5A6"
            
            draw.text((current_x, y_off + 3), char, fill=char_color, font=font_info)
            current_x += draw.textlength(char, font=font_info) + 6

        # 4) 이미지 붙여넣기 (정보줄 30px 바로 아래 밀착, 틈 0)
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
        # [MODIFIED] 연습 모드 끝에 도달하면 무한 반복 (리셔플 & 0번 인덱스 리셋)
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

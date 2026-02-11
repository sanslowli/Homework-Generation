import streamlit as st
import os
import random
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pandas as pd
from PIL import Image

# ==========================================
# [설정] 기본 경로 및 구글 시트
# ==========================================
st.set_page_config(page_title="Syntax Pitching™", layout="wide")

# [수정] 아이콘 폰트 깨짐 방지를 위해 CSS 적용 대상 축소
st.markdown("""
    <style>
        /* span, label 등 아이콘에 영향을 주는 태그 제외 */
        .stApp, .stMarkdown, p, h1, h2, h3, h4, div[data-testid="stMarkdownContainer"] {
            font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans KR", sans-serif !important;
        }
        .stApp { background-color: #F0F2F6; }
        [data-testid="stSidebar"] { background-color: #E0E2E6; }
        .stButton>button { border-radius: 8px; font-weight: 500; }
    </style>
    """, unsafe_allow_html=True)

BASE_FOLDER = os.path.dirname(os.path.abspath(__file__))
TARGET_FOLDERS = ["Syntax Pitching", "Syntax Only", "Syntax + Open-ended Question"]
ALLOWED_SUBFOLDERS = ["현행 챕터", "지난 챕터"]
SHEET_NAME = "Syntax Pitching DB"

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
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, student, chapter, image, result])
        st.cache_data.clear() 
    except Exception as e:
        st.error(f"데이터 저장 실패: {e}")

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

# ==========================================
# [화면] 사이드바
# ==========================================
client = init_connection()
st.sidebar.title("Syntax Pitching™")

query_params = st.query_params
url_student = query_params.get("student")

all_students_info = get_all_students()
selected_data = None

if all_students_info:
    if url_student:
        match = [s for s in all_students_info if s[1] == url_student]
        if match:
            selected_data = match[0]
            st.sidebar.success(f"수강생: {url_student}")
        else:
            st.sidebar.error(f"'{url_student}' 미등록")
            selected_data = st.sidebar.selectbox("수강생 선택", all_students_info, format_func=lambda x: x[1])
    else:
        selected_data = st.sidebar.selectbox("수강생 선택", all_students_info, format_func=lambda x: x[1])

    if selected_data:
        folder_name, student_name = selected_data
        chapter_list = get_chapters(folder_name, student_name)
        if chapter_list:
            selected_chapter_data = st.sidebar.selectbox("챕터 선택", chapter_list, format_func=lambda x: x[1])
            
            if st.sidebar.button("훈련 시작 (Start)", use_container_width=True):
                st.session_state.update({
                    'folder_name': folder_name, 'student_name': student_name,
                    'chapter_path': selected_chapter_data[0], 'chapter_name': selected_chapter_data[1],
                    'original_playlist': get_images(folder_name, student_name, selected_chapter_data[0]),
                    'playlist': random.sample(get_images(folder_name, student_name, selected_chapter_data[0]), len(get_images(folder_name, student_name, selected_chapter_data[0]))),
                    'current_index': 0, 'results': [], 'is_practice_mode': False, 'mode': 'playing'
                })
                if client: st.session_state['db_data'] = get_data_from_sheet(client)
                st.rerun()

            if st.sidebar.button("피칭 기록 보기", use_container_width=True):
                st.session_state.update({
                    'folder_name': folder_name, 'student_name': student_name,
                    'chapter_path': selected_chapter_data[0], 'chapter_name': selected_chapter_data[1],
                    'mode': 'records'
                })
                if client: st.session_state['db_data'] = get_data_from_sheet(client)
                st.rerun()

# ==========================================
# [화면] 메인 로직
# ==========================================
if 'mode' not in st.session_state: st.session_state['mode'] = 'setup'

if st.session_state['mode'] == 'setup':
    st.title("Welcome to Syntax Pitching™")
    if url_student:
        st.markdown(f"### {url_student}님, 환영합니다!\n왼쪽에서 챕터를 선택하고 훈련을 시작하세요.")
    else:
        st.markdown("### 👈 왼쪽 사이드바에서 수강생을 선택해주세요.")
    st.caption("© Powered by Kusukban | All Rights Reserved.")

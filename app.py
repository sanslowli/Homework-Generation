import streamlit as st
import os
import random
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pandas as pd
from PIL import Image
import base64

# ==========================================
# [설정] 기본 경로 및 구글 시트
# ==========================================
st.set_page_config(page_title="Syntax Pitching™", layout="wide")

# [업데이트] CSS: 모바일 폰트 크기 70% 축소 (줄바꿈 허용)
st.markdown("""
    <style>
        /* 기본 폰트 설정 (아이콘 제외) */
        .stApp, .stMarkdown, p, h1, h2, h3, h4, div[data-testid="stMarkdownContainer"] {
            font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans KR", sans-serif !important;
        }
        
        /* 배경색 */
        .stApp { background-color: #F0F2F6; }
        [data-testid="stSidebar"] { background-color: #E0E2E6; }
        .stButton>button { border-radius: 8px; font-weight: 500; }

        /* [모바일 최적화] 화면 너비가 768px 이하일 때 적용 */
        @media only screen and (max-width: 768px) {
            /* 1. 제목 크기 축소 (약 70%) */
            h1 { font-size: 22px !important; }
            h3 { font-size: 16px !important; }
            p, div, span { font-size: 13px !important; }
            
            /* 2. 사이드바 제목 축소 (줄바꿈 허용) */
            .sidebar-title {
                font-size: 20px !important; 
                margin-bottom: 10px !important;
            }
            
            /* 3. 푸터 텍스트 축소 */
            .footer-text {
                font-size: 11px !important;
            }
            
            /* 4. 버튼 텍스트도 살짝 줄임 */
            .stButton>button {
                font-size: 14px !important;
            }
        }

        /* 데스크탑 사이드바 제목 */
        .sidebar-title {
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 20px;
            color: #31333F;
        }
        
        /* 푸터 스타일 */
        .footer-text {
            color: #888;
            margin-top: 20px;
        }
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

# [최적화] 이미지 변환 결과 캐싱 (@st.cache_data)
# - 한 번 변환한 이미지는 메모리에 저장해두고 재사용하여 속도 저하 방지
@st.cache_data(show_spinner=False)
def get_image_base64(image_path):
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

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
    
    st.markdown('<div class="footer-text">© Powered by Kusukban | All Rights Reserved.</div>', unsafe_allow_html=True)

elif st.session_state['mode'] == 'playing':
    playlist = st.session_state['playlist']
    idx = st.session_state['current_index']
    is_practice = st.session_state.get('is_practice_mode', False)

    if is_practice: st.warning("현재 '틀린 구간 반복 모드'입니다. (기록되지 않음)")
    st.progress(idx / len(playlist))
    st.caption(f"Progress: {idx + 1} / {len(playlist)}")

    if idx < len(playlist):
        current_img_path = playlist[idx]
        
        try:
            abs_path = os.path.abspath(current_img_path)
            img = Image.open(abs_path)
            w, h = img.size
            actual_ratio = w / h
            target_ratio = (3 * 2.69) / 2.45

            # 너비 비율 계산 (최대 100%)
            width_pct = min(100, (actual_ratio / target_ratio) * 100)
            img_b64 = get_image_base64(abs_path)
            
            # [수정] 수직 중앙 정렬을 위한 Flexbox 설정
            # - align-items: center -> 수직 중앙 정렬
            # - min-height: 50vh -> 이미지가 작아도 최소한 화면 절반 높이의 공간을 확보하여 중앙에 띄움
            html_code = f"""
            <div style="display: flex; justify-content: center; align-items: center; width: 100%; min-height: 50vh;">
                <img src="data:image/png;base64,{img_b64}" 
                     style="width: {width_pct}%; max-width: 100%; max-height: 80vh; height: auto; border-radius: 5px;">
            </div>
            """
            st.markdown(html_code, unsafe_allow_html=True)

        except Exception as e:
            st.error(f"Image Error: {e}")
            st.image(current_img_path, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🙅 미통과", key='fail', use_container_width=True):
                if not is_practice and client: save_to_sheet(client, st.session_state['student_name'], st.session_state['chapter_name'], os.path.basename(current_img_path), "X")
                st.session_state['results'].append({'file': current_img_path, 'result': 'X'})
                st.session_state['current_index'] += 1
                st.rerun()
        with col2:
            if st.button("🙆 통과", key='pass', use_container_width=True):
                if not is_practice and client: save_to_sheet(client, st.session_state['student_name'], st.session_state['chapter_name'], os.path.basename(current_img_path), "O")
                st.session_state['results'].append({'file': current_img_path, 'result': 'O'})
                st.session_state['current_index'] += 1
                st.rerun()
        
        if is_practice:
            st.write("")
            if st.button("연습 종료", use_container_width=True):
                st.session_state['mode'] = 'setup'
                st.rerun()

    else:
        if is_practice:
            random.shuffle(st.session_state['playlist'])
            st.session_state['current_index'] = 0
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
                    if client: st.session_state['db_data'] = get_data_from_sheet(client)
                    st.rerun()
            with c2:
                if failed_items and st.button("틀린 구간 반복", use_container_width=True):
                    st.session_state.update({'playlist': random.sample(failed_items, len(failed_items)), 'current_index': 0, 'results': [], 'is_practice_mode': True})
                    st.rerun()
            with c3:
                if st.button("처음으로", use_container_width=True): st.session_state['mode'] = 'setup'; st.rerun()

elif st.session_state['mode'] == 'records':
    st.title(f"피칭 기록: {st.session_state['student_name']} - {st.session_state['chapter_name']}")
    if st.button("뒤로가기"): st.session_state['mode'] = 'setup'; st.rerun()
    
    imgs = get_images(st.session_state['folder_name'], st.session_state['student_name'], st.session_state['chapter_path'])
    if imgs and 'db_data' in st.session_state:
        cols = st.columns(3)
        for i, img_path in enumerate(imgs):
            with cols[i % 3]:
                st.image(img_path, use_container_width=True)
                avg, history = calculate_batting_average(st.session_state['db_data'], st.session_state['student_name'], img_path)
                color = "green" if avg >= 0.8 else "orange" if avg >= 0.5 else "red"
                hist_str = " ".join([f"{h}" for h in history])
                st.caption(f"타율: :{color}[{avg*100:.0f}%] | {hist_str}")

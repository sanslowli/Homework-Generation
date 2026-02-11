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

BASE_FOLDER = "." 
TARGET_FOLDERS = ["Syntax Pitching", "Syntax Only", "Syntax + Open-ended Question"]
ALLOWED_SUBFOLDERS = ["현행 챕터", "지난 챕터"]
SHEET_NAME = "Syntax Pitching DB"

# ==========================================
# [DB] 구글 시트 연결 & 데이터 처리
# ==========================================
@st.cache_resource
def init_connection():
    try:
        # Streamlit Secrets에서 계층형으로 가져오기
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
        st.cache_data.clear() # 데이터 갱신
    except Exception as e:
        st.error(f"데이터 저장 실패: {e}")

# ==========================================
# [로직] 파일 탐색 및 통계
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

def calculate_batting_average(df, student, image_name):
    if df.empty: return 0.0, []
    # 파일명만 추출해서 비교
    image_base = os.path.basename(image_name)
    target_df = df[(df['Student'] == student) & (df['Image'] == image_base)]
    if target_df.empty: return 0.0, []
    recent_records = target_df.tail(5)['Result'].tolist()
    return recent_records.count('O') / len(recent_records), recent_records

# ==========================================
# [화면] 사이드바 구성
# ==========================================
client = init_connection()
st.sidebar.title("Syntax Pitching™")

all_students_info = get_all_students()
if all_students_info:
    selected_data = st.sidebar.selectbox("수강생 선택", all_students_info, format_func=lambda x: x[1])
    if selected_data:
        folder_name, student_name = selected_data
        chapter_list = get_chapters(folder_name, student_name)
        
        if chapter_list:
            selected_chapter_data = st.sidebar.selectbox("챕터 선택", chapter_list, format_func=lambda x: x[1])
            
            # [훈련 시작]
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

            # [기록 보기] - 버튼 다시 살림!
            st.sidebar.markdown("---")
            if st.sidebar.button("📊 피칭 기록 보기", use_container_width=True):
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

# 1. 초기 화면
if st.session_state['mode'] == 'setup':
    st.title("Welcome to Syntax Pitching™")
    st.markdown("### 👈 왼쪽 사이드바에서 수강생을 선택해주세요.\n© Powered by Kusukban | All Rights Reserved.")

# 2. 훈련 화면
elif st.session_state['mode'] == 'playing':
    playlist = st.session_state['playlist']
    idx = st.session_state['current_index']
    is_practice = st.session_state.get('is_practice_mode', False)

    if is_practice: st.warning("⚠️ 현재 '틀린 구간 연습 모드'입니다. (기록되지 않음)")
    st.progress(idx / len(playlist))
    st.caption(f"Progress: {idx + 1} / {len(playlist)}")

    if idx < len(playlist):
        current_img_path = playlist[idx]
        img_name = os.path.basename(current_img_path)
        st.image(current_img_path, caption=img_name, use_container_width=True)

        if not is_practice and 'db_data' in st.session_state:
            avg, history = calculate_batting_average(st.session_state['db_data'], st.session_state['student_name'], img_name)
            color = "green" if avg >= 0.8 else "orange" if avg >= 0.5 else "red"
            hist_str = "".join(["🟢" if h=='O' else "🔴" for h in history])
            st.markdown(f"**최근 타율:** :{color}[{avg*100:.0f}%]  |  **기록:** {hist_str}")

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("⬅️ 뒤로가기", use_container_width=True) and idx > 0:
                st.session_state['current_index'] -= 1
                if st.session_state['results']: st.session_state['results'].pop()
                st.rerun()
        with col2:
            if st.button("❌ 다시", key='fail', use_container_width=True):
                if not is_practice and client: save_to_sheet(client, st.session_state['student_name'], st.session_state['chapter_name'], img_name, "X")
                st.session_state['results'].append({'file': current_img_path, 'result': 'X'})
                st.session_state['current_index'] += 1
                st.rerun()
        with col3:
            if st.button("⭕️ 통과", key='pass', use_container_width=True):
                if not is_practice and client: save_to_sheet(client, st.session_state['student_name'], st.session_state['chapter_name'], img_name, "O")
                st.session_state['results'].append({'file': current_img_path, 'result': 'O'})
                st.session_state['current_index'] += 1
                st.rerun()
    else:
        st.balloons(); st.success("🎉 훈련 완료!")
        results = st.session_state['results']
        failed_items = [r['file'] for r in results if r['result'] == 'X']
        st.markdown(f"### 결과: {len([r for r in results if r['result'] == 'O'])} / {len(results)}")
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("🔄 처음부터 재도전", use_container_width=True):
                st.session_state.update({'playlist': random.sample(st.session_state['original_playlist'], len(st.session_state['original_playlist'])), 'current_index': 0, 'results': [], 'is_practice_mode': False})
                if client: st.session_state['db_data'] = get_data_from_sheet(client)
                st.rerun()
        with c2:
            if failed_items and st.button("🔥 틀린 구간만 연습", use_container_width=True):
                st.session_state.update({'playlist': random.sample(failed_items, len(failed_items)), 'current_index': 0, 'results': [], 'is_practice_mode': True})
                st.rerun()
        with c3:
            if st.button("🏠 처음으로", use_container_width=True): st.session_state['mode'] = 'setup'; st.rerun()

# 3. 기록 보기 화면
elif st.session_state['mode'] == 'records':
    st.title(f"📊 {st.session_state['student_name']} - {st.session_state['chapter_name']}")
    if st.button("⬅️ 뒤로가기"): st.session_state['mode'] = 'setup'; st.rerun()
    
    imgs = get_images(st.session_state['folder_name'], st.session_state['student_name'], st.session_state['chapter_path'])
    if imgs and 'db_data' in st.session_state:
        # 3열 그리드 배치
        cols = st.columns(3)
        for i, img_path in enumerate(imgs):
            with cols[i % 3]:
                st.image(img_path, use_container_width=True)
                avg, history = calculate_batting_average(st.session_state['db_data'], st.session_state['student_name'], os.path.basename(img_path))
                color = "green" if avg >= 0.8 else "orange" if avg >= 0.5 else "red"
                hist_str = "".join(["🟢" if h=='O' else "🔴" for h in history])
                st.caption(f"타율: :{color}[{avg*100:.0f}%] | {hist_str}")

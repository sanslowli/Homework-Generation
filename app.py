import streamlit as st
import os
import random
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pandas as pd

# ==========================================
# [설정] 기본 경로 및 구글 시트
# ==========================================
st.set_page_config(page_title="Syntax Pitching™", layout="wide")

BASE_FOLDER = "." 
TARGET_FOLDERS = ["Syntax Pitching", "Syntax Only", "Syntax + Open-ended Question"]
ALLOWED_SUBFOLDERS = ["현행 챕터", "지난 챕터"]

# 구글 시트 이름 (아까 만드신 시트 이름과 똑같아야 합니다)
SHEET_NAME = "Syntax Pitching DB"

# ==========================================
# [DB] 구글 시트 연결 & 데이터 처리
# ==========================================
@st.cache_resource
def init_connection():
    try:
        # Streamlit Secrets에서 키 가져오기
        # .streamlit/secrets.toml 파일 혹은 Streamlit Cloud Secrets에 
        # [connections.gsheets] 섹션 하위에 JSON 내용을 넣어야 함
        credentials = st.secrets["connections.gsheets"]
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
        # 모든 데이터를 가져옴 (헤더 포함)
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        # 시트가 비어있거나 없을 경우 빈 DF 반환
        return pd.DataFrame(columns=["Timestamp", "Student", "Chapter", "Image", "Result"])

def save_to_sheet(client, student, chapter, image, result):
    try:
        sheet = client.open(SHEET_NAME).sheet1
        # 헤더가 없으면 생성
        if not sheet.get_all_values():
            sheet.append_row(["Timestamp", "Student", "Chapter", "Image", "Result"])
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, student, chapter, image, result])
        
        # 캐시 비우기 (데이터 갱신을 위해)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"데이터 저장 실패: {e}")

# ==========================================
# [로직] 파일 탐색
# ==========================================
def get_all_students():
    student_list = []
    for folder_name in TARGET_FOLDERS:
        target_path = os.path.join(BASE_FOLDER, folder_name)
        if os.path.exists(target_path):
            try:
                students = [d for d in os.listdir(target_path) 
                            if os.path.isdir(os.path.join(target_path, d)) 
                            and not d.startswith('.')]
                for s in students:
                    student_list.append((folder_name, s))
            except:
                continue
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
                subs = [d for d in os.listdir(sub_path) 
                        if os.path.isdir(os.path.join(sub_path, d)) 
                        and not d.startswith('.')]
                for ch in subs:
                    rel_path = os.path.join(sub, ch)
                    display_name = ch 
                    chapters.append((rel_path, display_name))
            except:
                continue
    chapters.sort(key=lambda x: x[1])
    return chapters

def get_images(folder_name, student_name, chapter_rel_path):
    full_path = os.path.join(BASE_FOLDER, folder_name, student_name, chapter_rel_path)
    images = []
    try:
        for f in os.listdir(full_path):
            if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                images.append(os.path.join(full_path, f))
    except:
        pass
    return sorted(images)

# ==========================================
# [통계] 타율 계산 (최근 5개 기준)
# ==========================================
def calculate_batting_average(df, student, image_name):
    if df.empty: return 0.0, []
    
    # 해당 학생, 해당 이미지의 기록만 필터링
    # 이미지 이름으로 필터링 (경로 제외)
    target_df = df[(df['Student'] == student) & (df['Image'] == image_name)]
    
    if target_df.empty:
        return 0.0, []
    
    # 최근 5개 추출
    recent_records = target_df.tail(5)['Result'].tolist()
    
    if not recent_records:
        return 0.0, []
        
    pass_count = recent_records.count('O')
    average = pass_count / len(recent_records)
    
    return average, recent_records

# ==========================================
# [화면] UI 구성
# ==========================================
# DB 연결 시도
client = init_connection()

st.sidebar.title("Syntax Pitching™")

all_students_info = get_all_students()

if not all_students_info:
    st.sidebar.warning("학생 데이터를 찾을 수 없습니다.")
else:
    selected_data = st.sidebar.selectbox("수강생 선택", all_students_info, format_func=lambda x: x[1])

    if selected_data:
        folder_name, student_name = selected_data
        chapter_list = get_chapters(folder_name, student_name)
        
        if chapter_list:
            selected_chapter_data = st.sidebar.selectbox("챕터 선택", chapter_list, format_func=lambda x: x[1])
            
            if st.sidebar.button("훈련 시작 (Start)", use_container_width=True):
                st.session_state['folder_name'] = folder_name
                st.session_state['student_name'] = student_name
                st.session_state['chapter_path'] = selected_chapter_data[0]
                st.session_state['chapter_name'] = selected_chapter_data[1]
                
                imgs = get_images(folder_name, student_name, selected_chapter_data[0])
                st.session_state['original_playlist'] = imgs 
                
                playlist = list(imgs)
                random.shuffle(playlist)
                
                st.session_state['playlist'] = playlist
                st.session_state['current_index'] = 0
                st.session_state['results'] = []
                st.session_state['is_practice_mode'] = False
                st.session_state['mode'] = 'playing'
                
                # [DB] 시작할 때 최신 데이터 한 번 로드
                if client:
                    st.session_state['db_data'] = get_data_from_sheet(client)
                
                st.rerun()

            # 기록 보기 버튼 (추후 구현)
            # st.sidebar.markdown("---")
            # if st.sidebar.button("📊 피칭 기록 보기"): ...

        else:
            st.sidebar.info("현행/지난 챕터가 없습니다.")

# 메인 로직
if 'mode' not in st.session_state:
    st.session_state['mode'] = 'setup'

if st.session_state['mode'] == 'setup':
    st.title("Welcome to Syntax Pitching™")
    st.markdown("""
    ### 👈 왼쪽 사이드바에서 수강생을 선택해주세요.
    © Powered by Kusukban | All Rights Reserved.
    """)

elif st.session_state['mode'] == 'playing':
    playlist = st.session_state['playlist']
    idx = st.session_state['current_index']
    is_practice = st.session_state.get('is_practice_mode', False)

    if is_practice:
        st.warning("⚠️ 현재 '틀린 구간 연습 모드'입니다. (기록되지 않음)")

    # 진행도
    progress = (idx / len(playlist)) if len(playlist) > 0 else 0
    st.progress(progress)
    st.caption(f"Progress: {idx + 1} / {len(playlist)}")

    if idx < len(playlist):
        current_img_path = playlist[idx]
        img_name = os.path.basename(current_img_path)
        
        # 이미지 표시 (순정)
        st.image(current_img_path, caption=img_name, use_container_width=True)

        # [통계 표시] 실전 모드일 때만 타율 보여주기
        if not is_practice and 'db_data' in st.session_state:
            avg, history = calculate_batting_average(
                st.session_state['db_data'], 
                st.session_state['student_name'], 
                img_name
            )
            # 색상 코딩
            color = "green" if avg >= 0.8 else "orange" if avg >= 0.5 else "red"
            hist_str = "".join(["🟢" if h=='O' else "🔴" for h in history])
            st.markdown(f"**최근 타율:** :{color}[{avg*100:.0f}%]  |  **기록:** {hist_str}")

        # 버튼 영역
        st.write("") 
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            if st.button("⬅️ 뒤로가기", use_container_width=True):
                if idx > 0:
                    st.session_state['current_index'] -= 1
                    if st.session_state['results']: st.session_state['results'].pop()
                    st.rerun()
        with col2:
            if st.button("❌ 다시", key='fail', use_container_width=True):
                # [DB 저장] 실전 모드면 즉시 저장
                if not is_practice and client:
                    save_to_sheet(
                        client, 
                        st.session_state['student_name'], 
                        st.session_state['chapter_name'],
                        img_name, 
                        "X"
                    )
                
                st.session_state['results'].append({'file': current_img_path, 'result': 'X'})
                st.session_state['current_index'] += 1
                st.rerun()
        with col3:
            if st.button("⭕️ 통과", key='pass', use_container_width=True):
                # [DB 저장] 실전 모드면 즉시 저장
                if not is_practice and client:
                    save_to_sheet(
                        client, 
                        st.session_state['student_name'], 
                        st.session_state['chapter_name'],
                        img_name, 
                        "O"
                    )
                
                st.session_state['results'].append({'file': current_img_path, 'result': 'O'})
                st.session_state['current_index'] += 1
                st.rerun()
    else:
        st.balloons()
        st.success("🎉 훈련 완료!")
        
        results = st.session_state['results']
        score = [r for r in results if r['result'] == 'O']
        pass_count = len(score)
        total_count = len(results)
        
        st.markdown(f"### 결과: {pass_count} / {total_count}")
        
        failed_items = [r['file'] for r in results if r['result'] == 'X']
        st.markdown("---")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("🔄 처음부터 재도전", use_container_width=True):
                playlist = list(st.session_state['original_playlist'])
                random.shuffle(playlist)
                st.session_state['playlist'] = playlist
                st.session_state['current_index'] = 0
                st.session_state['results'] = []
                st.session_state['is_practice_mode'] = False
                # 재도전 시 DB 다시 로드 (방금 한 기록 반영 위해)
                if client: st.session_state['db_data'] = get_data_from_sheet(client)
                st.rerun()
        with c2:
            if failed_items:
                if st.button("🔥 틀린 구간만 연습", use_container_width=True):
                    playlist = list(failed_items)
                    random.shuffle(playlist)
                    st.session_state['playlist'] = playlist
                    st.session_state['current_index'] = 0
                    st.session_state['results'] = []
                    st.session_state['is_practice_mode'] = True
                    st.rerun()
            else:
                st.button("완벽합니다!", disabled=True, use_container_width=True)
        with c3:
            if st.button("🏠 처음으로 돌아가기", use_container_width=True):
                st.session_state['mode'] = 'setup'
                st.rerun()

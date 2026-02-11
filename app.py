import streamlit as st
import os
import random

# ==========================================
# [설정] 페이지 및 경로
# ==========================================
st.set_page_config(page_title="Syntax Pitching™", layout="wide")

# 현재 폴더(Homework-Generation)를 기준으로 잡음
BASE_FOLDER = "." 

# 웹앱에서 보여줄 VIP 폴더 3개
TARGET_FOLDERS = [
    "Syntax Pitching",
    "Syntax Only",
    "Syntax + Open-ended Question"
]

# ==========================================
# [로직] 데이터 불러오기
# ==========================================
def get_all_students():
    student_list = []
    for folder_name in TARGET_FOLDERS:
        target_path = os.path.join(BASE_FOLDER, folder_name)
        if os.path.exists(target_path):
            try:
                # 폴더 내 학생들 찾기 (숨김파일 제외)
                students = [d for d in os.listdir(target_path) 
                            if os.path.isdir(os.path.join(target_path, d)) 
                            and not d.startswith('.')]
                for s in students:
                    student_list.append((folder_name, s))
            except:
                continue
    # 이름순 정렬
    student_list.sort(key=lambda x: x[1])
    return student_list

def get_chapters(folder_name, student_name):
    student_path = os.path.join(BASE_FOLDER, folder_name, student_name)
    chapters = []
    try:
        for root, dirs, files in os.walk(student_path):
            image_files = [f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            if image_files:
                rel_path = os.path.relpath(root, student_path)
                chapters.append(rel_path)
        return sorted(chapters)
    except:
        return []

def get_images(folder_name, student_name, chapter_path):
    full_path = os.path.join(BASE_FOLDER, folder_name, student_name, chapter_path)
    images = []
    try:
        for f in os.listdir(full_path):
            if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                images.append(os.path.join(full_path, f))
    except:
        pass
    return sorted(images)

# ==========================================
# [화면] 사이드바
# ==========================================
st.sidebar.title("Syntax Pitching™")

all_students_info = get_all_students()
if not all_students_info:
    st.sidebar.warning("학생 폴더를 찾을 수 없습니다.")
else:
    # "학생이름 (소속)" 형태로 표시
    student_options = [f"{s[1]} ({s[0]})" for s in all_students_info]
    selected_option = st.sidebar.selectbox("수강생 선택", student_options)

    if selected_option:
        idx = student_options.index(selected_option)
        folder_name, student_name = all_students_info[idx]
        
        chapter_list = get_chapters(folder_name, student_name)
        selected_chapter = st.sidebar.selectbox("챕터 선택", chapter_list)

        if st.sidebar.button("훈련 시작 (Start)", use_container_width=True):
            st.session_state['playlist'] = get_images(folder_name, student_name, selected_chapter)
            random.shuffle(st.session_state['playlist'])
            st.session_state['current_index'] = 0
            st.session_state['results'] = []
            st.session_state['mode'] = 'playing'
            st.rerun()

# ==========================================
# [화면] 메인
# ==========================================
if 'mode' not in st.session_state:
    st.session_state['mode'] = 'setup'

if st.session_state['mode'] == 'setup':
    st.title("Welcome to Syntax Pitching™")
    st.markdown("""
    ### 👈 왼쪽에서 수강생을 선택해주세요.
    * **Syntax Pitching**: 피칭 수강생
    * **Syntax Only**: 빙고 (무료)
    * **Syntax + Open**: 빙고 (유료)
    """)

elif st.session_state['mode'] == 'playing':
    playlist = st.session_state['playlist']
    idx = st.session_state['current_index']
    
    # 진행도
    progress = (idx / len(playlist)) if len(playlist) > 0 else 0
    st.progress(progress)
    st.caption(f"Progress: {idx + 1} / {len(playlist)}")

    if idx < len(playlist):
        current_img_path = playlist[idx]
        img_name = os.path.basename(current_img_path)
        
        st.image(current_img_path, caption=img_name, use_container_width=True)

        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            if st.button("⬅️ 뒤로가기", use_container_width=True):
                if idx > 0:
                    st.session_state['current_index'] -= 1
                    if st.session_state['results']: st.session_state['results'].pop()
                    st.rerun()
        with col2:
            if st.button("❌ 다시", key='fail', use_container_width=True):
                st.session_state['results'].append({'file': img_name, 'result': 'X'})
                st.session_state['current_index'] += 1
                st.rerun()
        with col3:
            if st.button("⭕️ 통과", key='pass', use_container_width=True):
                st.session_state['results'].append({'file': img_name, 'result': 'O'})
                st.session_state['current_index'] += 1
                st.rerun()
    else:
        st.balloons()
        st.success("🎉 훈련 완료!")
        
        results = st.session_state['results']
        score = [r for r in results if r['result'] == 'O']
        st.markdown(f"### 결과: {len(score)} / {len(results)}")
        
        if st.button("처음으로 돌아가기", use_container_width=True):
            st.session_state['mode'] = 'setup'
            st.rerun()

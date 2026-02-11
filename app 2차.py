import streamlit as st
import os
import random
from PIL import Image

# ==========================================
# [설정] 페이지 및 경로
# ==========================================
st.set_page_config(page_title="Syntax Pitching™", layout="wide")

BASE_FOLDER = "." 

TARGET_FOLDERS = [
    "Syntax Pitching",
    "Syntax Only",
    "Syntax + Open-ended Question"
]

ALLOWED_SUBFOLDERS = ["현행 챕터", "지난 챕터"]

# ==========================================
# [로직] 데이터 불러오기
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
    
    if not os.path.exists(student_path):
        return []

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
    
    # 챕터 이름순 정렬 (문자열 기준)
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
# [화면] 사이드바
# ==========================================
st.sidebar.title("Syntax Pitching™")

all_students_info = get_all_students()

if not all_students_info:
    st.sidebar.warning("학생 데이터를 찾을 수 없습니다.")
else:
    selected_data = st.sidebar.selectbox(
        "수강생 선택", 
        all_students_info, 
        format_func=lambda x: x[1] 
    )

    if selected_data:
        folder_name, student_name = selected_data
        chapter_list = get_chapters(folder_name, student_name)
        
        if chapter_list:
            selected_chapter_data = st.sidebar.selectbox(
                "챕터 선택", 
                chapter_list, 
                format_func=lambda x: x[1]
            )

            if st.sidebar.button("훈련 시작 (Start)", use_container_width=True):
                st.session_state['playlist'] = get_images(folder_name, student_name, selected_chapter_data[0])
                random.shuffle(st.session_state['playlist'])
                st.session_state['current_index'] = 0
                st.session_state['results'] = []
                st.session_state['mode'] = 'playing'
                st.rerun()
        else:
            st.sidebar.info("현행/지난 챕터가 없습니다.")

# ==========================================
# [화면] 메인
# ==========================================
if 'mode' not in st.session_state:
    st.session_state['mode'] = 'setup'

if st.session_state['mode'] == 'setup':
    st.title("Welcome to Syntax Pitching™")
    st.markdown("### 👈 왼쪽 사이드바에서 수강생을 선택해주세요.")
    st.markdown("---")
    st.caption("© Powered by **Kusukban** | All Rights Reserved.")

elif st.session_state['mode'] == 'playing':
    playlist = st.session_state['playlist']
    idx = st.session_state['current_index']
    
    progress = (idx / len(playlist)) if len(playlist) > 0 else 0
    st.progress(progress)
    st.caption(f"Progress: {idx + 1} / {len(playlist)}")

    if idx < len(playlist):
        current_img_path = playlist[idx]
        img_name = os.path.basename(current_img_path)
        
        # [이미지 사이즈 정밀 제어 로직]
        try:
            image = Image.open(current_img_path)
            width, height = image.size
            aspect_ratio = width / height
            
            # 기준값 설정 (재영 님이 원한 '3칸 정도'의 비율)
            # 보통 정사각형 패널 3개면 비율이 약 2.5 ~ 3.0 사이입니다.
            # 이 값을 2.5로 잡으면, 3칸짜리는 꽉 차고, 1칸짜리는 1/3 크기로 나옵니다.
            STANDARD_MAX_RATIO = 2.5 

            if aspect_ratio >= STANDARD_MAX_RATIO:
                # 3칸 이상(긴 이미지)은 화면을 꽉 채움
                st.image(current_img_path, caption=img_name, use_container_width=True)
            else:
                # 1칸, 2칸(짧은 이미지)은 비율에 맞춰서 가운데 정렬
                # 좌우 여백을 계산해서 컬럼을 나눕니다.
                
                # 이미지의 상대적 너비 비율 (예: 1칸이면 0.33, 2칸이면 0.66)
                img_width_ratio = aspect_ratio
                
                # 남는 공간 (여백)
                padding = (STANDARD_MAX_RATIO - aspect_ratio) / 2
                
                # 컬럼 생성 [왼쪽여백, 이미지, 오른쪽여백]
                # 비율이 음수가 되지 않도록 최소한의 안전장치 max(0.1, padding)
                cols = st.columns([max(0.01, padding), aspect_ratio, max(0.01, padding)])
                
                with cols[1]:
                    st.image(current_img_path, caption=img_name, use_container_width=True)

        except Exception:
            st.image(current_img_path, caption=img_name, use_container_width=True)

        # 버튼 영역
        st.write("") # 간격 띄우기
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

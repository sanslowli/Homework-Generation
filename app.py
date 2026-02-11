import streamlit as st
import os
import random

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
# [함수] 데이터 로드 로직
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
# [화면] 사이드바
# ==========================================
st.sidebar.title("Syntax Pitching™")

all_students_info = get_all_students()

if not all_students_info:
    st.sidebar.warning("학생 데이터를 찾을 수 없습니다.")
else:
    # 수강생 선택 (이름만 표시)
    selected_data = st.sidebar.selectbox(
        "수강생 선택", 
        all_students_info, 
        format_func=lambda x: x[1] 
    )

    if selected_data:
        folder_name, student_name = selected_data
        chapter_list = get_chapters(folder_name, student_name)
        
        if chapter_list:
            # 챕터 선택 (숫자만 표시)
            selected_chapter_data = st.sidebar.selectbox(
                "챕터 선택", 
                chapter_list, 
                format_func=lambda x: x[1]
            )
            
            # [훈련 시작 버튼]
            if st.sidebar.button("훈련 시작 (Start)", use_container_width=True):
                st.session_state['folder_name'] = folder_name
                st.session_state['student_name'] = student_name
                st.session_state['chapter_path'] = selected_chapter_data[0]
                
                # 플레이리스트 로드
                imgs = get_images(folder_name, student_name, selected_chapter_data[0])
                st.session_state['original_playlist'] = imgs # 전체 백업
                
                # 초기화
                playlist = list(imgs)
                random.shuffle(playlist)
                
                st.session_state['playlist'] = playlist
                st.session_state['current_index'] = 0
                st.session_state['results'] = []
                st.session_state['is_practice_mode'] = False # 실전 모드
                st.session_state['mode'] = 'playing'
                st.rerun()

            # [기록 보기 버튼]
            st.sidebar.markdown("---")
            if st.sidebar.button("📊 피칭 기록 보기", use_container_width=True):
                st.session_state['student_name'] = student_name # 누구 기록인지 알아야 함
                st.session_state['mode'] = 'records'
                st.rerun()

        else:
            st.sidebar.info("현행/지난 챕터가 없습니다.")

# ==========================================
# [화면] 메인 로직
# ==========================================
if 'mode' not in st.session_state:
    st.session_state['mode'] = 'setup'

# 1. 초기 화면 (Setup)
if st.session_state['mode'] == 'setup':
    st.title("Welcome to Syntax Pitching™")
    # [수정] 구분선 및 여백 제거, Bold 해제
    st.markdown("""
    ### 👈 왼쪽 사이드바에서 수강생을 선택해주세요.
    © Powered by Kusukban | All Rights Reserved.
    """)

# 2. 훈련 화면 (Playing)
elif st.session_state['mode'] == 'playing':
    playlist = st.session_state['playlist']
    idx = st.session_state['current_index']
    is_practice = st.session_state.get('is_practice_mode', False)

    # 상단 배지 (연습 모드일 때 표시)
    if is_practice:
        st.warning("⚠️ 현재 '틀린 구간 연습 모드'입니다. (기록되지 않음)")

    # 진행도
    progress = (idx / len(playlist)) if len(playlist) > 0 else 0
    st.progress(progress)
    st.caption(f"Progress: {idx + 1} / {len(playlist)}")

    if idx < len(playlist):
        current_img_path = playlist[idx]
        img_name = os.path.basename(current_img_path)
        
        # [수정] 이미지 비율 로직 제거 -> 순정 상태 (꽉 차게)
        st.image(current_img_path, caption=img_name, use_container_width=True)

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
                st.session_state['results'].append({'file': current_img_path, 'result': 'X'})
                st.session_state['current_index'] += 1
                st.rerun()
        with col3:
            if st.button("⭕️ 통과", key='pass', use_container_width=True):
                st.session_state['results'].append({'file': current_img_path, 'result': 'O'})
                st.session_state['current_index'] += 1
                st.rerun()
    else:
        # [훈련 종료 화면]
        st.balloons()
        st.success("🎉 훈련 완료!")
        
        results = st.session_state['results']
        score = [r for r in results if r['result'] == 'O']
        pass_count = len(score)
        total_count = len(results)
        
        st.markdown(f"### 결과: {pass_count} / {total_count}")
        
        # 틀린 목록 추출
        failed_items = [r['file'] for r in results if r['result'] == 'X']

        st.markdown("---")
        
        # [버튼 3개 배치]
        c1, c2, c3 = st.columns(3)
        
        with c1:
            # 1. 재도전 (처음부터 다시, 기록 반영)
            if st.button("🔄 처음부터 재도전", use_container_width=True):
                # 원본 플레이리스트 다시 로드
                playlist = list(st.session_state['original_playlist'])
                random.shuffle(playlist)
                
                st.session_state['playlist'] = playlist
                st.session_state['current_index'] = 0
                st.session_state['results'] = []
                st.session_state['is_practice_mode'] = False
                st.rerun()
                
        with c2:
            # 2. 틀린 구간만 연습 (기록 미반영)
            if failed_items:
                if st.button("🔥 틀린 구간만 연습", use_container_width=True):
                    # 틀린 것만 추려서 플레이리스트 구성
                    playlist = list(failed_items)
                    random.shuffle(playlist)
                    
                    st.session_state['playlist'] = playlist
                    st.session_state['current_index'] = 0
                    st.session_state['results'] = []
                    st.session_state['is_practice_mode'] = True # 연습 모드 ON
                    st.rerun()
            else:
                st.button("🔥 틀린 구간 없음 (완벽!)", disabled=True, use_container_width=True)

        with c3:
            # 3. 처음으로 (메인 화면)
            if st.button("🏠 처음으로 돌아가기", use_container_width=True):
                st.session_state['mode'] = 'setup'
                st.rerun()
        
        # (여기에 나중에 구글 시트 저장 로직이 들어갑니다)
        if not st.session_state.get('is_practice_mode', False):
             st.info("ℹ️ 현재 실전 모드입니다. (데이터 저장 기능 준비 중)")

# 3. 기록 보기 화면 (Records)
elif st.session_state['mode'] == 'records':
    student_name = st.session_state.get('student_name', 'Unknown')
    st.title(f"📊 {student_name}님의 피칭 기록")
    
    st.info("🚧 구글 시트 연동 대기 중입니다.")
    st.markdown("""
    **[예정된 기능]**
    1. 최근 5회 타율 그래프
    2. 챕터별 누적 성공률
    3. 날짜별 훈련 로그
    """)
    
    if st.button("⬅️ 뒤로가기"):
        st.session_state['mode'] = 'setup'
        st.rerun()

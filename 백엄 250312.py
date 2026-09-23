import os
import random
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# 기본 설정
TARGET_HEIGHT = 140  # 각 개별 이미지의 목표 높이
GRID_COLS = 4  # 4칸짜리 그리드
GRID_ROWS = 5  # 5개 구간 (5행)
HEADER_HEIGHT = 50  # 학생 이름이 들어갈 추가 공간
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"  # 한글 지원 폰트 경로
FONT_SIZE = 30  # 학생 이름 폰트 크기

# 학생 폴더가 있는 '그림 파일' 폴더 경로 설정
BASE_FOLDER = "/Users/seojaeyeong/Library/Mobile Documents/com~apple~CloudDocs/쿠숙반/커리큘럼/그림 파일"

def resize_image(image_path):
    """이미지를 TARGET_HEIGHT에 맞게 리사이징하면서 흰 배경 추가"""
    img = Image.open(image_path).convert("RGBA")  # RGBA 모드로 변환
    original_width, original_height = img.size

    # 비율 유지하면서 TARGET_HEIGHT 맞추기
    scale_factor = TARGET_HEIGHT / original_height
    new_width = int(original_width * scale_factor)
    img = img.resize((new_width, TARGET_HEIGHT), resample=Image.LANCZOS)  # 고품질 리사이징

    # 흰 배경 생성 (최대 너비 기준)
    white_bg = Image.new("RGBA", (new_width, TARGET_HEIGHT), "WHITE")
    white_bg.paste(img, (0, 0), img)  # 투명 배경을 흰색으로 채움
    return white_bg.convert("RGB")  # 다시 RGB로 변환하여 반환

def generate_homework_for_all():
    """모든 학생 폴더를 탐색하여 숙제 이미지를 생성"""
    student_folders = [f for f in os.listdir(BASE_FOLDER) if os.path.isdir(os.path.join(BASE_FOLDER, f))]
    today = datetime.today().strftime('%-m/%-d')  # 월/일 형식 (예: 3/1)

    for student_name in student_folders:
        student_folder = os.path.join(BASE_FOLDER, student_name)
        output_path = os.path.join(BASE_FOLDER, f"{student_name}_{today}.jpeg")  # 최종 저장 경로
        
        # 학생 폴더 내 이미지 찾기
        all_images = []
        for root, _, files in os.walk(student_folder):
            images = [os.path.join(root, f) for f in files if f.endswith(('.jpeg', '.jpg', '.png'))]
            all_images.extend(images)

        if len(all_images) < 5:
            print(f"❌ {student_name}: 구간 이미지가 5개 미만이라 숙제를 생성할 수 없습니다.")
            continue
        
        # 5개 이미지 무작위 선택
        selected_images = random.sample(all_images, 5)
        resized_images = [resize_image(img) for img in selected_images]  # 리사이징 적용

        # 최종 이미지 크기 결정
        max_width = max(img.size[0] for img in resized_images)  # 가장 넓은 이미지 기준
        total_height = (TARGET_HEIGHT * GRID_ROWS) + HEADER_HEIGHT  # 5행 + 학생이름 헤더
        
        # 최종 이미지 생성 (흰 배경)
        final_image = Image.new("RGB", (max_width, total_height), "white")
        
        # 학생 이름 + 날짜 추가 (헤더 부분)
        student_label = f"{student_name} {today}"  # 예: "김지연 3/1"
        draw = ImageDraw.Draw(final_image)
        try:
            font = ImageFont.truetype(FONT_PATH, FONT_SIZE)  # 한글 폰트 설정
        except IOError:
            font = ImageFont.load_default()  # 폰트 로드 실패 시 기본 폰트 사용
        draw.text((10, 10), student_label, fill="black", font=font)  # 왼쪽 상단에 이름 + 날짜 추가
        
        # 이미지 배치 (왼쪽 정렬)
        y_offset = HEADER_HEIGHT
        for img in resized_images:
            img_width, img_height = img.size
            padded_img = Image.new("RGB", (max_width, TARGET_HEIGHT), "white")
            padded_img.paste(img, (0, 0))  # 왼쪽 정렬
            final_image.paste(padded_img, (0, y_offset))
            y_offset += TARGET_HEIGHT

        # 최종 이미지 저장
        final_image.save(output_path, "JPEG")
        print(f"✅ {student_name} 숙제 이미지 생성 완료: {output_path}")

# 실행
if __name__ == "__main__":
    generate_homework_for_all()

import os
import random
import textwrap
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import json

# 기본 설정
TARGET_HEIGHT = 140
GRID_COLS = 4
GRID_ROWS = 6
HEADER_HEIGHT = 50
QUESTION_BOX_WIDTH = TARGET_HEIGHT * GRID_COLS
QUESTION_BOX_HEIGHT = TARGET_HEIGHT
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT_SIZE = 30
BASE_FOLDER = "/Users/seojaeyeong/숙제 생성"
QUESTION_FILE = os.path.join(BASE_FOLDER, "questions.json")
ASKED_QUESTIONS_FILE = os.path.join(BASE_FOLDER, "asked_questions.json")

def resize_image(image_path):
    img = Image.open(image_path).convert("RGBA")
    original_width, original_height = img.size
    scale_factor = TARGET_HEIGHT / original_height
    new_width = int(original_width * scale_factor)
    img = img.resize((new_width, TARGET_HEIGHT), resample=Image.LANCZOS)
    white_bg = Image.new("RGBA", (new_width, TARGET_HEIGHT), "WHITE")
    white_bg.paste(img, (0, 0), img)
    return white_bg.convert("RGB")

def get_random_question(student_name):
    with open(QUESTION_FILE, "r", encoding="utf-8") as f:
        questions = json.load(f)
    if os.path.exists(ASKED_QUESTIONS_FILE):
        with open(ASKED_QUESTIONS_FILE, "r", encoding="utf-8") as f:
            asked_questions = json.load(f)
    else:
        asked_questions = {}
    previous_questions = set(asked_questions.get(student_name, []))
    available_questions = [q for q in questions if q not in previous_questions]
    if not available_questions:
        return "NO AVAILABLE QUESTIONS."
    selected_question = random.choice(available_questions)
    asked_questions.setdefault(student_name, []).append(selected_question)
    with open(ASKED_QUESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(asked_questions, f, ensure_ascii=False, indent=2)
    return selected_question

def create_question_box(question_text, width, height):
    box = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(box)
    max_font_size = 30
    min_font_size = 18
    while max_font_size >= min_font_size:
        try:
            font = ImageFont.truetype(FONT_PATH, max_font_size)
        except IOError:
            font = ImageFont.load_default()
        wrapped_text = textwrap.fill(question_text, width=40)
        text_bbox = draw.textbbox((0, 0), wrapped_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        if text_width <= width - 20 and text_height <= height - 20:
            break
        max_font_size -= 2
    text_x = (width - text_width) // 2
    text_y = (height - text_height) // 2
    draw.text((text_x, text_y), wrapped_text, fill="black", font=font)
    return box

def generate_homework_for_all():
    student_folders = [f for f in os.listdir(BASE_FOLDER) if os.path.isdir(os.path.join(BASE_FOLDER, f))]
    today_filename = datetime.today().strftime('%Y-%m-%d')
    today_display = datetime.today().strftime('%-m/%-d')
    existing_homework_files = set(os.listdir(BASE_FOLDER))

    for student_name in student_folders:
        # ✅ 이름 포함 여부로 중복 검사
        if any(student_name in f and f.endswith(".jpeg") for f in existing_homework_files):
            print(f"⏭️ {student_name}: 기존 숙제가 있어서 새로운 숙제를 생성하지 않음.")
            continue

        output_filename = f"{today_filename}_{student_name}.jpeg"
        output_path = os.path.join(BASE_FOLDER, output_filename)

        student_folder = os.path.join(BASE_FOLDER, student_name)
        current_path = os.path.join(student_folder, "현행 챕터")
        past_path = os.path.join(student_folder, "지난 챕터")

        current_images, past_images = [], []
        for root, _, files in os.walk(current_path):
            current_images += [os.path.join(root, f) for f in files if f.endswith(('.jpeg', '.jpg', '.png'))]
        for root, _, files in os.walk(past_path):
            past_images += [os.path.join(root, f) for f in files if f.endswith(('.jpeg', '.jpg', '.png'))]

        selected_images = []

        if len(current_images) >= 3 and len(past_images) >= 2:
            selected_images += random.sample(current_images, 3)
            selected_images += random.sample(past_images, 2)
        elif len(current_images) >= 5:
            selected_images = random.sample(current_images, 5)
        elif len(past_images) >= 5:
            selected_images = random.sample(past_images, 5)
        else:
            print(f"❌ {student_name}: 충분한 이미지가 없어 숙제를 생성할 수 없습니다.")
            continue

        resized_images = [resize_image(img) for img in selected_images]
        question_text = get_random_question(student_name)
        question_box = create_question_box(question_text, QUESTION_BOX_WIDTH, QUESTION_BOX_HEIGHT)

        max_width = max(img.size[0] for img in resized_images)
        max_width = max(max_width, TARGET_HEIGHT * GRID_COLS)  # ✅ 최소 너비 보장 (ex. 140×4=560)
        total_height = (TARGET_HEIGHT * GRID_ROWS) + HEADER_HEIGHT
        final_image = Image.new("RGB", (max_width, total_height), "white")

        draw = ImageDraw.Draw(final_image)
        try:
            font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        except IOError:
            font = ImageFont.load_default()
        draw.text((10, 10), f"{student_name} {today_display}", fill="black", font=font)

        y_offset = HEADER_HEIGHT
        for img in resized_images:
            final_image.paste(img, (0, y_offset))
            y_offset += TARGET_HEIGHT

        final_image.paste(question_box, (0, y_offset))
        final_image.save(output_path, "JPEG")
        print(f"✅ {student_name} 숙제 생성 완료: {output_path}")

if __name__ == "__main__":
    generate_homework_for_all()

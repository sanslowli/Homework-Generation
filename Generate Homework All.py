import os
import random
import textwrap
import unicodedata  # [NEW] 맥 한글 자모 분리 해결용
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import json

# ======================
# 기본 설정
# ======================
TARGET_HEIGHT = 140
GRID_COLS = 4
GRID_ROWS = 6 
HEADER_HEIGHT = 50
QUESTION_BOX_WIDTH = TARGET_HEIGHT * GRID_COLS
QUESTION_BOX_HEIGHT = TARGET_HEIGHT
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT_SIZE = 30
BASE_FOLDER = "/Users/seojaeyeong/Homework-Generation"
QUESTION_FILE = os.path.join(BASE_FOLDER, "questions.json")
ASKED_QUESTIONS_FILE = os.path.join(BASE_FOLDER, "asked_questions.json")

# [PLAN] 상위 플랜 폴더
FREE_PLAN_DIR  = os.path.join(BASE_FOLDER, "Syntax Only")
PAID_PLAN_DIR  = os.path.join(BASE_FOLDER, "Syntax + Open-ended Question")

# 출제 횟수 기록 파일명
USAGE_LOG_FILE = "usage_history.json"

# ======================
# 라벨 스타일
# ======================
LABEL_FONT_SIZE = 18
LABEL_PAD_X = 6
LABEL_PAD_Y = 3
LABEL_CORNER = 6
LABEL_TEXT_RGBA = (255, 255, 255, 255)
LABEL_OFFSET_X = 0
LABEL_OFFSET_Y = 0
LABEL_ALPHA = 160

RED_HEX    = '#D6524B'
GREEN_HEX  = '#3E8161'
YELLOW_HEX = '#C78E2B'

def hex_to_rgb(hex_str):
    h = hex_str.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def with_alpha(rgb, alpha=LABEL_ALPHA):
    return (rgb[0], rgb[1], rgb[2], alpha)

def get_label_bg_rgba(label_text: str):
    if label_text and label_text.startswith('1'):
        return with_alpha(hex_to_rgb(RED_HEX))
    if label_text and label_text.endswith('S'):
        return with_alpha(hex_to_rgb(YELLOW_HEX))
    return with_alpha(hex_to_rgb(GREEN_HEX))

# ======================
# 기능 함수
# ======================
def resize_image(image_path):
    img = Image.open(image_path).convert("RGBA")
    original_width, original_height = img.size
    scale_factor = TARGET_HEIGHT / original_height
    new_width = int(original_width * scale_factor)
    img = img.resize((new_width, TARGET_HEIGHT), resample=Image.LANCZOS)
    white_bg = Image.new("RGBA", (new_width, TARGET_HEIGHT), "WHITE")
    white_bg.paste(img, (0, 0), img)
    return white_bg.convert("RGB")

def get_random_question(student_name, student_folder):
    if os.path.exists(ASKED_QUESTIONS_FILE):
        with open(ASKED_QUESTIONS_FILE, "r", encoding="utf-8") as f:
            asked_questions = json.load(f)
    else:
        asked_questions = {}

    custom_path = os.path.join(student_folder, "custom_questions.json")
    if os.path.exists(custom_path):
        with open(custom_path, "r", encoding="utf-8") as f:
            custom_questions = json.load(f)
        if custom_questions:
            selected_question = custom_questions.pop(0)
            with open(custom_path, "w", encoding="utf-8") as f:
                json.dump(custom_questions, f, ensure_ascii=False, indent=2)
            asked_questions.setdefault(student_name, []).append(selected_question)
            with open(ASKED_QUESTIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(asked_questions, f, ensure_ascii=False, indent=2)
            return selected_question

    with open(QUESTION_FILE, "r", encoding="utf-8") as f:
        questions = json.load(f)

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
        wrapped = textwrap.fill(question_text, width=40)
        tb = draw.textbbox((0, 0), wrapped, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        if tw <= width - 20 and th <= height - 20:
            break
        max_font_size -= 2
    text_x = (width - tw) // 2
    text_y = (height - th) // 2
    draw.text((text_x, text_y), wrapped, fill="black", font=font)
    return box

def extract_chapter_label(image_path):
    return os.path.basename(os.path.dirname(image_path))

def draw_label_badge(base_image, x, y, text, bg_rgba):
    draw = ImageDraw.Draw(base_image, "RGBA")
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode Bold.ttf", LABEL_FONT_SIZE)
    except IOError:
        font = ImageFont.truetype(FONT_PATH, LABEL_FONT_SIZE)

    tb = draw.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    w = tw + LABEL_PAD_X * 2
    h = th + LABEL_PAD_Y * 2
    rect = (x, y, x + w, y + h)

    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(rect, radius=LABEL_CORNER, fill=bg_rgba)
    else:
        draw.rectangle(rect, fill=bg_rgba)

    draw.text((x + LABEL_PAD_X + 1, y + LABEL_PAD_Y - 6), text, font=font, fill=(0, 0, 0, 120))
    draw.text((x + LABEL_PAD_X,     y + LABEL_PAD_Y - 7), text, font=font, fill=LABEL_TEXT_RGBA)

def collect_students():
    results = []
    if os.path.isdir(FREE_PLAN_DIR):
        for name in os.listdir(FREE_PLAN_DIR):
            p = os.path.join(FREE_PLAN_DIR, name)
            if os.path.isdir(p):
                results.append((name, "free", p))
    if os.path.isdir(PAID_PLAN_DIR):
        for name in os.listdir(PAID_PLAN_DIR):
            p = os.path.join(PAID_PLAN_DIR, name)
            if os.path.isdir(p):
                results.append((name, "paid", p))
    return results

# =========================================================
# 이미지 선택 로직
# =========================================================
def select_and_update_images(image_paths, n):
    if not image_paths or n <= 0:
        return []

    dir_map = {}
    for p in image_paths:
        d = os.path.dirname(p)
        if d not in dir_map:
            dir_map[d] = []
        dir_map[d].append(p)

    candidates = []
    folders_data = {}

    for folder_path, paths in dir_map.items():
        json_path = os.path.join(folder_path, USAGE_LOG_FILE)
        history = {}
        
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except:
                history = {}

        for p in paths:
            fname = os.path.basename(p)
            if fname not in history:
                history[fname] = 0
        
        folders_data[folder_path] = {'path': json_path, 'data': history}

        for p in paths:
            fname = os.path.basename(p)
            candidates.append({
                'full_path': p,
                'folder': folder_path,
                'filename': fname,
                'count': history[fname]
            })

    random.shuffle(candidates)
    candidates.sort(key=lambda x: x['count'])
    
    selected_items = candidates[:n]
    
    for item in selected_items:
        folder = item['folder']
        fname = item['filename']
        folders_data[folder]['data'][fname] += 1
        
    for folder, info in folders_data.items():
        sorted_data = dict(sorted(info['data'].items()))
        with open(info['path'], 'w', encoding='utf-8') as f:
            json.dump(sorted_data, f, indent=2, ensure_ascii=False)
            
    return [item['full_path'] for item in selected_items]

# ======================
# 메인 플로우
# ======================
def generate_homework_for_all():
    students = collect_students()

    today_filename = datetime.today().strftime('%Y-%m-%d')
    today_display = datetime.today().strftime('%m/%d').lstrip("0").replace("/0", "/")
    existing_homework_files = set(os.listdir(BASE_FOLDER))

    for student_name, plan_type, student_folder in students:
        if any(student_name in f and f.endswith(".jpeg") for f in existing_homework_files):
            print(f"⏭️ {student_name}: 기존 숙제가 있어서 스킵.")
            continue

        output_filename = f"{today_filename}_{student_name}.jpeg"
        output_path = os.path.join(BASE_FOLDER, output_filename)

        current_path = os.path.join(student_folder, "현행 챕터")
        past_path    = os.path.join(student_folder, "지난 챕터")

        # ---------------------------------------------------------
        # [MODIFIED] '보류' 폴더 스킵 기능 강화 (맥 한글 자모 분리 대응)
        # ---------------------------------------------------------
        current_images = []
        for root, _, files in os.walk(current_path):
            # 경로를 NFC(완성형)로 변환 후 체크
            root_nfc = unicodedata.normalize('NFC', root)
            if "보류" in root_nfc:
                continue
            for f in files:
                if f.lower().endswith(('.jpeg', '.jpg', '.png')):
                    current_images.append(os.path.join(root, f))
        
        past_images = []
        for root, _, files in os.walk(past_path):
            # [FIX] 지난 챕터에도 동일한 스킵 로직 적용
            root_nfc = unicodedata.normalize('NFC', root)
            if "보류" in root_nfc:
                continue
            for f in files:
                if f.lower().endswith(('.jpeg', '.jpg', '.png')):
                    past_images.append(os.path.join(root, f))

        if plan_type == "free":
            target_current = 4
            target_past = 2
        else:
            target_current = 4
            target_past = 1

        pick_count_curr = min(len(current_images), target_current)
        selected_paths_curr = select_and_update_images(current_images, pick_count_curr)

        pick_count_past = min(len(past_images), target_past)
        selected_paths_past = select_and_update_images(past_images, pick_count_past)

        selected_paths = selected_paths_curr + selected_paths_past

        if not selected_paths:
            print(f"❌ {student_name}: 생성할 이미지가 하나도 없습니다 (현행/지난 모두 0개).")
            continue

        selected = [(p, extract_chapter_label(p)) for p in selected_paths]
        resized_images = [(resize_image(p), label) for p, label in selected]

        include_question = (plan_type == "paid")

        rows = len(resized_images) + (1 if include_question else 0)
        total_height = HEADER_HEIGHT + TARGET_HEIGHT * rows

        max_image_width = max(img.size[0] for img, _ in resized_images) if resized_images else 0
        final_width = max(max_image_width, TARGET_HEIGHT * GRID_COLS)
        
        final_image = Image.new("RGB", (final_width, total_height), "white")
        draw = ImageDraw.Draw(final_image)
        
        try:
            title_font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        except IOError:
            title_font = ImageFont.load_default()
        draw.text((10, 10), f"{student_name} {today_display}", fill="black", font=title_font)

        y_offset = HEADER_HEIGHT
        for img, label in resized_images:
            final_image.paste(img, (0, y_offset))
            bg_rgba = get_label_bg_rgba(str(label))
            draw_label_badge(final_image, LABEL_OFFSET_X, y_offset + LABEL_OFFSET_Y, str(label), bg_rgba)
            y_offset += TARGET_HEIGHT

        if include_question:
            question_text = get_random_question(student_name, student_folder)
            question_box = create_question_box(question_text, QUESTION_BOX_WIDTH, QUESTION_BOX_HEIGHT)
            final_image.paste(question_box, (0, y_offset))

        final_image.save(output_path, "JPEG")
        
        tag_parts = []
        if pick_count_curr > 0: tag_parts.append(f"현행{pick_count_curr}")
        if pick_count_past > 0: tag_parts.append(f"지난{pick_count_past}")
        if include_question: tag_parts.append("질문")
        tag = "+".join(tag_parts)

        print(f"✅ {student_name} ({tag}) 숙제 생성 완료: {output_path}")

if __name__ == "__main__":
    generate_homework_for_all()

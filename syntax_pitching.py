import os
import json
import random
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from datetime import datetime
import platform

# ==========================================
# [설정] 경로 및 디자인
# ==========================================
BASE_FOLDER = "/Users/seojaeyeong/Homework-Generation/Syntax Pitching"
HISTORY_FILE = "pitching_history.json"

# 이미지 설정
IMG_HEIGHT = 300
BORDER_WIDTH = 10 

# [디자인] 폰트
FONT_MAIN = "Hiragino Sans"
FONT_TITLE = (FONT_MAIN, 30)
FONT_TEXT = (FONT_MAIN, 14)
FONT_BTN = (FONT_MAIN, 16)
FONT_SMALL = (FONT_MAIN, 12)

# 색상
COLOR_BG = "#F0F0F0"
COLOR_SUCCESS = "#00FF00" 
COLOR_FAIL = "#FFD700" 
COLOR_DEFAULT = "#FFFFFF"

# 그래프/통계 색상
COLOR_BAR_HIGH = "#4CAF50" # 80~100 (초록)
COLOR_BAR_MID = "#FFC107"  # 40~60 (노랑)
COLOR_BAR_LOW = "#F44336"  # 0~20 (빨강)

class SyntaxPitchingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Syntax Pitching™ - Simulator")
        self.root.geometry("1100x900")
        self.root.configure(bg=COLOR_BG)

        # 데이터 초기화
        self.history_data = self.load_history()
        self.playlist = []
        self.current_img_index = 0
        self.failed_images = []
        
        # 상태 플래그
        self.is_retry_mode = False 
        self.input_locked = False

        # UI 프레임
        self.setup_frame = None
        self.pitch_frame = None
        self.result_frame = None
        self.data_frame = None

        # 초기 화면 실행
        self.build_setup_screen()


    def load_history(self):
        path = os.path.join(BASE_FOLDER, HISTORY_FILE)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_history(self):
        if not os.path.exists(BASE_FOLDER):
            os.makedirs(BASE_FOLDER)
        path = os.path.join(BASE_FOLDER, HISTORY_FILE)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.history_data, f, indent=4, ensure_ascii=False)

    # ============================================
    # 화면 1: 초기 설정 (Setup)
    # ============================================
    def build_setup_screen(self):
        for frame in [self.pitch_frame, self.result_frame, self.data_frame]:
            if frame: frame.destroy()

        self.setup_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(self.setup_frame, text="Syntax Pitching™", font=FONT_TITLE, bg=COLOR_BG).pack(pady=20)

        tk.Label(self.setup_frame, text="Select Player (Student)", font=FONT_TEXT, bg=COLOR_BG).pack(anchor="w")
        self.student_combo = ttk.Combobox(self.setup_frame, state="readonly", font=FONT_TEXT)
        self.student_combo.pack(fill="x", pady=5)
        self.student_combo.bind("<<ComboboxSelected>>", self.load_chapters)

        tk.Label(self.setup_frame, text="Select Chapters", font=FONT_TEXT, bg=COLOR_BG).pack(anchor="w", pady=(20, 0))
        self.chapter_listbox = tk.Listbox(self.setup_frame, selectmode="multiple", font=FONT_TEXT, height=10)
        self.chapter_listbox.pack(fill="both", expand=True, pady=5)

        btn_frame = tk.Frame(self.setup_frame, bg=COLOR_BG)
        btn_frame.pack(pady=30)
        
        tk.Button(btn_frame, text="Pitching Start", command=self.start_pitching, 
                  font=FONT_BTN, bg="black", fg="white", width=18, height=2).pack(side="left", padx=10)
        
        tk.Button(btn_frame, text="Watch Data", command=self.build_data_screen, 
                  font=FONT_BTN, bg="#DDDDDD", fg="black", width=18, height=2).pack(side="left", padx=10)

        self.load_students()

    def load_students(self):
        if not os.path.exists(BASE_FOLDER):
            os.makedirs(BASE_FOLDER)
            return
        students = [d for d in os.listdir(BASE_FOLDER) if os.path.isdir(os.path.join(BASE_FOLDER, d)) and not d.startswith('.')]
        self.student_combo['values'] = sorted(students)

    def load_chapters(self, event=None):
        student = self.student_combo.get()
        if not student: return
        student_path = os.path.join(BASE_FOLDER, student)
        self.chapter_listbox.delete(0, tk.END)
        self.chapter_map = [] 
        if not os.path.exists(student_path): return

        categories = [d for d in os.listdir(student_path) if os.path.isdir(os.path.join(student_path, d)) and not d.startswith('.')]
        for cat in sorted(categories):
            cat_path = os.path.join(student_path, cat)
            chapters = [ch for ch in os.listdir(cat_path) if os.path.isdir(os.path.join(cat_path, ch)) and not ch.startswith('.')]
            for ch in sorted(chapters):
                display_name = f"[{cat}] {ch}"
                full_path = os.path.join(cat_path, ch)
                self.chapter_listbox.insert(tk.END, display_name)
                self.chapter_map.append(full_path)

    # ============================================
    # 화면 2: 피칭 진행
    # ============================================
    def start_pitching(self):
        student = self.student_combo.get()
        selections = self.chapter_listbox.curselection()
        if not student or not selections:
            messagebox.showwarning("경고", "학생과 챕터를 선택해주세요.")
            return

        self.playlist = []
        for idx in selections:
            folder_path = self.chapter_map[idx]
            chapter_name = os.path.basename(folder_path)
            for file in os.listdir(folder_path):
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    self.playlist.append({
                        "path": os.path.join(folder_path, file),
                        "name": file,
                        "folder": chapter_name 
                    })
        
        if not self.playlist:
            messagebox.showerror("오류", "선택한 챕터에 이미지가 없습니다.")
            return

        random.shuffle(self.playlist)
        self.current_img_index = 0
        self.failed_images = []
        self.is_retry_mode = False 
        
        self.setup_frame.pack_forget()
        self.build_pitching_screen()
        self.show_next_image()

    def build_pitching_screen(self):
        self.pitch_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.pitch_frame.pack(fill="both", expand=True)

        self.info_label = tk.Label(self.pitch_frame, text="", font=(FONT_MAIN, 24), bg=COLOR_BG, fg="#333")
        self.info_label.pack(pady=(40, 10))

        self.img_container = tk.Frame(self.pitch_frame, bg=COLOR_BG, padx=BORDER_WIDTH, pady=BORDER_WIDTH)
        self.img_container.pack(expand=True)

        self.img_label = tk.Label(self.img_container, bg="white")
        self.img_label.pack()

        guide_text = "→ : 통과  |  ↓ : 미통과  |  ← : 뒤로가기 (Undo)"
        self.guide_label = tk.Label(self.pitch_frame, text=guide_text, font=FONT_TEXT, bg=COLOR_BG, fg="#888")
        self.guide_label.pack(pady=30)

        self.root.bind('<Right>', self.on_success)
        self.root.bind('<Down>', self.on_fail)
        self.root.bind('<Left>', self.on_undo)
        self.root.focus_set()

    def show_next_image(self):
        if self.is_retry_mode:
            self.show_retry_image()
            return
        if self.current_img_index >= len(self.playlist):
            self.finish_pitching()
            return

        current_data = self.playlist[self.current_img_index]
        self.display_image(current_data)

    def display_image(self, data):
        display_name = os.path.splitext(data['name'])[0]
        self.info_label.config(text=display_name)
        try:
            original_img = Image.open(data['path'])
            ratio = IMG_HEIGHT / float(original_img.size[1])
            new_width = int(float(original_img.size[0]) * ratio)
            resized_img = original_img.resize((new_width, IMG_HEIGHT), Image.Resampling.LANCZOS)
            self.tk_image = ImageTk.PhotoImage(resized_img)
            self.img_label.config(image=self.tk_image)
            self.img_container.config(bg=COLOR_BG)
            self.input_locked = False
        except Exception as e:
            print(f"이미지 로드 에러: {e}")
            if not self.is_retry_mode:
                self.current_img_index += 1
                self.show_next_image()

    def show_retry_image(self):
        if not self.failed_images:
            messagebox.showinfo("알림", "틀린 문제가 없습니다!")
            self.return_to_result()
            return
        current_data = random.choice(self.failed_images)
        self.display_image(current_data)

    def flash_border(self, color, callback):
        if self.input_locked: return
        self.input_locked = True
        self.img_container.config(bg=color)
        self.root.after(400, callback)

    def on_success(self, event=None):
        if self.input_locked: return
        if not self.is_retry_mode:
            self.record_result("O")
        self.flash_border(COLOR_SUCCESS, self.next_step)

    def on_fail(self, event=None):
        if self.input_locked: return
        if not self.is_retry_mode:
            self.record_result("X")
            self.failed_images.append(self.playlist[self.current_img_index])
        self.flash_border(COLOR_FAIL, self.next_step)

    def on_undo(self, event=None):
        if self.input_locked or self.is_retry_mode: return
        if self.current_img_index > 0:
            self.current_img_index -= 1
            self.rollback_result()
            current_data = self.playlist[self.current_img_index]
            if current_data in self.failed_images:
                self.failed_images.remove(current_data)
            self.show_next_image()

    def next_step(self):
        if not self.is_retry_mode:
            self.current_img_index += 1
        self.show_next_image()

    def record_result(self, result):
        student = self.student_combo.get()
        current_data = self.playlist[self.current_img_index]
        img_key = f"{current_data['folder']}/{current_data['name']}"

        if student not in self.history_data: self.history_data[student] = {}
        if img_key not in self.history_data[student]:
            self.history_data[student][img_key] = {"recent_history": [], "total_attempts": 0, "batting_average": 0.0}
        
        data = self.history_data[student][img_key]
        data["total_attempts"] += 1
        data["recent_history"].append(result)
        if len(data["recent_history"]) > 5: data["recent_history"].pop(0)
        self.update_average(data)
        data["last_played"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def rollback_result(self):
        student = self.student_combo.get()
        current_data = self.playlist[self.current_img_index]
        img_key = f"{current_data['folder']}/{current_data['name']}"
        if student in self.history_data and img_key in self.history_data[student]:
            data = self.history_data[student][img_key]
            if data["recent_history"]: data["recent_history"].pop()
            if data["total_attempts"] > 0: data["total_attempts"] -= 1
            self.update_average(data)

    def update_average(self, data):
        success_count = data["recent_history"].count("O")
        total_recent = len(data["recent_history"])
        data["batting_average"] = round(success_count / total_recent, 2) if total_recent > 0 else 0.0

    # ============================================
    # 화면 3: 결과 및 리셋 (스크롤 적용 버전)
    # ============================================
    def finish_pitching(self):
        self.save_history()
        self.root.unbind('<Right>')
        self.root.unbind('<Down>')
        self.root.unbind('<Left>')
        
        self.pitch_frame.destroy()
        self.pitch_frame = None
        self.is_retry_mode = False 
        
        self.result_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.result_frame.pack(fill="both", expand=True)

        # [NEW] 스크롤 컨테이너 생성
        canvas = tk.Canvas(self.result_frame, bg=COLOR_BG)
        scrollbar = tk.Scrollbar(self.result_frame, orient="vertical", command=canvas.yview)
        
        content_frame = tk.Frame(canvas, bg=COLOR_BG)
        content_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=content_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 꽉 채우기 위해 pack 설정
        canvas.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=20)
        scrollbar.pack(side="right", fill="y", padx=(0, 20), pady=20)

        # 1. 타이틀
        tk.Label(content_frame, text="피칭 완료! 수고하셨습니다.", font=FONT_TITLE, bg=COLOR_BG).pack(pady=(10, 20))

        # 2. Retry List
        if self.failed_images:
            tk.Label(content_frame, text="[Retry List]", font=FONT_BTN, fg="red", bg=COLOR_BG).pack(pady=(0, 10))
            # [수정] 3열 배치 (grid_cols=3)
            self.draw_grid_images(content_frame, self.failed_images, show_stats=False, grid_cols=3)
        else:
            tk.Label(content_frame, text="Perfect Game! 🎉", font=(FONT_MAIN, 20), fg=COLOR_SUCCESS, bg=COLOR_BG).pack(pady=20)

        # 3. 버튼
        btn_area = tk.Frame(content_frame, bg=COLOR_BG)
        btn_area.pack(pady=20)

        tk.Button(btn_area, text="메인으로 (Home)", command=self.build_setup_screen, 
                  font=FONT_BTN, width=15).pack(side="left", padx=10)
        
        state = "normal" if self.failed_images else "disabled"
        tk.Button(btn_area, text="미통과 구간 연습", command=self.start_retry_mode, 
                  font=FONT_BTN, width=20, fg="black", state=state).pack(side="left", padx=10)

        # 4. 그래프
        self.draw_graph_frame(content_frame, self.playlist)
        
        # 하단 여백 확보
        tk.Label(content_frame, text=" ", bg=COLOR_BG).pack(pady=20)

    # [중요] 그리드 이미지 그리기 (행간 삭제 버전)
    def draw_grid_images(self, parent, img_list, show_stats=False, grid_cols=3):
        grid_frame = tk.Frame(parent, bg=COLOR_BG)
        grid_frame.pack()

        limit = 12 if not show_stats else 9999
        count = 0
        
        for idx, data in enumerate(img_list):
            if count >= limit: break
            try:
                thumb_h = 100
                orig = Image.open(data['path'])
                ratio = thumb_h / float(orig.size[1])
                new_w = int(float(orig.size[0]) * ratio)
                img = ImageTk.PhotoImage(orig.resize((new_w, thumb_h), Image.Resampling.LANCZOS))

                card = tk.Frame(grid_frame, bg="white", bd=1, relief="solid")
                r, c = (count // grid_cols, count % grid_cols)
                card.grid(row=r, column=c, padx=10, pady=10)
                
                lbl_img = tk.Label(card, image=img, bg="white", bd=0)
                lbl_img.image = img
                lbl_img.pack(pady=0) # 여백 삭제
                
                name_only = os.path.splitext(data['name'])[0]
                # [수정] bd=0, highlightthickness=0 으로 경계 제거 및 밀착
                tk.Label(card, text=name_only, font=FONT_SMALL, bg="white", bd=0, highlightthickness=0).pack(pady=(5,0))

                if show_stats:
                    stats = self.get_img_stats(data)
                    
                    fg_color = COLOR_BAR_LOW
                    if stats['avg'] >= 0.8: fg_color = COLOR_BAR_HIGH
                    elif stats['avg'] >= 0.4: fg_color = COLOR_BAR_MID

                    # [수정] 모든 텍스트 라벨을 '꽉' 붙임
                    tk.Label(card, text=f"Total Tries: {stats['total']}", font=FONT_SMALL, bg="white", fg="#555", bd=0, highlightthickness=0).pack(pady=0)
                    
                    recent_str = " ".join(stats['history']) if stats['history'] else "-"
                    tk.Label(card, text=recent_str, font=FONT_SMALL, bg="white", fg=fg_color, bd=0, highlightthickness=0).pack(pady=0)

                    rate_pct = int(stats['avg']*100)
                    tk.Label(card, text=f"Batting Rate: {rate_pct}%", font=FONT_SMALL, bg="white", fg=fg_color, bd=0, highlightthickness=0).pack(pady=(0,5))

                count += 1
            except:
                continue

    def get_img_stats(self, data):
        student = self.student_combo.get()
        img_key = f"{data['folder']}/{data['name']}"
        if student in self.history_data and img_key in self.history_data[student]:
            d = self.history_data[student][img_key]
            return {"avg": d["batting_average"], "total": d["total_attempts"], "history": d["recent_history"]}
        return {"avg": 0.0, "total": 0, "history": []}

    def draw_graph_frame(self, parent, playlist):
        tk.Label(parent, text="[Batting Rate]", font=FONT_BTN, bg=COLOR_BG, fg="#555").pack(pady=(10, 5))
        
        graph_h = 200 
        canvas_frame = tk.Frame(parent, bg="white", bd=1, relief="solid")
        canvas_frame.pack(fill="x", pady=10, padx=20)
        
        played_keys = sorted(list(set([f"{p['folder']}/{p['name']}" for p in playlist])))
        if not played_keys: return

        bar_width = 40
        gap = 20
        total_w = max(900, len(played_keys) * (bar_width + gap) + 50)
        
        canvas = tk.Canvas(canvas_frame, height=graph_h, width=total_w, bg="white")
        scroll_x = tk.Scrollbar(canvas_frame, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=scroll_x.set)
        
        canvas.pack(side="top", fill="both", expand=True)
        scroll_x.pack(side="bottom", fill="x")
        canvas.config(scrollregion=(0, 0, total_w, graph_h))

        student = self.student_combo.get()
        x_start = 30
        max_bar_h = 140
        base_y = 170
        
        for i, key in enumerate(played_keys):
            avg = 0.0
            if student in self.history_data and key in self.history_data[student]:
                avg = self.history_data[student][key]["batting_average"]
            
            bar_h = int(avg * max_bar_h)
            x0 = x_start + i * (bar_width + gap)
            y0 = base_y - bar_h
            x1 = x0 + bar_width
            y1 = base_y
            
            if avg >= 0.8: color = COLOR_BAR_HIGH 
            elif avg >= 0.4: color = COLOR_BAR_MID 
            else: color = COLOR_BAR_LOW 
            
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
            canvas.create_text((x0+x1)/2, y0-10, text=f"{int(avg*100)}%", font=FONT_SMALL, fill="#333")
            
            fname = key.split("/")[-1].replace(".png","").replace(".jpg","")
            short_name = fname.split("_")[0] if "_" in fname else fname
            canvas.create_text((x0+x1)/2, base_y+15, text=short_name, font=FONT_SMALL, fill="#555")

    # ============================================
    # 화면 4: 데이터 관제 (Watch Data)
    # ============================================
    def build_data_screen(self):
        student = self.student_combo.get()
        selections = self.chapter_listbox.curselection()

        if not student:
            messagebox.showwarning("경고", "데이터를 확인할 학생을 먼저 선택해주세요.")
            return
        if len(selections) != 1:
            messagebox.showwarning("경고", "Watch Data는 정확한 분석을 위해\n한 번에 '한 개의 챕터'만 선택해주세요.")
            return
        
        idx = selections[0]
        full_chapter_name = self.chapter_listbox.get(idx)
        clean_chapter_name = full_chapter_name.split("] ")[-1] if "] " in full_chapter_name else full_chapter_name

        self.setup_frame.pack_forget()
        self.data_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.data_frame.pack(fill="both", expand=True)

        header = tk.Frame(self.data_frame, bg=COLOR_BG)
        header.pack(fill="x", pady=20, padx=20)
        
        tk.Label(header, text=f"{student} / {clean_chapter_name}", font=FONT_TITLE, bg=COLOR_BG).pack(side="left")
        tk.Button(header, text="Back to Home", command=self.build_setup_screen, font=FONT_BTN, width=15).pack(side="right")

        # 스크롤 영역
        container = tk.Frame(self.data_frame, bg=COLOR_BG)
        container.pack(fill="both", expand=True, padx=20, pady=10)
        
        self.data_canvas = tk.Canvas(container, bg=COLOR_BG) 
        scrollbar = tk.Scrollbar(container, orient="vertical", command=self.data_canvas.yview)
        scrollable_frame = tk.Frame(self.data_canvas, bg=COLOR_BG)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: self.data_canvas.configure(scrollregion=self.data_canvas.bbox("all"))
        )
        self.data_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        self.data_canvas.configure(yscrollcommand=scrollbar.set)

        self.data_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 데이터 로드
        chapter_path = self.chapter_map[idx]
        all_files = []
        
        if os.path.exists(chapter_path):
            folder_name = os.path.basename(chapter_path)
            for file in os.listdir(chapter_path):
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    all_files.append({
                        "path": os.path.join(chapter_path, file),
                        "name": file,
                        "folder": folder_name
                    })
        
        all_files.sort(key=lambda x: x['name'])

        if not all_files:
            tk.Label(scrollable_frame, text="이 챕터에 이미지가 없습니다.", font=FONT_TEXT, bg=COLOR_BG).pack(pady=50)
        else:
            self.draw_grid_images(scrollable_frame, all_files, show_stats=True, grid_cols=3)
            
            tk.Label(scrollable_frame, text=" ", bg=COLOR_BG).pack(pady=10)
            self.draw_graph_frame(scrollable_frame, all_files)
            tk.Label(scrollable_frame, text=" ", bg=COLOR_BG).pack(pady=20)

    # ============================================
    # 화면 5: 재연습 모드
    # ============================================
    def start_retry_mode(self):
        self.result_frame.pack_forget()
        self.is_retry_mode = True
        
        self.pitch_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.pitch_frame.pack(fill="both", expand=True)

        tk.Label(self.pitch_frame, text="미통과 구간 연습", font=("Hiragino Sans", 20), bg=COLOR_BG, fg="black").pack(pady=20)
        
        self.info_label = tk.Label(self.pitch_frame, text="", font=(FONT_MAIN, 24), bg=COLOR_BG, fg="#333")
        self.info_label.pack(pady=10)

        self.img_container = tk.Frame(self.pitch_frame, bg=COLOR_BG, padx=BORDER_WIDTH, pady=BORDER_WIDTH)
        self.img_container.pack(expand=True)

        self.img_label = tk.Label(self.img_container, bg="white")
        self.img_label.pack()

        tk.Label(self.pitch_frame, text="→ : 통과  |  ↓ : 다시 (기록 안됨)", font=FONT_TEXT, bg=COLOR_BG, fg="#888").pack(pady=20)

        tk.Button(self.pitch_frame, text="이전 화면 (Back to Result)", command=self.return_to_result, 
                  font=FONT_BTN, width=25).pack(pady=20)

        self.root.bind('<Right>', self.on_success)
        self.root.bind('<Down>', self.on_fail)
        self.root.unbind('<Left>') 
        self.root.focus_set()
        
        self.show_retry_image()

    def return_to_result(self):
        self.pitch_frame.destroy()
        self.finish_pitching()


if __name__ == "__main__":
    root = tk.Tk()
    app = SyntaxPitchingApp(root)
    root.mainloop()

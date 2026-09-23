import os
import json
import random
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageDraw
from datetime import datetime

# ==========================================
# [설정] 경로 및 디자인
# ==========================================
BASE_FOLDER = "/Users/seojaeyeong/숙제 생성/Syntax Pitching"
HISTORY_FILE = "pitching_history.json"

# 이미지 설정
IMG_HEIGHT = 300
BORDER_WIDTH = 10 

# [디자인] 폰트
FONT_MAIN = "Hiragino Sans"
FONT_TITLE = (FONT_MAIN, 30, "bold")
FONT_TEXT = (FONT_MAIN, 14)
FONT_BOLD = (FONT_MAIN, 16, "bold")
FONT_SMALL = (FONT_MAIN, 10)

# 색상
COLOR_BG = "#F0F0F0"
COLOR_SUCCESS = "#00FF00" 
COLOR_FAIL = "#FFD700" 
COLOR_DEFAULT = "#FFFFFF"
COLOR_BAR_HIGH = "#4CAF50" # 타율 높음 (초록)
COLOR_BAR_LOW = "#F44336"  # 타율 낮음 (빨강)

class SyntaxPitchingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Syntax Pitching™ - Simulator")
        self.root.geometry("1000x850") # 그래프 공간 확보를 위해 조금 늘림
        self.root.configure(bg=COLOR_BG)

        # 데이터 초기화
        self.history_data = self.load_history()
        self.playlist = []
        self.current_img_index = 0
        self.failed_images = []
        
        # 상태 플래그
        self.is_retry_mode = False # 재연습 모드 여부
        self.input_locked = False

        # UI 프레임
        self.setup_frame = None
        self.pitch_frame = None
        self.result_frame = None
        self.retry_frame = None

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
        # 기존 프레임 정리
        for frame in [self.pitch_frame, self.result_frame, self.retry_frame]:
            if frame: frame.destroy()

        self.setup_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(self.setup_frame, text="Syntax Pitching™", font=FONT_TITLE, bg=COLOR_BG).pack(pady=20)

        tk.Label(self.setup_frame, text="Select Player (Student)", font=FONT_TEXT, bg=COLOR_BG).pack(anchor="w")
        self.student_combo = ttk.Combobox(self.setup_frame, state="readonly", font=FONT_TEXT)
        self.student_combo.pack(fill="x", pady=5)
        self.student_combo.bind("<<ComboboxSelected>>", self.load_chapters)

        tk.Label(self.setup_frame, text="Select Chapters (Multiple Selection)", font=FONT_TEXT, bg=COLOR_BG).pack(anchor="w", pady=(20, 0))
        self.chapter_listbox = tk.Listbox(self.setup_frame, selectmode="multiple", font=FONT_TEXT, height=10)
        self.chapter_listbox.pack(fill="both", expand=True, pady=5)

        btn_frame = tk.Frame(self.setup_frame, bg=COLOR_BG)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="PITCHING START", command=self.start_pitching, 
                  font=FONT_BOLD, bg="black", fg="white", width=20, height=2).pack()

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
    # 화면 2: 피칭 진행 (Pitching)
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
        self.is_retry_mode = False # 정규 모드
        
        self.setup_frame.pack_forget()
        self.build_pitching_screen()
        self.show_next_image()

    def build_pitching_screen(self):
        self.pitch_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.pitch_frame.pack(fill="both", expand=True)

        self.info_label = tk.Label(self.pitch_frame, text="", font=(FONT_MAIN, 24, "bold"), bg=COLOR_BG, fg="#333")
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
        self.root.bind('<Left>', self.on_undo) # 뒤로가기 추가
        self.root.focus_set()

    def show_next_image(self):
        # [모드 분기] 재연습 모드일 때
        if self.is_retry_mode:
            self.show_retry_image()
            return

        # [모드 분기] 정규 모드일 때
        if self.current_img_index >= len(self.playlist):
            self.finish_pitching()
            return

        current_data = self.playlist[self.current_img_index]
        self.display_image(current_data)

    def display_image(self, data):
        """실제 이미지를 화면에 그리는 공통 함수"""
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
        """재연습 모드: 랜덤으로 무한 재생"""
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
        self.root.after(400, callback) # 속도감 있게 0.4초

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
        """[NEW] 뒤로가기 및 기록 삭제"""
        if self.input_locked or self.is_retry_mode: return
        
        if self.current_img_index > 0:
            self.current_img_index -= 1
            # 기록 삭제 (Rollback)
            self.rollback_result()
            # 미통과 리스트에 있다면 제거 (방금 X였다가 취소하는 경우)
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
        """방금 기록한 데이터를 삭제 (Undo 로직)"""
        student = self.student_combo.get()
        current_data = self.playlist[self.current_img_index]
        img_key = f"{current_data['folder']}/{current_data['name']}"

        if student in self.history_data and img_key in self.history_data[student]:
            data = self.history_data[student][img_key]
            if data["recent_history"]:
                data["recent_history"].pop() # 마지막 기록 삭제
            if data["total_attempts"] > 0:
                data["total_attempts"] -= 1
            self.update_average(data)

    def update_average(self, data):
        success_count = data["recent_history"].count("O")
        total_recent = len(data["recent_history"])
        data["batting_average"] = round(success_count / total_recent, 2) if total_recent > 0 else 0.0

    # ============================================
    # 화면 3: 결과 및 리셋 (Result)
    # ============================================
    def finish_pitching(self):
        self.save_history()
        self.root.unbind('<Right>')
        self.root.unbind('<Down>')
        self.root.unbind('<Left>')
        
        self.pitch_frame.destroy()
        self.pitch_frame = None
        self.is_retry_mode = False # 모드 초기화
        
        self.result_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.result_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 1. 상단 타이틀
        tk.Label(self.result_frame, text="피칭 완료! 수고하셨습니다.", font=FONT_TITLE, bg=COLOR_BG).pack(pady=(10, 20))

        # 2. 버튼 영역 (메인으로 / 무한 재연습)
        btn_area = tk.Frame(self.result_frame, bg=COLOR_BG)
        btn_area.pack(pady=10)

        tk.Button(btn_area, text="메인으로 (Home)", command=self.build_setup_screen, 
                  font=FONT_BOLD, width=15).pack(side="left", padx=10)
        
        # 재연습 버튼 (틀린 게 있을 때만 활성화)
        state = "normal" if self.failed_images else "disabled"
        tk.Button(btn_area, text="🔥 놓친 구간 무한 루프", command=self.start_retry_mode, 
                  font=FONT_BOLD, width=20, fg="red", state=state).pack(side="left", padx=10)

        # 3. 그래프 영역 (Canvas)
        self.draw_graph_frame(self.result_frame)

    def draw_graph_frame(self, parent):
        """[NEW] 타율 그래프 그리기"""
        tk.Label(parent, text="[Batting Rate Analysis]", font=FONT_BOLD, bg=COLOR_BG, fg="#555").pack(pady=(20, 5))
        
        # 캔버스 프레임
        graph_h = 250
        canvas_frame = tk.Frame(parent, bg="white", bd=1, relief="solid")
        canvas_frame.pack(fill="x", pady=10)
        
        # 데이터 준비 (파일명 순 정렬)
        student = self.student_combo.get()
        # 이번 세션에 플레이한 파일들만 추출해서 중복 제거 후 정렬
        played_keys = sorted(list(set([f"{p['folder']}/{p['name']}" for p in self.playlist])))
        
        if not played_keys: return

        # 캔버스 생성
        bar_width = 40
        gap = 20
        total_w = max(900, len(played_keys) * (bar_width + gap) + 50)
        
        canvas = tk.Canvas(canvas_frame, height=graph_h, width=total_w, bg="white")
        
        # 스크롤바 (데이터가 많을 경우 대비)
        scroll_x = tk.Scrollbar(canvas_frame, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=scroll_x.set)
        canvas.pack(side="top", fill="both", expand=True)
        scroll_x.pack(side="bottom", fill="x")
        
        canvas.config(scrollregion=(0, 0, total_w, graph_h))

        # 그래프 그리기
        x_start = 30
        max_bar_h = 180
        base_y = 220
        
        for i, key in enumerate(played_keys):
            # 타율 가져오기
            avg = 0.0
            if student in self.history_data and key in self.history_data[student]:
                avg = self.history_data[student][key]["batting_average"]
            
            bar_h = int(avg * max_bar_h)
            x0 = x_start + i * (bar_width + gap)
            y0 = base_y - bar_h
            x1 = x0 + bar_width
            y1 = base_y
            
            color = COLOR_BAR_HIGH if avg >= 0.8 else (COLOR_BAR_LOW if avg < 0.5 else "#FFC107") # 노랑
            
            # 막대
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
            # 수치 텍스트
            canvas.create_text((x0+x1)/2, y0-10, text=f"{int(avg*100)}%", font=FONT_SMALL, fill="#333")
            # 파일명 (1-1 등) - 폴더명 제외하고 파일명만
            fname = key.split("/")[-1].replace(".png","").replace(".jpg","")
            # 너무 길면 자르기
            short_name = fname.split("_")[0] if "_" in fname else fname
            canvas.create_text((x0+x1)/2, base_y+15, text=short_name, font=FONT_SMALL, fill="#555")

    # ============================================
    # 화면 4: 재연습 모드 (Retry Loop)
    # ============================================
    def start_retry_mode(self):
        self.result_frame.pack_forget()
        self.is_retry_mode = True
        
        self.pitch_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.pitch_frame.pack(fill="both", expand=True)

        # 재연습 UI
        tk.Label(self.pitch_frame, text="🔥 놓친 구간 무한 루프 🔥", font=("Hiragino Sans", 20, "bold"), bg=COLOR_BG, fg="red").pack(pady=20)
        
        self.info_label = tk.Label(self.pitch_frame, text="", font=(FONT_MAIN, 24, "bold"), bg=COLOR_BG, fg="#333")
        self.info_label.pack(pady=10)

        self.img_container = tk.Frame(self.pitch_frame, bg=COLOR_BG, padx=BORDER_WIDTH, pady=BORDER_WIDTH)
        self.img_container.pack(expand=True)

        self.img_label = tk.Label(self.img_container, bg="white")
        self.img_label.pack()

        tk.Label(self.pitch_frame, text="→ : 통과  |  ↓ : 다시 (기록 안됨)", font=FONT_TEXT, bg=COLOR_BG, fg="#888").pack(pady=20)

        # 하단 탈출 버튼
        tk.Button(self.pitch_frame, text="이전 화면 (Back to Result)", command=self.return_to_result, 
                  font=FONT_BOLD, width=25).pack(pady=20)

        self.root.bind('<Right>', self.on_success)
        self.root.bind('<Down>', self.on_fail)
        self.root.unbind('<Left>') # 재연습에선 언두 필요 없음 (어차피 무한이라)
        self.root.focus_set()
        
        self.show_retry_image()

    def return_to_result(self):
        """재연습 종료 후 결과 화면 복귀"""
        self.pitch_frame.destroy()
        self.finish_pitching() # 결과 화면 다시 로드 (그래프 등)


if __name__ == "__main__":
    root = tk.Tk()
    app = SyntaxPitchingApp(root)
    root.mainloop()

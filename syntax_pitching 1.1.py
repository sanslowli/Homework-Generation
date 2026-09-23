import os
import json
import random
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from datetime import datetime

# ==========================================
# [설정] 경로 및 디자인
# ==========================================
# 재영님 맥북 경로 (수정 금지)
BASE_FOLDER = "/Users/seojaeyeong/숙제 생성/Syntax Pitching"
HISTORY_FILE = "pitching_history.json"

# 이미지 설정
IMG_HEIGHT = 300
BORDER_WIDTH = 10  # 테두리 두께 (px)

# [중요] 맥북 한글 깨짐 방지 폰트 설정
# AppleGothic은 맥북 기본 한글 폰트입니다.
FONT_MAIN = "AppleGothic" 
FONT_TITLE = (FONT_MAIN, 30, "bold")
FONT_TEXT = (FONT_MAIN, 14)
FONT_BOLD = (FONT_MAIN, 16, "bold")

# 색상
COLOR_BG = "#F0F0F0"
COLOR_SUCCESS = "#00FF00"  # 초록 (통과)
COLOR_FAIL = "#FFD700"     # 노랑 (미통과)
COLOR_DEFAULT = "#FFFFFF"  # 기본

class SyntaxPitchingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Syntax Pitching™ - Simulator")
        self.root.geometry("1000x800")
        self.root.configure(bg=COLOR_BG)

        # 데이터 초기화
        self.history_data = self.load_history()
        self.playlist = []
        self.current_img_index = 0
        self.failed_images = [] 

        # === 1. 초기 화면 (설정) ===
        self.setup_frame = tk.Frame(root, bg=COLOR_BG)
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 타이틀
        tk.Label(self.setup_frame, text="Syntax Pitching™", font=FONT_TITLE, bg=COLOR_BG).pack(pady=20)

        # 학습자 선택
        tk.Label(self.setup_frame, text="Select Player (Student)", font=FONT_TEXT, bg=COLOR_BG).pack(anchor="w")
        self.student_combo = ttk.Combobox(self.setup_frame, state="readonly", font=FONT_TEXT)
        self.student_combo.pack(fill="x", pady=5)
        self.student_combo.bind("<<ComboboxSelected>>", self.load_chapters)

        # 챕터 선택
        tk.Label(self.setup_frame, text="Select Chapters (Multiple Selection)", font=FONT_TEXT, bg=COLOR_BG).pack(anchor="w", pady=(20, 0))
        
        self.chapter_listbox = tk.Listbox(self.setup_frame, selectmode="multiple", font=FONT_TEXT, height=10)
        self.chapter_listbox.pack(fill="both", expand=True, pady=5)

        # 시작 버튼
        btn_frame = tk.Frame(self.setup_frame, bg=COLOR_BG)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="PITCHING START", command=self.start_pitching, 
                  font=FONT_BOLD, bg="black", fg="white", width=20, height=2).pack()

        # 학생 목록 로드
        self.load_students()


    def load_history(self):
        if os.path.exists(os.path.join(BASE_FOLDER, HISTORY_FILE)):
            try:
                with open(os.path.join(BASE_FOLDER, HISTORY_FILE), "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_history(self):
        if not os.path.exists(BASE_FOLDER):
            os.makedirs(BASE_FOLDER)
        with open(os.path.join(BASE_FOLDER, HISTORY_FILE), "w", encoding="utf-8") as f:
            json.dump(self.history_data, f, indent=4, ensure_ascii=False)

    def load_students(self):
        if not os.path.exists(BASE_FOLDER):
            os.makedirs(BASE_FOLDER)
            messagebox.showinfo("알림", f"폴더가 없어서 생성했습니다.\n{BASE_FOLDER}\n이 안에 학생 폴더와 이미지를 넣어주세요.")
            return

        students = [d for d in os.listdir(BASE_FOLDER) if os.path.isdir(os.path.join(BASE_FOLDER, d)) and not d.startswith('.')]
        self.student_combo['values'] = sorted(students)

    def load_chapters(self, event=None):
        student = self.student_combo.get()
        if not student: return

        student_path = os.path.join(BASE_FOLDER, student)
        self.chapter_listbox.delete(0, tk.END)
        self.chapter_map = [] 

        if not os.path.exists(student_path):
            return

        categories = [d for d in os.listdir(student_path) if os.path.isdir(os.path.join(student_path, d)) and not d.startswith('.')]
        
        for cat in sorted(categories):
            cat_path = os.path.join(student_path, cat)
            chapters = [ch for ch in os.listdir(cat_path) if os.path.isdir(os.path.join(cat_path, ch)) and not ch.startswith('.')]
            
            for ch in sorted(chapters):
                display_name = f"[{cat}] {ch}"
                full_path = os.path.join(cat_path, ch)
                self.chapter_listbox.insert(tk.END, display_name)
                self.chapter_map.append(full_path)

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
        
        self.setup_frame.pack_forget()
        self.build_pitching_screen()
        self.show_next_image()

    def build_pitching_screen(self):
        self.pitch_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.pitch_frame.pack(fill="both", expand=True)

        # 상단 파일명 (한글 폰트 적용)
        self.info_label = tk.Label(self.pitch_frame, text="", font=(FONT_MAIN, 24, "bold"), bg=COLOR_BG, fg="#333")
        self.info_label.pack(pady=(50, 10))

        self.img_container = tk.Frame(self.pitch_frame, bg=COLOR_BG, padx=BORDER_WIDTH, pady=BORDER_WIDTH)
        self.img_container.pack(expand=True)

        self.img_label = tk.Label(self.img_container, bg="white")
        self.img_label.pack()

        # 안내 문구
        guide_text = "→ : 통과 (Success)  |  ↓ : 미통과 (Retry)"
        tk.Label(self.pitch_frame, text=guide_text, font=FONT_TEXT, bg=COLOR_BG, fg="#888").pack(pady=30)

        self.root.bind('<Right>', self.on_success)
        self.root.bind('<Down>', self.on_fail)
        self.root.focus_set()

    def show_next_image(self):
        if self.current_img_index >= len(self.playlist):
            self.finish_pitching()
            return

        current_data = self.playlist[self.current_img_index]
        
        display_name = os.path.splitext(current_data['name'])[0]
        self.info_label.config(text=display_name)

        try:
            original_img = Image.open(current_data['path'])
            ratio = IMG_HEIGHT / float(original_img.size[1])
            new_width = int(float(original_img.size[0]) * ratio)
            
            # [수정] Pillow 최신 버전 호환 (LANCZOS)
            resized_img = original_img.resize((new_width, IMG_HEIGHT), Image.Resampling.LANCZOS)
            self.tk_image = ImageTk.PhotoImage(resized_img)

            self.img_label.config(image=self.tk_image)
            self.img_container.config(bg=COLOR_BG)
            
            self.input_locked = False
        except Exception as e:
            print(f"이미지 로드 에러: {e}")
            self.next_step()

    def flash_border(self, color, callback):
        if self.input_locked: return
        self.input_locked = True
        self.img_container.config(bg=color)
        self.root.after(500, callback)

    def on_success(self, event=None):
        if self.input_locked: return
        self.record_result("O")
        self.flash_border(COLOR_SUCCESS, self.next_step)

    def on_fail(self, event=None):
        if self.input_locked: return
        self.record_result("X")
        self.failed_images.append(self.playlist[self.current_img_index])
        self.flash_border(COLOR_FAIL, self.next_step)

    def next_step(self):
        self.current_img_index += 1
        self.show_next_image()

    def record_result(self, result):
        student = self.student_combo.get()
        current_data = self.playlist[self.current_img_index]
        img_key = f"{current_data['folder']}/{current_data['name']}"

        if student not in self.history_data:
            self.history_data[student] = {}
        
        if img_key not in self.history_data[student]:
            self.history_data[student][img_key] = {
                "recent_history": [],
                "total_attempts": 0,
                "batting_average": 0.0,
                "last_played": ""
            }
        
        data = self.history_data[student][img_key]
        data["total_attempts"] += 1
        data["recent_history"].append(result)
        if len(data["recent_history"]) > 5:
            data["recent_history"].pop(0)
        
        success_count = data["recent_history"].count("O")
        total_recent = len(data["recent_history"])
        
        if total_recent > 0:
            data["batting_average"] = round(success_count / total_recent, 2)
        else:
            data["batting_average"] = 0.0

        data["last_played"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def finish_pitching(self):
        self.save_history()
        self.root.unbind('<Right>')
        self.root.unbind('<Down>')
        
        self.pitch_frame.pack_forget()
        
        res_frame = tk.Frame(self.root, bg=COLOR_BG)
        res_frame.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(res_frame, text="피칭 완료! 수고하셨습니다.", font=FONT_TITLE, bg=COLOR_BG).pack(pady=30)

        if self.failed_images:
            tk.Label(res_frame, text="[Retry List]", font=FONT_BOLD, fg="red", bg=COLOR_BG).pack(pady=(0, 20))
            
            grid_frame = tk.Frame(res_frame, bg=COLOR_BG)
            grid_frame.pack()

            count = 0
            for idx, data in enumerate(self.failed_images):
                if count >= 12: break

                try:
                    thumb_h = 100
                    orig = Image.open(data['path'])
                    ratio = thumb_h / float(orig.size[1])
                    new_w = int(float(orig.size[0]) * ratio)
                    img = ImageTk.PhotoImage(orig.resize((new_w, thumb_h), Image.Resampling.LANCZOS))

                    card = tk.Frame(grid_frame, bg="white", bd=1, relief="solid")
                    card.grid(row=count//4, column=count%4, padx=10, pady=10)
                    
                    lbl_img = tk.Label(card, image=img, bg="white")
                    lbl_img.image = img
                    lbl_img.pack()
                    
                    name_only = os.path.splitext(data['name'])[0]
                    # 한글 폰트 적용
                    lbl_text = tk.Label(card, text=name_only, font=(FONT_MAIN, 12), bg="white")
                    lbl_text.pack()

                    count += 1
                except:
                    continue
        else:
            tk.Label(res_frame, text="Perfect Game! 🎉", font=(FONT_MAIN, 20), fg=COLOR_SUCCESS, bg=COLOR_BG).pack(pady=50)

        tk.Button(res_frame, text="종료 (Exit)", command=self.root.quit, font=FONT_BOLD, width=15).pack(pady=30)


if __name__ == "__main__":
    root = tk.Tk()
    app = SyntaxPitchingApp(root)
    root.mainloop()

#!/usr/bin/env python3
"""
BBT O/X 자동클릭 프로그램  —  auto_click_debug.py
Phase 1: X_BLACK 감지 → 즉시 클릭  /  O_BLACK·Ban → 무시
단축키 F9 : 캡처 → 추론 → 일괄 클릭
"""

import os
import sys
import json
import queue
import threading
import time
from datetime import datetime
from ctypes import windll

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from PIL import Image, ImageTk

# DPI 스케일 보정 (물리 픽셀 기준 좌표 사용)
try:
    windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ── 선택적 라이브러리 ─────────────────────────────────────────
try:
    import mss
    import mss.tools
except ImportError:
    mss = None

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import pydirectinput
    pydirectinput.PAUSE = 0
except ImportError:
    pydirectinput = None

try:
    import keyboard as kb
except ImportError:
    kb = None

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

# ── 상수 ─────────────────────────────────────────────────────
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings_autoclicker.json")
APP_TITLE = "BBT 자동클릭"
VERSION   = "1.0"

DEFAULT_SIM_FOLDER = (
    r"D:\VIBE\데이터 셋\3차 라벨링_260609"
    r"\1. O_BLACK과 X_BLACK과 BAN 만 적용 260604_OX_BLACK\train\images"
)

DEFAULT_SETTINGS: dict = {
    "weight_path":     "",
    "device":          "cpu",
    "conf":            0.50,
    "iou":             0.45,
    "imgsz":           320,
    "click_order":     "top_left",
    "capture_region":  None,
    "window_geometry": "480x920+0+0",
    "always_on_top":   True,
    "dark_mode":       False,
    "hotkey":          "f9",
    "sim_folder":      DEFAULT_SIM_FOLDER,
}

CLICK_ORDER_KEYS    = ["top_left",       "left_top",       "confidence"]
CLICK_ORDER_LABELS  = ["위→아래 / 좌→우", "좌→우 / 위→아래", "Confidence 높은 순"]

# 클래스 색상 (BGR → draw용 RGB)
CLS_COLOR = {
    "X_BLACK": (50, 220, 50),    # 초록
    "O_BLACK": (255, 160, 30),   # 주황
    "Ban":     (80, 140, 255),   # 파랑
}

# ── 테마 팔레트 ───────────────────────────────────────────────
THEMES = {
    "dark": dict(
        bg="#1e1e1e", fg="#e0e0e0",
        panel="#2d2d2d", entry="#3c3c3c",
        btn="#404040", btn_fg="#e0e0e0",
        accent="#0078d4", log_bg="#141414",
        preview_bg="#111111", tag_ok="#2ecc71",
        tag_warn="#e67e22", tag_err="#e74c3c", tag_info="#3498db",
    ),
    "light": dict(
        bg="#f0f0f0", fg="#1e1e1e",
        panel="#e0e0e0", entry="#ffffff",
        btn="#d0d0d0", btn_fg="#1e1e1e",
        accent="#0078d4", log_bg="#ffffff",
        preview_bg="#cccccc", tag_ok="#1a7a40",
        tag_warn="#b7600a", tag_err="#c0392b", tag_info="#1a5fa8",
    ),
}


# ════════════════════════════════════════════════════════════
# RegionSelector  —  전체화면 드래그 영역 선택기
# ════════════════════════════════════════════════════════════
class RegionSelector(tk.Toplevel):
    def __init__(self, parent: tk.Tk, callback):
        super().__init__(parent)
        self._cb = callback
        self._sx = self._sy = 0
        self._rect_id = None

        # -fullscreen 속성은 보통 "창이 떠 있는 모니터 1개"만 덮어서
        # 듀얼(멀티) 모니터 환경에서는 다른 모니터 위 드래그를 못 잡는 문제가 있었음.
        # → 모든 모니터를 합친 가상 화면(virtual screen) 전체 크기로 직접 지정.
        SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
        SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
        vx = windll.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = windll.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = windll.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = windll.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        self.overrideredirect(True)
        self.geometry(f"{vw}x{vh}+{vx}+{vy}")
        self.attributes("-alpha", 0.25)
        self.attributes("-topmost", True)
        self.configure(bg="black")

        self.cv = tk.Canvas(self, bg="black", cursor="cross", highlightthickness=0)
        self.cv.pack(fill="both", expand=True)

        tk.Label(
            self.cv, bg="black", fg="white",
            text="BBT 창 영역을 드래그하여 선택하세요    (ESC = 취소)",
            font=("Segoe UI", 13),
        ).place(relx=0.5, rely=0.04, anchor="center")

        self.cv.bind("<ButtonPress-1>",   self._press)
        self.cv.bind("<B1-Motion>",       self._drag)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self.bind("<Escape>", lambda _: (self.destroy(), self._cb(None)))

        # overrideredirect 창은 자동으로 포커스를 못 받는 경우가 있어
        # 마우스/ESC 입력이 씹히는 문제가 생김 → 창이 실제로 화면에 그려진 뒤 강제로 포커스/그랩 확보
        self.update_idletasks()
        self.focus_force()
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _press(self, e):
        self._sx, self._sy = e.x_root, e.y_root
        if self._rect_id:
            self.cv.delete(self._rect_id)

    def _drag(self, e):
        if self._rect_id:
            self.cv.delete(self._rect_id)
        # 캔버스 로컬 좌표계로 변환 (창이 화면 (0,0)에 있지 않은 경우 대비)
        ox, oy = self.winfo_rootx(), self.winfo_rooty()
        self._rect_id = self.cv.create_rectangle(
            self._sx - ox, self._sy - oy, e.x_root - ox, e.y_root - oy,
            outline="#0078d4", width=4, dash=(6, 3),
        )

    def _release(self, e):
        x = min(self._sx, e.x_root)
        y = min(self._sy, e.y_root)
        w = abs(e.x_root - self._sx)
        h = abs(e.y_root - self._sy)
        self.destroy()
        if w > 20 and h > 20:
            self._cb({"x": x, "y": y, "w": w, "h": h})
        else:
            self._cb(None)


# ════════════════════════════════════════════════════════════
# AutoClickApp
# ════════════════════════════════════════════════════════════
class AutoClickApp:

    def __init__(self, root: tk.Tk):
        self.root      = root
        self.settings  = self._load_settings()
        self.model     = None
        self._loaded_weight_path: str | None = None
        self._model_loading = False
        self._model_load_gen = 0
        self.cap_region: dict | None = self.settings.get("capture_region")

        self._running   = False
        self._is_busy   = False
        self._work_q: queue.Queue = queue.Queue()
        self._ui_q:   queue.Queue = queue.Queue()
        self._preview_photo       = None
        self._canvas_size         = (460, 240)
        self._run_params: dict    = {}

        self._build_window()
        self._build_menu()
        self._build_ui()
        self._apply_theme()
        self._refresh_region_label()

        self.root.after(80, self._process_ui_queue)

        # 저장된 가중치 자동 로드
        wp = self.settings.get("weight_path", "")
        if wp and os.path.exists(wp):
            self.root.after(400, self._load_model_async)

    # ── 윈도우 초기화 ─────────────────────────────────────────
    def _build_window(self):
        self.root.title(f"{APP_TITLE}  v{VERSION}")
        self.root.geometry(self.settings.get("window_geometry", "480x920+0+0"))
        self.root.minsize(360, 600)
        self.root.attributes("-topmost", self.settings.get("always_on_top", True))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.resizable(True, True)

    # ── 메뉴바 ────────────────────────────────────────────────
    def _build_menu(self):
        mb = tk.Menu(self.root, tearoff=0)
        self.root.config(menu=mb)

        mf = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label="파일", menu=mf)
        mf.add_command(label="가중치 선택…", command=self._select_weight)
        mf.add_separator()
        mf.add_command(label="🔬 이미지 폴더 시뮬레이션…", command=self._open_simulation)
        mf.add_separator()
        mf.add_command(label="종료", command=self._on_close)

        mw = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label="창 설정", menu=mw)
        mw.add_command(label="좌측 좁게  (380px)",       command=lambda: self._resize_w(380))
        mw.add_command(label="좌측 보통  (480px)  ← 기본", command=lambda: self._resize_w(480))
        mw.add_command(label="좌측 넓게  (600px)",       command=lambda: self._resize_w(600))
        mw.add_separator()
        mw.add_command(label="현재 크기/위치 저장",  command=self._save_win_pos)
        mw.add_command(label="위치 초기화 (좌상단)", command=lambda: self.root.geometry("480x920+0+0"))

        mh = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label="도움말", menu=mh)
        mh.add_command(label=f"v{VERSION}  —  BBT 자동클릭", state="disabled")
        mh.add_command(label="F9 : 캡처 & 클릭 실행",        state="disabled")

    # ── UI 탭 ─────────────────────────────────────────────────
    def _build_ui(self):
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=4, pady=(2, 4))

        self.tab_a = tk.Frame(self.nb)
        self.nb.add(self.tab_a, text="  Phase 1  ")
        self._build_tab_a()

        self.tab_b = tk.Frame(self.nb)
        self.nb.add(self.tab_b, text="  Phase 2  ")
        self._build_tab_b()

    # ── Tab A ─────────────────────────────────────────────────
    def _build_tab_a(self):
        self._build_control_panel(self.tab_a)
        self._build_preview(self.tab_a)
        self._build_log(self.tab_a)

    # ── 제어판 ────────────────────────────────────────────────
    def _build_control_panel(self, parent):
        frm = tk.LabelFrame(parent, text="  제어판  ", padx=8, pady=6)
        frm.pack(fill="x", padx=6, pady=(6, 2))
        self._frm_ctrl = frm

        # 가중치 ────────────────────────────────────────────────
        r = tk.Frame(frm); r.pack(fill="x", pady=2)
        tk.Label(r, text="가중치", width=8, anchor="w").pack(side="left")
        self._var_weight = tk.StringVar(value=self.settings.get("weight_path", ""))
        ent = tk.Entry(r, textvariable=self._var_weight, state="readonly", width=20)
        ent.pack(side="left", fill="x", expand=True, padx=(2, 4))
        self._ent_weight = ent
        tk.Button(r, text="📁", width=3, command=self._select_weight).pack(side="left")

        # 장치 / 항상위 / 다크모드 ──────────────────────────────
        r = tk.Frame(frm); r.pack(fill="x", pady=2)
        tk.Label(r, text="장치", width=8, anchor="w").pack(side="left")
        self._var_device = tk.StringVar(value=self.settings.get("device", "cpu"))
        tk.Radiobutton(r, text="CPU", variable=self._var_device, value="cpu").pack(side="left")
        tk.Radiobutton(r, text="GPU (CUDA)", variable=self._var_device, value="cuda:0").pack(side="left", padx=(6, 0))

        self._var_dark = tk.BooleanVar(value=self.settings.get("dark_mode", False))
        tk.Checkbutton(r, text="◑다크", variable=self._var_dark,
                       command=self._toggle_dark).pack(side="right", padx=2)
        self._var_top = tk.BooleanVar(value=self.settings.get("always_on_top", True))
        tk.Checkbutton(r, text="📌항상위", variable=self._var_top,
                       command=self._toggle_topmost).pack(side="right", padx=2)

        # conf / iou 슬라이더 ────────────────────────────────────
        self._var_conf = tk.DoubleVar(value=self.settings.get("conf", 0.50))
        self._var_iou  = tk.DoubleVar(value=self.settings.get("iou",  0.45))
        for label, var in [("conf", self._var_conf), ("iou", self._var_iou)]:
            r = tk.Frame(frm); r.pack(fill="x", pady=1)
            tk.Label(r, text=label, width=8, anchor="w").pack(side="left")
            val_lbl = tk.Label(r, width=5, anchor="e")
            val_lbl.pack(side="right")
            sc = tk.Scale(r, variable=var, from_=0.05, to=0.95, resolution=0.05,
                          orient="horizontal", showvalue=False, length=180)
            sc.pack(side="left", fill="x", expand=True)
            def _cb(v, lv=val_lbl): lv.config(text=f"{float(v):.2f}")
            sc.config(command=_cb)
            _cb(var.get())

        # imgsz ──────────────────────────────────────────────────
        r = tk.Frame(frm); r.pack(fill="x", pady=2)
        tk.Label(r, text="imgsz", width=8, anchor="w").pack(side="left")
        self._var_imgsz = tk.IntVar(value=self.settings.get("imgsz", 320))
        for v in [320, 640]:
            tk.Radiobutton(r, text=str(v), variable=self._var_imgsz, value=v).pack(side="left", padx=4)
        tk.Label(r, text="← 저사양 CPU = 320 권장", font=("Segoe UI", 8)).pack(side="left", padx=6)

        # 클릭 순서 ──────────────────────────────────────────────
        r = tk.Frame(frm); r.pack(fill="x", pady=2)
        tk.Label(r, text="클릭순서", width=8, anchor="w").pack(side="left")
        saved_order  = self.settings.get("click_order", "top_left")
        saved_idx    = CLICK_ORDER_KEYS.index(saved_order) if saved_order in CLICK_ORDER_KEYS else 0
        self._var_order_disp = tk.StringVar(value=CLICK_ORDER_LABELS[saved_idx])
        ttk.Combobox(r, textvariable=self._var_order_disp, width=24, state="readonly",
                     values=CLICK_ORDER_LABELS).pack(side="left", padx=(2, 0))

        # 캡처 영역 ──────────────────────────────────────────────
        r = tk.Frame(frm); r.pack(fill="x", pady=2)
        tk.Label(r, text="캡처영역", width=8, anchor="w").pack(side="left")
        self._lbl_region = tk.Label(r, text="미설정", anchor="w", width=22)
        self._lbl_region.pack(side="left", fill="x", expand=True, padx=2)
        tk.Button(r, text="영역 설정", command=self._select_capture_region,
                  width=8).pack(side="left")

        # 시작 / 정지 ────────────────────────────────────────────
        r = tk.Frame(frm); r.pack(fill="x", pady=(8, 2))
        self._btn_start = tk.Button(
            r, text="▶  시작  (F9 활성화)",
            command=self._start,
            font=("Segoe UI", 10, "bold"), width=20, height=1,
        )
        self._btn_start.pack(side="left", padx=(0, 6))
        self._btn_stop = tk.Button(
            r, text="■  정지",
            command=self._stop,
            font=("Segoe UI", 10, "bold"), width=10, height=1,
            state="disabled",
        )
        self._btn_stop.pack(side="left")

        # 상태 표시 ──────────────────────────────────────────────
        r = tk.Frame(frm); r.pack(fill="x", pady=(2, 0))
        self._lbl_status = tk.Label(r, text="● 대기 중", anchor="w", font=("Segoe UI", 9))
        self._lbl_status.pack(side="left")
        self._lbl_model = tk.Label(r, text="모델 미로드", anchor="e", font=("Segoe UI", 8))
        self._lbl_model.pack(side="right")

    # ── 화면 프리뷰 ───────────────────────────────────────────
    def _build_preview(self, parent):
        frm = tk.LabelFrame(parent, text="  화면 프리뷰  (F9 실행 시 갱신)  ",
                             padx=4, pady=4)
        frm.pack(fill="both", expand=True, padx=6, pady=2)
        self._frm_preview = frm
        self._canvas = tk.Canvas(frm, bg="#111111", height=240, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Configure>", lambda e: setattr(self, "_canvas_size", (e.width, e.height)))
        # 초기 안내 텍스트
        self._canvas.create_text(230, 120, text="F9를 누르면 캡처 화면이 표시됩니다",
                                 fill="#555555", font=("Segoe UI", 10), tags="hint")

    # ── 실행 로그 ─────────────────────────────────────────────
    def _build_log(self, parent):
        frm = tk.LabelFrame(parent, text="  실행 로그  ", padx=4, pady=4)
        frm.pack(fill="both", expand=False, padx=6, pady=(2, 6))
        self._frm_log = frm

        # 툴바 (클리어 버튼)
        tb = tk.Frame(frm); tb.pack(fill="x", anchor="e")
        tk.Button(tb, text="로그 지우기", font=("Segoe UI", 8),
                  command=self._clear_log).pack(side="right")

        sb = tk.Scrollbar(frm)
        sb.pack(side="right", fill="y")
        self._log_text = tk.Text(frm, height=9, state="disabled",
                                  yscrollcommand=sb.set, wrap="word",
                                  font=("Consolas", 8))
        self._log_text.pack(fill="both", expand=True)
        sb.config(command=self._log_text.yview)

        self._log_text.tag_config("ok",   foreground="#2ecc71")
        self._log_text.tag_config("warn", foreground="#e67e22")
        self._log_text.tag_config("err",  foreground="#e74c3c")
        self._log_text.tag_config("info", foreground="#3498db")

    # ── Tab B (Phase 2 placeholder) ───────────────────────────
    def _build_tab_b(self):
        tk.Label(
            self.tab_b,
            text="Phase 2  (O_RED / X_RED)\n\n미구성 — 추후 개발 예정",
            font=("Segoe UI", 11), justify="center",
        ).pack(expand=True)

    # ── 테마 적용 ─────────────────────────────────────────────
    def _apply_theme(self):
        t = THEMES["dark" if self._var_dark.get() else "light"]

        def _style(w):
            cls = w.winfo_class()
            try:
                if cls in ("Frame", "Labelframe"):
                    w.configure(bg=t["bg"])
                elif cls == "Label":
                    w.configure(bg=t["bg"], fg=t["fg"])
                elif cls == "Button":
                    w.configure(bg=t["btn"], fg=t["btn_fg"],
                                activebackground=t["accent"],
                                relief="flat", borderwidth=1)
                elif cls in ("Radiobutton", "Checkbutton"):
                    w.configure(bg=t["bg"], fg=t["fg"],
                                activebackground=t["bg"], selectcolor=t["entry"])
                elif cls == "Scale":
                    w.configure(bg=t["bg"], fg=t["fg"],
                                troughcolor=t["entry"], activebackground=t["accent"])
                elif cls == "Entry":
                    w.configure(bg=t["entry"], fg=t["fg"],
                                insertbackground=t["fg"],
                                disabledbackground=t["panel"],
                                disabledforeground=t["fg"])
                elif cls == "Text":
                    w.configure(bg=t["log_bg"], fg=t["fg"],
                                insertbackground=t["fg"])
                elif cls == "Canvas":
                    w.configure(bg=t["preview_bg"])
            except tk.TclError:
                pass
            for child in w.winfo_children():
                _style(child)

        _style(self.root)

        # 로그 태그 색상 갱신
        try:
            self._log_text.tag_config("ok",   foreground=t["tag_ok"])
            self._log_text.tag_config("warn", foreground=t["tag_warn"])
            self._log_text.tag_config("err",  foreground=t["tag_err"])
            self._log_text.tag_config("info", foreground=t["tag_info"])
        except AttributeError:
            pass

        style = ttk.Style()
        style.configure("TNotebook",     background=t["bg"])
        style.configure("TNotebook.Tab", background=t["btn"],
                        foreground=t["fg"], padding=[10, 4])
        style.map("TNotebook.Tab",
                  background=[("selected", t["accent"])],
                  foreground=[("selected", "#ffffff")])
        style.configure("TCombobox",
                        fieldbackground=t["entry"], foreground=t["fg"],
                        background=t["btn"])

    # ── Settings ──────────────────────────────────────────────
    def _load_settings(self) -> dict:
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    return {**DEFAULT_SETTINGS, **json.load(f)}
            except Exception:
                pass
        return dict(DEFAULT_SETTINGS)

    def _save_settings(self):
        try:
            disp = self._var_order_disp.get()
            order_key = CLICK_ORDER_KEYS[
                CLICK_ORDER_LABELS.index(disp)
            ] if disp in CLICK_ORDER_LABELS else "top_left"

            s = {
                "weight_path":     self._var_weight.get(),
                "device":          self._var_device.get(),
                "conf":            round(self._var_conf.get(), 2),
                "iou":             round(self._var_iou.get(), 2),
                "imgsz":           self._var_imgsz.get(),
                "click_order":     order_key,
                "capture_region":  self.cap_region,
                "window_geometry": self.root.geometry(),
                "always_on_top":   self._var_top.get(),
                "dark_mode":       self._var_dark.get(),
                "hotkey":          self.settings.get("hotkey", "f9"),
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False, indent=2)
            self.settings = s
        except Exception as e:
            pass  # 종료 중 오류 무시

    def _refresh_region_label(self):
        if self.cap_region:
            r = self.cap_region
            self._lbl_region.config(
                text=f"({r['x']}, {r['y']})  {r['w']} × {r['h']} px"
            )

    # ── 가중치 선택 & 모델 로드 ───────────────────────────────
    def _select_weight(self):
        init_dir = os.path.dirname(self.settings.get("weight_path") or __file__)
        path = filedialog.askopenfilename(
            title="가중치 파일 선택 (best.pt)",
            filetypes=[("PyTorch Model", "*.pt"), ("All", "*.*")],
            initialdir=init_dir,
        )
        if path:
            self._var_weight.set(path)
            self._load_model_async()

    def _load_model_async(self):
        self._model_load_gen += 1
        gen = self._model_load_gen
        self._model_loading = True
        self._lbl_model.config(text="로딩 중…")
        self._log("모델 로딩 중…", "info")
        threading.Thread(target=self._load_model, args=(gen,), daemon=True).start()

    def _load_model(self, gen: int):
        path = self._var_weight.get()
        if not path or not os.path.exists(path):
            if gen == self._model_load_gen:
                self._model_loading = False
            self._ui_q.put(("log",    ("가중치 파일을 찾을 수 없습니다.", "err")))
            self._ui_q.put(("model",  "미로드"))
            return
        if YOLO is None:
            if gen == self._model_load_gen:
                self._model_loading = False
            self._ui_q.put(("log",   ("ultralytics 미설치. pip install ultralytics", "err")))
            return
        try:
            m = YOLO(path)
            if gen != self._model_load_gen:
                # 로딩 중 더 최신 가중치 선택으로 대체됨 — 이 결과는 폐기
                return
            self.model = m
            self._loaded_weight_path = path
            self._model_loading = False
            names = list(m.names.values()) if hasattr(m, "names") else []
            self._ui_q.put(("log",   (f"모델 로드 완료  ·  클래스: {names}", "ok")))
            self._ui_q.put(("model", f"✔ {os.path.basename(path)}"))
        except Exception as e:
            if gen == self._model_load_gen:
                self._model_loading = False
            self._ui_q.put(("log",   (f"모델 로드 실패: {e}", "err")))
            self._ui_q.put(("model", "로드 실패"))

    # ── 캡처 영역 선택 ────────────────────────────────────────
    def _select_capture_region(self):
        # 메인 창을 숨기지 않고 그대로 둔 채, 그 위에 반투명 드래그 오버레이만 띄움.
        # 단, 메인 창도 "항상 위"라면 오버레이와 topmost 자리를 다투다가
        # 드래그 시작 클릭이 오버레이 대신 메인 창으로 들어갈 수 있어 잠시 꺼둠.
        self._region_prev_topmost = self.root.attributes("-topmost")
        if self._region_prev_topmost:
            self.root.attributes("-topmost", False)
        RegionSelector(self.root, self._on_region_set)

    def _on_region_set(self, region: dict | None):
        if getattr(self, "_region_prev_topmost", False):
            self.root.attributes("-topmost", True)
        if region is None:
            return
        self.cap_region = region
        self._refresh_region_label()
        self._log(
            f"캡처 영역 설정 완료: {region['w']}×{region['h']}  "
            f"@ ({region['x']}, {region['y']})", "ok"
        )
        self._save_settings()

    # ── 시작 / 정지 ───────────────────────────────────────────
    def _start(self):
        missing = []
        if self.model     is None: missing.append("가중치 파일 선택 필요")
        if self.cap_region is None: missing.append("캡처 영역 설정 필요")
        if mss            is None: missing.append("pip install mss")
        if cv2            is None: missing.append("pip install opencv-python")
        if pydirectinput  is None: missing.append("pip install pydirectinput")
        if kb             is None: missing.append("pip install keyboard")
        if missing:
            messagebox.showwarning("시작 불가", "\n".join(missing))
            return

        # 실행 파라미터 스냅샷 (worker 스레드가 읽음 → thread-safe)
        disp = self._var_order_disp.get()
        order_key = CLICK_ORDER_KEYS[
            CLICK_ORDER_LABELS.index(disp)
        ] if disp in CLICK_ORDER_LABELS else "top_left"

        self._run_params = {
            "conf":   self._var_conf.get(),
            "iou":    self._var_iou.get(),
            "imgsz":  self._var_imgsz.get(),
            "device": self._var_device.get(),
            "order":  order_key,
        }

        self._running = True
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._lbl_status.config(text="● 실행 중  [F9 = 클릭]")

        # Worker 스레드 시작
        threading.Thread(target=self._worker_loop, daemon=True).start()

        # 전역 단축키 등록
        hotkey = self.settings.get("hotkey", "f9")
        try:
            kb.add_hotkey(hotkey, self._on_hotkey)
            self._log(
                f"시작됨  ·  단축키={hotkey.upper()}  "
                f"conf={self._run_params['conf']:.2f}  "
                f"imgsz={self._run_params['imgsz']}", "ok"
            )
        except Exception as e:
            self._log(f"단축키 등록 실패: {e}", "warn")

        self._save_settings()

    def _stop(self):
        self._running = False
        self._btn_start.config(state="normal")
        self._btn_stop.config(state="disabled")
        self._lbl_status.config(text="● 대기 중")
        try:
            kb.remove_hotkey(self.settings.get("hotkey", "f9"))
        except Exception:
            pass
        self._log("정지됨", "warn")

    def _on_hotkey(self):
        if self._running and not self._is_busy:
            self._work_q.put("f9")

    # ── Worker 루프 ───────────────────────────────────────────
    def _worker_loop(self):
        while self._running:
            try:
                cmd = self._work_q.get(timeout=0.3)
            except queue.Empty:
                continue
            if cmd == "f9":
                self._do_capture_and_click()

    # ── 핵심: 캡처 → 추론 → 클릭 ────────────────────────────
    def _do_capture_and_click(self):
        self._is_busy = True
        t0 = time.perf_counter()
        try:
            r   = self.cap_region
            prm = self._run_params

            # ① 캡처 ─────────────────────────────────────────
            with mss.mss() as sct:
                mon  = {"top": r["y"], "left": r["x"], "width": r["w"], "height": r["h"]}
                shot = sct.grab(mon)
                img_bgra = np.array(shot)
                img_bgr  = img_bgra[:, :, :3]          # BGRA → BGR (YOLO 추론용)
                img_rgb  = img_bgra[:, :, [2, 1, 0]]   # BGRA → RGB (시각화용)

            # ② YOLO 추론 ─────────────────────────────────────
            # ultralytics는 numpy 배열 입력을 BGR(cv2 기본 포맷)로 간주하고
            # 내부에서 자체적으로 BGR→RGB 변환을 수행하므로, 여기서 RGB로
            # 미리 바꿔서 넘기면 채널이 두 번 뒤집혀 추론이 깨짐 → BGR을 그대로 전달.
            results = self.model(
                img_bgr,
                conf=prm["conf"], iou=prm["iou"],
                imgsz=prm["imgsz"], device=prm["device"],
                verbose=False,
            )

            # ③ 결과 파싱 & 시각화 이미지 생성 ─────────────────
            annotated = img_rgb.copy()
            x_targets: list[tuple[int, int, float]] = []   # (cx, cy, conf)

            for res in results:
                if res.boxes is None:
                    continue
                for box in res.boxes:
                    cls_id   = int(box.cls[0])
                    cls_name = res.names.get(cls_id, str(cls_id))
                    conf_val = float(box.conf[0])
                    x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

                    color = CLS_COLOR.get(cls_name, (180, 180, 180))
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(annotated,
                                f"{cls_name} {conf_val:.2f}",
                                (x1, max(y1 - 4, 12)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1,
                                cv2.LINE_AA)

                    if cls_name == "X_BLACK":
                        x_targets.append((cx, cy, conf_val))
                        # 클릭 포인트 마커
                        cv2.drawMarker(annotated, (cx, cy), (50, 220, 50),
                                       cv2.MARKER_CROSS, 12, 2)

            # ④ 클릭 순서 정렬 ────────────────────────────────
            order = prm.get("order", "top_left")
            if order == "top_left":
                x_targets.sort(key=lambda p: (p[1], p[0]))
            elif order == "left_top":
                x_targets.sort(key=lambda p: (p[0], p[1]))
            elif order == "confidence":
                x_targets.sort(key=lambda p: -p[2])

            # ⑤ 클릭 실행 ────────────────────────────────────
            n_clicked = 0
            for cx, cy, _ in x_targets:
                scr_x = r["x"] + cx
                scr_y = r["y"] + cy
                pydirectinput.click(scr_x, scr_y)
                n_clicked += 1

            # ⑥ 결과 로그 & 프리뷰 업데이트 ──────────────────
            dt    = (time.perf_counter() - t0) * 1000
            total = sum(len(res.boxes) for res in results if res.boxes)
            tag   = "ok" if n_clicked > 0 else "info"
            self._ui_q.put(("log", (
                f"F9  감지={total}개  X_BLACK클릭={n_clicked}개  {dt:.0f}ms",
                tag,
            )))
            self._ui_q.put(("preview", annotated))

        except Exception as e:
            self._ui_q.put(("log", (f"오류: {e}", "err")))
        finally:
            self._is_busy = False

    # ── UI 큐 처리 (메인 스레드, 80ms 주기) ───────────────────
    def _process_ui_queue(self):
        try:
            while True:
                kind, data = self._ui_q.get_nowait()
                if kind == "log":
                    self._log(data[0], data[1])
                elif kind == "preview":
                    self._update_preview(data)
                elif kind == "model":
                    self._lbl_model.config(text=data)
        except queue.Empty:
            pass
        self.root.after(80, self._process_ui_queue)

    def _update_preview(self, img_rgb: np.ndarray):
        cw, ch = self._canvas_size
        h, w   = img_rgb.shape[:2]
        if w == 0 or h == 0:
            return
        scale  = min(cw / w, ch / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        resized = cv2.resize(img_rgb, (nw, nh), interpolation=cv2.INTER_AREA)

        bg = Image.new("RGB", (cw, ch), (20, 20, 20))
        bg.paste(Image.fromarray(resized), ((cw - nw) // 2, (ch - nh) // 2))
        self._preview_photo = ImageTk.PhotoImage(bg)
        self._canvas.delete("hint")
        self._canvas.create_image(0, 0, anchor="nw", image=self._preview_photo)

    # ── 로그 ─────────────────────────────────────────────────
    def _log(self, text: str, tag: str = ""):
        ts   = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {text}\n"
        self._log_text.config(state="normal")
        self._log_text.insert("end", line, tag or "")
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    # ── 창 관련 헬퍼 ─────────────────────────────────────────
    def _toggle_topmost(self):
        self.root.attributes("-topmost", self._var_top.get())

    def _toggle_dark(self):
        self._apply_theme()

    def _resize_w(self, w: int):
        self.root.geometry(
            f"{w}x{self.root.winfo_height()}"
            f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
        )

    def _save_win_pos(self):
        self._save_settings()
        self._log(f"창 설정 저장: {self.root.geometry()}", "ok")

    def _on_close(self):
        if self._running:
            self._stop()
        self._save_settings()
        self.root.destroy()

    # ── 시뮬레이션 ────────────────────────────────────────────
    def _open_simulation(self):
        current_path = self._var_weight.get()
        if not current_path:
            messagebox.showwarning("시뮬레이션", "가중치 파일을 먼저 선택하세요.")
            return
        # 메인 화면에 표시된 가중치가 아직 로드되지 않았다면(선택 직후 등) 새로 로드
        if self._loaded_weight_path != current_path and not self._model_loading:
            self._load_model_async()
        self._wait_model_then_open_simulation(current_path)

    def _wait_model_then_open_simulation(self, target_path: str):
        if self._model_loading:
            self.root.after(150, lambda: self._wait_model_then_open_simulation(target_path))
            return
        if self.model is None or self._loaded_weight_path != target_path:
            messagebox.showerror("시뮬레이션", "가중치 파일 로드에 실패했습니다.")
            return
        init_dir = self.settings.get("sim_folder", DEFAULT_SIM_FOLDER)
        folder = filedialog.askdirectory(
            title="시뮬레이션할 BBT 이미지 폴더 선택",
            initialdir=init_dir if os.path.exists(init_dir) else os.path.dirname(__file__),
        )
        if not folder:
            return
        self.settings["sim_folder"] = folder
        self._save_settings()
        SimulationWindow(
            parent=self.root,
            folder=folder,
            model=self.model,
            weight_path=self._loaded_weight_path,
            conf=self._var_conf.get(),
            iou=self._var_iou.get(),
            imgsz=self._var_imgsz.get(),
            device=self._var_device.get(),
            log_fn=self._log,
        )


# ════════════════════════════════════════════════════════════
# SimulationWindow  —  이미지 폴더 가상 클릭 시뮬레이션
# ════════════════════════════════════════════════════════════
class SimulationWindow(tk.Toplevel):
    """
    선택한 폴더의 이미지에 YOLO 추론을 실행하여
    X_BLACK이 클릭될 위치를 시각적으로 확인하는 창.
    실제 클릭은 하지 않음.
    """

    IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

    def __init__(self, parent, folder: str, model, weight_path: str | None,
                 conf: float, iou: float, imgsz: int, device: str, log_fn):
        super().__init__(parent)
        self.folder      = folder
        self.model       = model
        self.weight_path = weight_path
        self.conf    = conf
        self.iou     = iou
        self.imgsz   = imgsz
        self.device  = device
        self._log    = log_fn

        self._results: list[dict] = []   # {path, annotated(np), n_x, n_o, n_ban}
        self._photo   = None
        self._stop_ev = threading.Event()

        weight_label = os.path.basename(weight_path) if weight_path else "알 수 없음"
        self.title(f"시뮬레이션  —  {os.path.basename(folder)}  ·  가중치: {weight_label}")
        self.geometry("900x620")
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        threading.Thread(target=self._run, daemon=True).start()

    def _build_ui(self):
        # ── 상단 요약 바 ──────────────────────────────────────
        top = tk.Frame(self, bg="#2d2d2d")
        top.pack(fill="x", padx=6, pady=(6, 2))
        self._lbl_summary = tk.Label(
            top, text="처리 중…", bg="#2d2d2d", fg="#e0e0e0",
            font=("Consolas", 9), anchor="w",
        )
        self._lbl_summary.pack(side="left", fill="x", expand=True)
        tk.Button(top, text="결과 저장 (annotated)", font=("Segoe UI", 8),
                  command=self._save_results).pack(side="right", padx=4)

        # ── 본문 : 리스트 + 프리뷰 ───────────────────────────
        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=6, pady=2)

        # 왼쪽: 파일 리스트
        lf = tk.Frame(body, width=240); lf.pack(side="left", fill="y")
        lf.pack_propagate(False)
        tk.Label(lf, text="이미지 목록", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        sb = tk.Scrollbar(lf); sb.pack(side="right", fill="y")
        self._listbox = tk.Listbox(lf, yscrollcommand=sb.set, font=("Consolas", 8),
                                   bg="#1e1e1e", fg="#e0e0e0",
                                   selectbackground="#0078d4",
                                   activestyle="none")
        self._listbox.pack(fill="both", expand=True)
        sb.config(command=self._listbox.yview)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        # 오른쪽: 캔버스 프리뷰
        self._canvas = tk.Canvas(body, bg="#111111", highlightthickness=0)
        self._canvas.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self._canvas.bind("<Configure>",
                          lambda e: setattr(self, "_cv_size", (e.width, e.height)))
        self._cv_size = (640, 560)

        # ── 하단 진행 바 ──────────────────────────────────────
        self._progress = ttk.Progressbar(self, mode="determinate")
        self._progress.pack(fill="x", padx=6, pady=(2, 6))

    # ── 처리 루프 (백그라운드) ────────────────────────────────
    def _run(self):
        weight_name = os.path.basename(self.weight_path) if self.weight_path else "알 수 없음"
        self._log(f"[시뮬레이션] 사용 가중치: {weight_name}  ({self.weight_path})", "info")
        imgs = sorted(
            p for p in (
                os.path.join(self.folder, f) for f in os.listdir(self.folder)
            )
            if os.path.splitext(p)[1].lower() in self.IMG_EXTS
        )
        total = len(imgs)
        if total == 0:
            self.after(0, lambda: self._lbl_summary.config(
                text="이미지 파일이 없습니다."))
            return

        self.after(0, lambda: self._progress.config(maximum=total))
        tot_x = tot_o = tot_ban = 0

        for i, path in enumerate(imgs):
            if self._stop_ev.is_set():
                break
            try:
                # 한글 경로 대응: cv2.imread 대신 numpy fromfile + imdecode 사용
                buf = np.fromfile(path, dtype=np.uint8)
                img_bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                if img_bgr is None:
                    continue
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

                # ultralytics는 numpy 배열 입력을 BGR로 간주해 내부에서 자체
                # BGR→RGB 변환을 하므로, 여기서 미리 RGB로 바꾼 img_rgb를 넘기면
                # 채널이 두 번 뒤집혀 추론이 깨짐 → 원본 BGR(img_bgr)을 그대로 전달.
                results = self.model(
                    img_bgr,
                    conf=self.conf, iou=self.iou,
                    imgsz=self.imgsz, device=self.device,
                    verbose=False,
                )

                annotated = img_rgb.copy()
                n_x = n_o = n_ban = 0

                for res in results:
                    if res.boxes is None:
                        continue
                    for box in res.boxes:
                        cls_id   = int(box.cls[0])
                        cls_name = res.names.get(cls_id, str(cls_id))
                        conf_val = float(box.conf[0])
                        x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                        color  = CLS_COLOR.get(cls_name, (180, 180, 180))

                        # 모든 클래스에 대해 rectangle 표시 (가시성 확보)
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                        cv2.putText(annotated, f"{cls_name} {conf_val:.3f}",
                                    (x1, max(y1 - 4, 12)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

                        if cls_name == "X_BLACK":
                            n_x += 1
                            cv2.drawMarker(annotated, (cx, cy), (50, 220, 50),
                                           cv2.MARKER_CROSS, 14, 2)
                            cv2.putText(annotated, f"X[{n_x}]",
                                        (cx + 8, cy - 8),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (50, 220, 50), 2)
                        elif cls_name == "O_BLACK":
                            n_o += 1
                            # O_BLACK도 시각적으로 구분되도록 원 표시
                            cv2.circle(annotated, (cx, cy), 6, (255, 165, 0), 2)
                            cv2.putText(annotated, f"O[{n_o}]",
                                        (cx + 8, cy - 8),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 165, 0), 2)
                        else:
                            n_ban += 1
                            cv2.circle(annotated, (cx, cy), 8, (80, 140, 255), 2)
                            cv2.putText(annotated, f"B[{n_ban}]",
                                        (cx + 8, cy - 8),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 140, 255), 2)

                tot_x   += n_x
                tot_o   += n_o
                tot_ban += n_ban

                entry = {
                    "path":      path,
                    "annotated": annotated,
                    "n_x":       n_x,
                    "n_o":       n_o,
                    "n_ban":     n_ban,
                }
                self._results.append(entry)

                # UI 업데이트 (메인 스레드 예약)
                fname = os.path.basename(path)
                # 모든 클래스 개수 표시
                label = f"X{n_x:2d} O{n_o:3d} B{n_ban:2d}  |  {fname}"
                idx   = len(self._results) - 1
                self.after(0, lambda lb=label, ix=idx: self._add_list_item(lb, ix))
                self.after(0, lambda v=i+1: self._progress.config(value=v))

            except Exception as e:
                pass

        # 완료
        summary = (
            f"완료  {len(self._results)}/{total}장  |  "
            f"X_BLACK 클릭예정: {tot_x}  O_BLACK: {tot_o}  Ban: {tot_ban}"
        )
        self.after(0, lambda: self._lbl_summary.config(text=summary))
        self._log(f"[시뮬레이션] {summary}", "ok")

    def _add_list_item(self, label: str, idx: int):
        self._listbox.insert("end", label)
        # X_BLACK 1개 이상이면 초록 강조
        if self._results[idx]["n_x"] > 0:
            self._listbox.itemconfig("end", fg="#2ecc71")
        # 자동으로 마지막 항목 선택
        if self._listbox.size() == 1:
            self._listbox.select_set(0)
            self._show_index(0)

    def _on_select(self, _event):
        sel = self._listbox.curselection()
        if sel:
            self._show_index(sel[0])

    def _show_index(self, idx: int):
        if idx >= len(self._results):
            return
        entry = self._results[idx]
        img   = entry["annotated"]
        cw, ch = self._cv_size
        h, w   = img.shape[:2]
        scale  = min(cw / w, ch / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        bg = Image.new("RGB", (cw, ch), (17, 17, 17))
        bg.paste(Image.fromarray(resized), ((cw - nw) // 2, (ch - nh) // 2))
        self._photo = ImageTk.PhotoImage(bg)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        # 이미지 정보 오버레이
        info = (f"X_BLACK(클릭):{entry['n_x']}  "
                f"O_BLACK:{entry['n_o']}  Ban:{entry['n_ban']}  |  "
                f"{os.path.basename(entry['path'])}")
        self._canvas.create_rectangle(0, 0, cw, 22, fill="#000000aa", outline="")
        self._canvas.create_text(6, 11, anchor="w", text=info,
                                 fill="#e0e0e0", font=("Consolas", 8))

    def _save_results(self):
        if not self._results:
            messagebox.showinfo("저장", "처리된 결과가 없습니다.")
            return
        out_dir = os.path.join(self.folder, "sim_results")
        os.makedirs(out_dir, exist_ok=True)
        for entry in self._results:
            fname = os.path.basename(entry["path"])
            save_path = os.path.join(out_dir, fname)
            # 한글 경로 대응: cv2.imwrite 대신 imencode + 파일 직접 쓰기
            img_bgr = cv2.cvtColor(entry["annotated"], cv2.COLOR_RGB2BGR)
            ext = os.path.splitext(fname)[1].lower() or ".jpg"
            _, buf = cv2.imencode(ext, img_bgr)
            with open(save_path, "wb") as f:
                f.write(buf.tobytes())
        messagebox.showinfo("저장 완료", f"{len(self._results)}장 저장됨\n→ {out_dir}")
        self._log(f"[시뮬레이션] 결과 {len(self._results)}장 저장: {out_dir}", "ok")

    def _on_close(self):
        self._stop_ev.set()
        self.destroy()


# ════════════════════════════════════════════════════════════
# 진입점
# ════════════════════════════════════════════════════════════
def _check_libs() -> list[str]:
    missing = []
    if mss           is None: missing.append("mss")
    if cv2           is None: missing.append("opencv-python")
    if pydirectinput is None: missing.append("pydirectinput")
    if kb            is None: missing.append("keyboard")
    if YOLO          is None: missing.append("ultralytics")
    return missing


def main():
    missing = _check_libs()
    if missing:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "라이브러리 오류",
            f"다음 라이브러리를 설치 후 재실행해주세요:\n\n"
            f"pip install {' '.join(missing)}\n\n"
            f"(requirements_autoclicker.txt 참조)",
        )
        sys.exit(1)

    root = tk.Tk()
    AutoClickApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

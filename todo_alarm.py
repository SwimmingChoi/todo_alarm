"""오늘 날짜의 일정을 팝업으로 알려주는 Windows 상주 프로그램 + 일정 관리 창.

- 처음 실행한 프로세스가 상주하며 알림을 띄운다. 창을 닫아도 계속 돈다.
- 실행 중에 한 번 더 실행하면 일정 관리 창만 띄우는 편집용 프로세스가 된다.
  (상주 프로세스가 일정 파일을 주기적으로 다시 읽으므로 프로세스 간 통신은 필요 없음)
"""
import sys
import tempfile
from datetime import date
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, messagebox, ttk

import schedule

APP_TITLE = "일정 알림"
APP_ID = "todo_alarm"
FROZEN = getattr(sys, "frozen", False)
STARTUP_FLAG = "--startup"  # 로그인 시 자동 실행일 때만 붙는 인자 (창을 띄우지 않음)
CHECK_INTERVAL_MS = 30_000
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def already_running() -> bool:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, APP_ID)  # 핸들은 프로세스 종료 시까지 유지
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def register_autostart() -> None:
    """로그인 시 자동 실행 등록 (HKCU라 관리자 권한 불필요). 매 실행마다 현재 경로로 갱신."""
    import winreg

    # 새로 만든 계정에는 Run 키가 없을 수 있어 OpenKey 대신 CreateKeyEx (없으면 생성)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, f'"{sys.executable}" {STARTUP_FLAG}')


def popup(root: Tk, show, message: str):
    root.attributes("-topmost", True)  # 알림이 다른 창 뒤에 숨지 않도록
    try:
        return show(APP_TITLE, message, parent=root)
    finally:
        root.attributes("-topmost", False)


def build_window(root: Tk, on_close) -> None:
    """일정 목록 + 추가/삭제 창을 root 위에 구성."""
    today = date.today()
    root.title(APP_TITLE)
    root.minsize(520, 360)
    root.protocol("WM_DELETE_WINDOW", on_close)

    # --- 목록 ---
    list_frame = ttk.Frame(root, padding=(10, 10, 10, 0))
    list_frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(list_frame, columns=("date", "text"), show="headings", selectmode="browse")
    tree.heading("date", text="날짜")
    tree.heading("text", text="내용")
    tree.column("date", width=150, stretch=False)
    tree.column("text", width=330)
    tree.tag_configure("today", foreground="#0a58ca")
    tree.tag_configure("past", foreground="#888888")
    tree.tag_configure("bad", foreground="#c0392b")
    scroll = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    raws: dict[str, str] = {}  # 목록 행 id -> 파일의 원본 줄

    def refresh() -> None:
        now = date.today()
        now_ymd = (now.year, now.month, now.day)
        entries, bad = schedule.parse(schedule.read_lines())
        tree.delete(*tree.get_children())
        raws.clear()
        # 다가오는 일정을 가까운 순으로, 지난 일정은 맨 아래로
        for e in sorted(entries, key=lambda e: (e.next_ymd(now) < now_ymd, e.next_ymd(now))):
            ymd = e.next_ymd(now)
            label = ("매년 " if e.year is None else f"{e.year}-") + f"{e.month:02d}-{e.day:02d}"
            tag = "today" if ymd == now_ymd else "past" if ymd < now_ymd else ""
            if tag == "today":
                label += " (오늘)"
            raws[tree.insert("", "end", values=(label, e.text), tags=(tag,))] = e.raw
        for line in bad:
            raws[tree.insert("", "end", values=("형식 오류", line), tags=("bad",))] = line

    # --- 추가 ---
    form = ttk.Frame(root, padding=10)
    form.pack(fill="x")
    year = StringVar(value=str(today.year))
    month = StringVar(value=str(today.month))
    day = StringVar(value=str(today.day))
    yearly = BooleanVar(value=False)
    text = StringVar()

    # 읽기 전용 콤보박스라 숫자 외 입력이 들어올 수 없음
    year_box = ttk.Combobox(form, textvariable=year, width=5, state="readonly",
                            values=[str(today.year + i) for i in range(6)])
    month_box = ttk.Combobox(form, textvariable=month, width=3, state="readonly",
                             values=[str(i) for i in range(1, 13)])
    day_box = ttk.Combobox(form, textvariable=day, width=3, state="readonly",
                           values=[str(i) for i in range(1, 32)])
    text_entry = ttk.Entry(form, textvariable=text)

    def on_yearly() -> None:
        year_box.configure(state="disabled" if yearly.get() else "readonly")

    def on_add(_event=None) -> None:
        try:
            schedule.add(None if yearly.get() else int(year.get()), int(month.get()), int(day.get()), text.get())
        except ValueError as e:
            popup(root, messagebox.showwarning, str(e))
            return
        text.set("")
        refresh()

    def on_delete(_event=None) -> None:
        selected = tree.selection()
        if not selected:
            return
        raw = raws[selected[0]]
        if popup(root, messagebox.askyesno, f"이 일정을 삭제할까요?\n\n{raw}"):
            schedule.delete(raw)
            refresh()

    year_box.pack(side="left")
    ttk.Label(form, text="년").pack(side="left", padx=(2, 6))
    month_box.pack(side="left")
    ttk.Label(form, text="월").pack(side="left", padx=(2, 6))
    day_box.pack(side="left")
    ttk.Label(form, text="일").pack(side="left", padx=(2, 6))
    ttk.Checkbutton(form, text="매년", variable=yearly, command=on_yearly).pack(side="left", padx=(0, 8))
    ttk.Button(form, text="삭제", width=6, command=on_delete).pack(side="right")
    ttk.Button(form, text="추가", width=6, command=on_add).pack(side="right", padx=(6, 6))
    text_entry.pack(side="left", fill="x", expand=True)
    text_entry.bind("<Return>", on_add)
    tree.bind("<Delete>", on_delete)

    ttk.Label(
        root,
        text="창을 닫아도 알림은 계속 동작합니다. 다시 열려면 프로그램을 한 번 더 실행하세요.",
        foreground="#666666",
        padding=(10, 0, 10, 10),
    ).pack(anchor="w")

    root.after_idle(refresh)  # 콜백으로 돌려 파일 읽기 실패가 오류 팝업으로만 끝나게 함
    text_entry.focus_set()


def start_notifier(root: Tk) -> None:
    """일정 파일을 주기적으로 읽어 오늘 일정 중 아직 알리지 않은 것을 팝업으로 알림."""
    seen: set[str] = set()  # 오늘 이미 알린 내용 (날짜가 바뀌면 초기화)
    seen_day = None

    def tick() -> None:
        nonlocal seen_day
        try:
            today = date.today()
            if today != seen_day:
                seen_day = today
                seen.clear()
            items, bad = schedule.todays(schedule.read_lines(), today)
            new_items = [i for i in items if i not in seen]
            new_bad = [b for b in bad if b not in seen]
            seen.update(items, bad)
            if new_items:
                weekday = "월화수목금토일"[today.weekday()]
                popup(
                    root,
                    messagebox.showinfo,
                    f"{today:%Y-%m-%d} ({weekday}) 오늘의 일정\n\n" + "\n".join(f"• {i}" for i in new_items),
                )
            if new_bad:
                popup(
                    root,
                    messagebox.showwarning,
                    "일정.txt에서 날짜를 해석하지 못한 줄이 있습니다.\n\n"
                    + "\n".join(new_bad)
                    + "\n\n형식: 2026-10-06 내용 / 10-06 내용(매년)",
                )
        except (OSError, UnicodeDecodeError) as e:
            msg = f"일정 파일을 읽지 못했습니다.\n\n{type(e).__name__}: {e}"
            if msg not in seen:
                seen.add(msg)
                popup(root, messagebox.showerror, msg)
        finally:
            root.after(CHECK_INTERVAL_MS, tick)

    tick()


def main() -> None:
    root = Tk()
    root.withdraw()
    # --noconsole 빌드에서 버튼 콜백의 예외가 조용히 사라지지 않도록
    root.report_callback_exception = lambda exc_type, exc, _tb: popup(
        root, messagebox.showerror, f"오류가 발생했습니다.\n\n{exc_type.__name__}: {exc}"
    )

    if FROZEN:
        # 탐색기에서 zip 안의 exe를 바로 실행하면 임시 폴더에서 돌아, 정리될 때 자동 실행이 끊긴다
        if Path(tempfile.gettempdir()).resolve() in Path(sys.executable).resolve().parents:
            popup(root, messagebox.showerror, "압축 파일 안에서 바로 실행하셨습니다.\n\n원하는 폴더에 압축을 푼 뒤 다시 실행해 주세요.")
            return
        try:
            register_autostart()
        except OSError as e:  # 백신/정책이 막아도 알림과 일정 관리는 계속 쓸 수 있게
            popup(
                root,
                messagebox.showwarning,
                f"자동 실행 등록에 실패했습니다. 컴퓨터를 켠 뒤 직접 실행해 주세요.\n\n{type(e).__name__}: {e}",
            )
    resident = not already_running()
    startup = STARTUP_FLAG in sys.argv
    if startup and not resident:
        return
    first_run = resident and not schedule.SCHEDULE_FILE.exists()
    if first_run:
        schedule.write_lines(schedule.SAMPLE.splitlines())

    if not startup:
        build_window(root, on_close=root.withdraw if resident else root.destroy)
        root.deiconify()
    if first_run and not startup:
        popup(
            root,
            messagebox.showinfo,
            "설치 완료! 이제 컴퓨터를 켤 때마다 자동으로 실행되어 오늘 일정을 알려 드립니다.\n\n"
            "이 창에서 일정을 추가하세요. 창을 닫아도 알림은 계속 동작하고,\n"
            "창을 다시 열려면 이 프로그램을 한 번 더 실행하면 됩니다.\n\n"
            "※ 프로그램 파일을 다른 폴더로 옮기면 한 번 더 실행해 주세요.",
        )
    if resident:
        start_notifier(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # --noconsole 빌드에서도 예기치 못한 예외를 사용자에게 보여주기 위함
        messagebox.showerror(APP_TITLE, f"예상치 못한 오류가 발생했습니다.\n\n{type(e).__name__}: {e}")
        sys.exit(1)

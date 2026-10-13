"""队列内的视频预览，播放声音并即时保存平台选择。"""
import tkinter as tk
from tkinter import ttk, messagebox
import os
from pathlib import Path

_dll_directories = []


def load_player():
    import ffpyplayer
    # uv 的缓存安装将共享 DLL 放在包的实际目录旁，保留句柄到进程退出。
    if os.name == "nt":
        base = Path(ffpyplayer.__file__).resolve().parents[3] / "share" / "ffpyplayer"
        for library in ("ffmpeg", "sdl"):
            directory = base / library / "bin"
            if directory.is_dir():
                _dll_directories.append(os.add_dll_directory(str(directory)))
    from ffpyplayer.player import MediaPlayer
    return MediaPlayer


class VideoPreview:
    def __init__(self, parent, video, item, labels, change, navigate=None, index=0, total=1):
        MediaPlayer = load_player()
        self.MediaPlayer = MediaPlayer
        self.navigate, self.index, self.total = navigate, index, total
        self.item, self.change, self.labels = item, change, labels
        from PIL import Image, ImageTk
        self.Image, self.ImageTk = Image, ImageTk
        self.player = MediaPlayer(str(video), ff_opts={"out_fmt": "rgb24"})
        self.closed = False
        self.timer = None
        self.previous_focus = parent.focus_get()
        self.window = tk.Toplevel(parent)
        self.window.title(f"视频预览 · {item['folder'].name}")
        self.window.geometry("880x700")
        self.window.minsize(600, 450)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda event: self.close())
        self.screen = tk.Canvas(self.window, background="#111111", highlightthickness=0, width=640, height=400)
        self.screen.pack(fill="both", expand=True)
        self.screen.bind("<Button-1>", lambda event: self.screen.focus_set())
        self.window.bind("<Map>", self.focus_on_open, add="+")
        self.video_image = self.screen.create_image(0, 0, anchor="center")
        controls = ttk.Frame(self.window, padding=10)
        controls.pack(fill="x")
        self.play_button = ttk.Button(controls, text="暂停", command=self.toggle)
        self.play_button.pack(side="left")
        ttk.Button(controls, text="从头播放", command=self.restart).pack(side="left", padx=8)
        self.position = tk.StringVar(value="正在加载视频…")
        ttk.Label(controls, textvariable=self.position).pack(side="left")
        self.next_button = ttk.Button(controls, text="下一个 ↓", command=lambda: self.switch(1))
        self.next_button.pack(side="right")
        self.previous_button = ttk.Button(controls, text="上一个 ↑", command=lambda: self.switch(-1))
        self.previous_button.pack(side="right", padx=8)
        self.window.bind("<Up>", lambda event: self.switch(-1))
        self.window.bind("<Down>", lambda event: self.switch(1))
        platforms = ttk.LabelFrame(self.window, text="发布平台", padding=12)
        platforms.pack(fill="x", padx=10, pady=(0, 10))
        self.variables = {}
        self.boxes = {}
        self.status_labels = {}
        for platform, label in labels.items():
            cell = ttk.Frame(platforms)
            cell.pack(side="left", padx=10)
            variable = tk.BooleanVar()
            self.variables[platform] = variable
            self.boxes[platform] = box = ttk.Checkbutton(cell, variable=variable)
            box.configure(text=label, command=lambda p=platform, v=variable, b=box, name=label:
                          self.choose(p, v, b, name, self.item, self.change))
            self.status_labels[platform] = ttk.Label(cell)
        self.update_platform_controls()
        self.update_navigation()
        self.tick()

    def focus_on_open(self, event):
        if event.widget == self.window:
            self.window.unbind("<Map>")
            self.window.after_idle(self.focus_preview)

    def focus_preview(self):
        if not self.closed:
            self.window.lift()
            self.screen.focus_force()

    def update_navigation(self):
        self.window.title(f"视频预览 · {self.index + 1}/{self.total} · {self.item['folder'].name}")
        self.previous_button.configure(state="normal" if self.navigate and self.index > 0 else "disabled")
        self.next_button.configure(state="normal" if self.navigate and self.index < self.total - 1 else "disabled")

    def update_platform_controls(self):
        for platform, variable in self.variables.items():
            state = self.item["states"][platform]
            box, status = self.boxes[platform], self.status_labels[platform]
            box.pack_forget()
            status.pack_forget()
            locked = state in ("已完成", "待核对", "发布中")
            variable.set(not locked and state != "不发布")
            if locked:
                status.configure(text=f"{self.labels[platform]}：{state}")
                status.pack(side="left")
            else:
                box.pack(side="left")

    def switch(self, direction):
        target = self.index + direction
        if self.closed or not self.navigate or not 0 <= target < self.total:
            return "break"
        try:
            video, item, change = self.navigate(target)
            player = self.MediaPlayer(str(video), ff_opts={"out_fmt": "rgb24"})
        except Exception as error:
            messagebox.showerror("无法预览视频", str(error), parent=self.window)
            return "break"
        if self.timer is not None:
            self.window.after_cancel(self.timer)
        self.player.close_player()
        self.player = player
        self.index, self.item, self.change = target, item, change
        self.screen.itemconfigure(self.video_image, image="")
        self.position.set("正在加载视频…")
        self.play_button.configure(text="暂停")
        self.update_platform_controls()
        self.update_navigation()
        self.tick()
        return "break"

    def choose(self, platform, variable, box, label, item, change):
        change(platform, "待发布" if variable.get() else "不发布")
        self.update_platform_controls()

    def toggle(self):
        self.player.toggle_pause()
        self.play_button.configure(text="播放" if self.player.get_pause() else "暂停")

    def restart(self):
        self.player.seek(0, relative=False)
        self.player.set_pause(False)
        self.play_button.configure(text="暂停")

    def tick(self):
        if self.closed:
            return
        frame, delay = self.player.get_frame()
        if frame is not None:
            source, timestamp = frame
            picture = self.Image.frombytes("RGB", source.get_size(), source.to_bytearray()[0])
            picture.thumbnail((max(1, self.screen.winfo_width()), max(1, self.screen.winfo_height())))
            self.photo = self.ImageTk.PhotoImage(picture)
            self.screen.itemconfigure(self.video_image, image=self.photo)
            self.screen.coords(self.video_image, self.screen.winfo_width() / 2, self.screen.winfo_height() / 2)
            duration = self.player.get_metadata().get("duration") or 0
            self.position.set(f"{timestamp:.0f} 秒 / {duration:.0f} 秒")
        if delay == "eof":
            self.player.set_pause(True)
            self.play_button.configure(text="播放")
            self.position.set("播放结束，可点击从头播放")
        wait = max(10, min(100, int(delay * 1000))) if isinstance(delay, (float, int)) else 50
        self.timer = self.window.after(wait, self.tick)

    def close(self):
        self.closed = True
        if self.timer is not None:
            self.window.after_cancel(self.timer)
        self.player.close_player()
        self.window.destroy()
        if self.previous_focus is not None and self.previous_focus.winfo_exists():
            self.previous_focus.focus_set()

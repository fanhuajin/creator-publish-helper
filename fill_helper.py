"""用户手动聚焦输入框后触发快捷键；不导航、不上传、不点击发布。"""

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path
import re
import time
import json
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import ImageChops, ImageGrab
from focus_detection import focused_field


def candidate_visible(before, current):
    """判断输入行下方是否有跨行变化；只是浮层迹象，不解析话题。"""
    mask = ImageChops.difference(before, current).convert("L").point(
        lambda value: 255 if value > 5 else 0
    )
    rows = [
        y for y in range(mask.height)
        if mask.crop((0, y, mask.width, y + 1)).histogram()[255] >= 60
    ]
    return len(rows) >= 8 and rows[-1] - rows[0] >= 45


def candidate_stable(previous, current):
    """检测候选区域渲染稳定，排除候选加载或改写过程。"""
    difference = ImageChops.difference(previous, current).convert("L")
    changed = difference.point(lambda value: 255 if value > 3 else 0)
    return changed.histogram()[255] / (changed.width * changed.height) < 0.001


def read_copy(path):
    """读取 UTF-8 文案，以标题、简介、标签分节，保留简介换行和 emoji。"""
    text = path.read_text(encoding="utf-8-sig")
    parts = re.split(r"(?m)^\s*(标题|简介|标签)[：:]\s*", text)
    values = dict(zip(parts[1::2], (s.strip() for s in parts[2::2])))
    if not values.get("标题") or not values.get("简介") or not values.get("标签"):
        raise ValueError("文案必须包含标题：、简介：、标签：三个非空章节")
    tags = list(dict.fromkeys(t.lstrip("#") for t in values["标签"].split()))
    return values["标题"], values["简介"], tags


def detect_platform(window_title):
    """从当前窗口标题识别平台；不确定时拒绝输入，不猜测标签规则。"""
    names = {
        "bilibili": ("哔哩哔哩", "bilibili", "b站"),
        "douyin": ("抖音", "douyin"),
        "xiaohongshu": ("小红书", "xiaohongshu"),
    }
    found = [name for name, words in names.items() if any(w in window_title.lower() for w in words)]
    if len(found) != 1:
        raise ValueError(f"无法识别投稿平台：{window_title}。请切换到对应投稿标签页。")
    return found[0]


def discard_pending_hotkeys(user):
    """丢弃处理期间排队的 F5/F6，保留 F9 的退出意图，不动其他 Windows 消息。"""
    message = wintypes.MSG()
    ignored = 0
    exit_requested = False
    while user.PeekMessageW(ctypes.byref(message), None, 0x312, 0x312, 1):
        if message.wParam == 4:
            exit_requested = True
        elif message.wParam in (1, 5):
            ignored += 1
    return ignored, exit_requested


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("copy_file", type=Path, nargs="?", help="可选的初始发布文案路径")
    args = parser.parse_args()
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    # 指针接口显式声明，避免 64 位 Python 截断剪贴板内存句柄。
    kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
    user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user.SetClipboardData.restype = wintypes.HANDLE
    user.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user.GetAsyncKeyState.restype = ctypes.c_short
    user.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    user.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND,
        wintypes.UINT, wintypes.UINT, wintypes.UINT,
    ]
    user.PeekMessageW.restype = wintypes.BOOL
    user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.GetClipboardData.argtypes = [wintypes.UINT]
    user.GetClipboardData.restype = wintypes.HANDLE
    user.GetClipboardSequenceNumber.restype = wintypes.DWORD
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell.DragQueryFileW.restype = wintypes.UINT
    user.SetProcessDPIAware()

    def stopped():
        return bool(user.GetAsyncKeyState(0x1B) & 0x8000)

    def paste(text, replace):
        data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-16-le") + b"\0\0"
        handle = kernel.GlobalAlloc(2, len(data))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            pointer = kernel.GlobalLock(handle)
            if not pointer:
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.memmove(pointer, data, len(data))
            kernel.GlobalUnlock(handle)
            opened = False
            for _ in range(20):
                if user.OpenClipboard(None):
                    opened = True
                    break
                time.sleep(0.025)
            if not opened:
                raise RuntimeError("剪贴板忙，请稍后重试")
            try:
                if not user.EmptyClipboard() or not user.SetClipboardData(13, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                handle = None  # 成功后内存所有权交给系统。
            finally:
                user.CloseClipboard()
        finally:
            if handle:
                kernel.GlobalFree(handle)
        if stopped():
            return False
        if replace:
            chord(0x41)
        chord(0x56)
        time.sleep(0.25)
        return True

    def key(code):
        user.keybd_event(code, 0, 0, 0)
        user.keybd_event(code, 0, 2, 0)

    def chord(code):
        user.keybd_event(0x11, 0, 0, 0)
        try:
            key(code)
        finally:
            user.keybd_event(0x11, 0, 2, 0)

    def hash_key():
        """标准英文键盘 Shift+3 输入 #，触发编辑器的话题输入逻辑。"""
        user.keybd_event(0x10, 0, 0, 0)
        try:
            key(0x33)
        finally:
            user.keybd_event(0x10, 0, 2, 0)

    def wait_topic():
        """固定等待候选加载，可用 Esc 中止，不进行截图识别。"""
        for _ in range(20):
            if stopped():
                return False
            time.sleep(0.05)
        return True

    def wait_topic_fast(before, region):
        """最多等一秒；浮层出现且连续稳定才提前确认，漏判时回落固定等待。"""
        started = time.monotonic()
        previous = None
        stable_frames = 0
        while time.monotonic() - started < 1:
            if stopped():
                return False
            current = ImageGrab.grab(bbox=region)
            visible = candidate_visible(before, current)
            stable = previous is not None and candidate_stable(previous, current)
            stable_frames = stable_frames + 1 if visible and stable else 0
            # 为输入后的异步候选更新保留最少时间，不只看到框就立即按空格。
            if stable_frames >= 2 and time.monotonic() - started >= 0.3:
                print("候选区域出现并稳定，提前发送空格。", flush=True)
                return True
            previous = current
            time.sleep(0.06)
        print("检测未确认，使用一秒等待。", flush=True)
        return True

    def select_copy():
        """优先读取资源管理器选中文件；其他窗口打开选择框，校验成功才切换稿件。"""
        source_window = user.GetForegroundWindow()
        window_class = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(source_window, window_class, len(window_class))
        dialog = tk.Tk()
        dialog.withdraw()
        dialog.attributes("-topmost", True)
        selection = Path(__file__).with_name("current_copy.json")
        try:
            current = args.copy_file
            if selection.exists():
                current = Path(json.loads(selection.read_text(encoding="utf-8"))["copy_file"])
            if window_class.value in ("CabinetWClass", "ExploreWClass"):
                user.SetForegroundWindow(source_window)
                if user.GetForegroundWindow() != source_window:
                    raise RuntimeError("资源管理器焦点已改变，请重新选中文案再按 F5。")
                # Ctrl+C 只复制当前选中路径。等待新剪贴板版本，禁止误用上一次的文件。
                sequence = user.GetClipboardSequenceNumber()
                chord(0x43)
                deadline = time.monotonic() + 1.5
                while user.GetClipboardSequenceNumber() == sequence and time.monotonic() < deadline:
                    time.sleep(0.03)
                if user.GetClipboardSequenceNumber() == sequence:
                    raise ValueError("没有读取到新选择，请在资源管理器中单击选中文案文件再按 F5。")
                if not user.OpenClipboard(None):
                    raise RuntimeError("剪贴板忙，请稍后再按 F5。")
                try:
                    handle = user.GetClipboardData(15)  # CF_HDROP：资源管理器复制的文件列表。
                    if not handle or shell.DragQueryFileW(handle, 0xFFFFFFFF, None, 0) != 1:
                        raise ValueError("请只选中一个文案文件或一个视频目录。")
                    length = shell.DragQueryFileW(handle, 0, None, 0)
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    shell.DragQueryFileW(handle, 0, buffer, len(buffer))
                    filename = buffer.value
                finally:
                    user.CloseClipboard()
                if Path(filename).is_dir():
                    filename = str(Path(filename) / "发布文案.txt")
            else:
                filename = filedialog.askopenfilename(
                    parent=dialog,
                    initialdir=str(current.parent if current else Path.home()),
                    title="选择当前视频的发布文案",
                    filetypes=[("文案文本", "*.txt"), ("所有文件", "*.*")],
                )
            if not filename:
                return
            selected = Path(filename)
            selected_title, _, _ = read_copy(selected)
            temporary = selection.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"copy_file": str(selected)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(selection)
            print(f"文案选中成功：{selected}", flush=True)
            messagebox.showinfo(
                "文案选中成功",
                f"文件：{selected}\n\n标题：{selected_title}\n\n切回目标输入框后按 F6 自动填写。",
                parent=dialog,
            )
        except Exception as error:
            messagebox.showerror("文案选择失败", str(error), parent=dialog)
        finally:
            dialog.destroy()

    registered = []
    try:
        for number, code in [(1, 0x75), (4, 0x78), (5, 0x74)]:
            if not user.RegisterHotKey(None, number, 0x4000, code):
                raise RuntimeError(f"F{code - 0x6F} 被其他程序占用，请关闭冲突程序")
            registered.append(number)
        print("点击目标输入框后按 F6 自动识别并填写。F9 退出。", flush=True)
        print("F5：直接使用资源管理器选中的文案文件，成功后弹出提示；其他窗口打开选择框。", flush=True)
        print("B站各字段分别按 F6；抖音/小红书正文一次填写简介和话题。", flush=True)
        print("执行时按住 Esc 可中止。剪贴板会被覆盖。", flush=True)
        print("填写期间重复 F6 将忽略，不会排队重复输入；F9 在本次处理结束后退出。", flush=True)
        print("先在资源管理器选中文案并按 F5，再使用填写快捷键。", flush=True)
        message = wintypes.MSG()
        exit_requested = False
        while not exit_requested:
            result = user.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result == -1:
                raise ctypes.WinError(ctypes.get_last_error())
            if result == 0:
                break
            if message.message != 0x312:
                continue
            action = message.wParam
            if action == 4:
                break
            # 等触发键释放后输入，避免仍按着功能键时混入组合键。
            trigger = {1: 0x75, 5: 0x74}[action]
            while user.GetAsyncKeyState(trigger) & 0x8000:
                time.sleep(0.02)
            # 同步填写会阻塞 GetMessage，重复快捷键实际在系统消息队列中排队。
            # 保持热键注册以拦截 F6，结束时清理队列，避免 F6 落到浏览器切换焦点。
            print("状态：正在选择文案。" if action == 5 else "状态：正在识别并填写。", flush=True)
            try:
                if action == 5:
                    select_copy()
                    continue
                source_window = user.GetForegroundWindow()
                window_title = ctypes.create_unicode_buffer(1024)
                user.GetWindowTextW(source_window, window_title, len(window_title))
                platform = detect_platform(window_title.value)
                # 每次快捷键重新读取当前选择，切换稿件无需重启后台程序。
                selection = Path(__file__).with_name("current_copy.json")
                copy_file = Path(json.loads(selection.read_text(encoding="utf-8"))["copy_file"]) if selection.exists() else args.copy_file
                if copy_file is None:
                    raise ValueError("请先选中文案文件并按 F5。")
                title, description, tags = read_copy(copy_file)
                field = focused_field(platform, source_window)
                if user.GetForegroundWindow() != source_window:
                    raise RuntimeError("窗口已切换，本次未输入。")
                print(f"平台：{platform}；字段：{field}；稿件：{copy_file.parent.name}", flush=True)
                if field == "title":
                    paste(title, True)
                elif field == "description" and platform == "bilibili":
                    paste(description, True)
                elif field == "tags":
                    # 旧标签由用户清理，只在已聚焦的标签输入框逐个追加。
                    for tag in tags:
                        if stopped() or not paste(tag, False):
                            break
                        if stopped():
                            break
                        key(0x0D)
                        time.sleep(0.35)
                elif field == "description":
                    # 共用正文编辑器时先替换简介，再在同一焦点追加话题。
                    if not paste(description + " ", True):
                        continue
                    # 恢复用户确认有效的固定等待流程；截图变化不代表候选准备完成。
                    region = None
                    if platform in ("douyin", "xiaohongshu"):
                        point = wintypes.POINT()
                        if not user.GetCursorPos(ctypes.byref(point)):
                            raise ctypes.WinError(ctypes.get_last_error())
                        screen = ImageGrab.grab()
                        region = (
                            max(0, point.x - 400), max(0, point.y + 20),
                            min(screen.width, point.x + 750), min(screen.height, point.y + 420),
                        )
                        if region[2] <= region[0] or region[3] <= region[1]:
                            raise RuntimeError("请将鼠标留在简介输入行附近")
                    for tag in tags:
                        if stopped():
                            break
                        before = ImageGrab.grab(bbox=region) if region else None
                        hash_key()
                        if not paste(tag, False):
                            break
                        confirmed = wait_topic_fast(before, region) if region else wait_topic()
                        if not confirmed:
                            break
                        key(0x20)
                        print(f"已发送空格：#{tag}，请检查关联结果。", flush=True)
                        time.sleep(0.15)
                print("本次输入结束，请检查网页结果。", flush=True)
            except Exception as error:
                print(f"输入停止：{error}", flush=True)
                dialog = tk.Tk()
                dialog.withdraw()
                dialog.attributes("-topmost", True)
                try:
                    messagebox.showerror("未执行自动填写", str(error), parent=dialog)
                finally:
                    dialog.destroy()
            finally:
                ignored, exit_requested = discard_pending_hotkeys(user)
                if ignored:
                    print(f"已忽略处理期间重复的快捷键：{ignored} 次。", flush=True)
                print("状态：空闲。", flush=True)
    finally:
        for number in registered:
            user.UnregisterHotKey(None, number)


if __name__ == "__main__":
    instance_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    instance_kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    instance_kernel.CreateMutexW.restype = wintypes.HANDLE
    instance_kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    instance_handle = instance_kernel.CreateMutexW(None, False, "Local\\CreatorPublishHelper")
    instance_error = ctypes.get_last_error()
    if not instance_handle:
        raise ctypes.WinError(instance_error)
    try:
        if instance_error == 183:
            print("助手已经运行，请直接使用 F5 / F6 / F7 / F8；按 F9 退出。", flush=True)
        else:
            main()
    finally:
        instance_kernel.CloseHandle(instance_handle)

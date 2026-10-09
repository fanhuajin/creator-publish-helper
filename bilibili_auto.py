"""B站投稿准备：读取本地控件并发送鼠标键盘事件，始终在提交前停止。"""

import argparse
from _ctypes import COMError
import ctypes
from datetime import datetime, timedelta, timezone
import json
import re
from pathlib import Path
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from urllib.parse import urlsplit

from fill_helper import read_copy

CHINA_TIME = timezone(timedelta(hours=8))


class ControlSnapshot:
    """一次捕获控件定位属性，避免同轮遍历后重复访问已被页面销毁的节点。"""

    def __init__(self, control):
        self.control = control
        self.Name = control.Name
        self.ControlTypeName = control.ControlTypeName
        self.BoundingRectangle = control.BoundingRectangle
        self.IsOffscreen = control.IsOffscreen

    def __getattr__(self, name):
        # 点击和状态模式仍使用实时控件，失效时停止，不盲目重发操作。
        return getattr(self.control, name)


def category_from_folder(folder):
    """只按用户指定的目录标记分类；缺失或混合标记都拒绝猜测。"""
    matches = [
        category for marker, category in (("_跳舞", "舞蹈"), ("_唱歌", "音乐"))
        if marker in folder.name
    ]
    if len(matches) != 1:
        raise ValueError("目录名必须明确包含 _跳舞 或 _唱歌，不能同时包含两个标记。")
    return matches[0]


def cover_from_folder(folder):
    """两种比例共用一张已有封面，优先B站4x3.png，不随意选择人物素材。"""
    for name in ("B站4x3.png", "封面.png", "封面.jpg"):
        path = folder / name
        if path.is_file():
            return path.resolve()
    raise ValueError("没有找到封面：请提供 B站4x3.png、封面.png 或封面.jpg。")


def parse_publish_time(value, now=None):
    """按北京时间解析分钟精度；截图中页面允许当前时间5分钟至15天内。"""
    if not value.strip():
        return None
    try:
        selected = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=CHINA_TIME)
    except ValueError as error:
        raise ValueError("定时时间格式应为 YYYY-MM-DD HH:MM，例如 2026-10-10 18:30。") from error
    current = now or datetime.now(CHINA_TIME)
    if current.tzinfo is None:
        raise ValueError("校验时间必须带时区。")
    if not current + timedelta(minutes=5) <= selected <= current + timedelta(days=15):
        raise ValueError("定时时间应在北京时间当前时间5分钟之后、15天以内。")
    if selected.minute % 5:
        raise ValueError("页面时间选项以5分钟为间隔，请选择例如18:30或18:35。")
    return selected


def prepare_files(folder):
    """仅接受单个明确视频；优先最终成片，避免批量误上传其他素材。"""
    title, description, tags = read_copy(folder / "发布文案.txt")
    preferred = folder / "最终成片.mp4"
    videos = [preferred] if preferred.is_file() else [
        item for item in folder.iterdir()
        if item.is_file() and item.suffix.lower() in (".mp4", ".mov", ".mkv")
    ]
    if len(videos) != 1:
        raise ValueError("目录中必须有最终成片.mp4，或只有一个视频文件。")
    if len(title) > 80 or len(description) > 2000:
        raise ValueError("标题超过80字或简介超过2000字。")
    if len(tags) > 10 or any(not tag or len(tag) > 20 for tag in tags):
        raise ValueError("B站最多10个标签，每个标签应为1至20字。")
    return videos[0].resolve(), title, description, tags


def is_upload_url(value):
    """校验精确域名和投稿路径，不接受相似域名或普通视频页面。"""
    url = urlsplit(value)
    return (
        url.scheme == "https"
        and url.hostname == "member.bilibili.com"
        and url.path.startswith("/platform/upload/video")
    )


def choose_control(found, editable=False):
    """合并浏览器同一位置的容器/文字节点，独立同名字段仍保留歧义。"""
    if not editable:
        buttons = [item for item in found if item.ControlTypeName == "ButtonControl"]
        texts = [item for item in found if item.ControlTypeName == "TextControl"]
        found = buttons or texts or found
    unique = {}
    for item in found:
        rect = item.BoundingRectangle
        unique[(rect.left, rect.top, rect.right, rect.bottom)] = item
    found = list(unique.values())
    if len(found) > 1 and not editable:
        boxes = [item.BoundingRectangle for item in found]
        centers = [((box.left + box.right) / 2, (box.top + box.bottom) / 2) for box in boxes]
        if (
            max(x for x, _ in centers) - min(x for x, _ in centers) <= 30
            and max(y for _, y in centers) - min(y for _, y in centers) <= 20
        ):
            found = [min(found, key=lambda item: item.BoundingRectangle.width() * item.BoundingRectangle.height())]
    if len(found) > 1:
        details = [
            (item.ControlTypeName, item.BoundingRectangle.left, item.BoundingRectangle.top,
             item.BoundingRectangle.right, item.BoundingRectangle.bottom)
            for item in found
        ]
        raise RuntimeError(f"存在多个同名控件，无法安全定位：{details}")
    return found[0] if found else None


class BilibiliDraft:
    def __init__(self):
        # 复用 Windows MCP 已安装的 UIA 和输入实现，无需模型/MCP客户端逐步决策。
        import pyperclip
        import windows_mcp.uia as uia
        from windows_mcp.desktop.service import Desktop

        self.uia = uia
        self.clipboard = pyperclip
        self.desktop = Desktop()
        self.window = None
        self.form_left = None

    def check(self):
        """每步输入前检查取消键及窗口，窗口被切走即停，不抢回焦点。"""
        if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
            raise RuntimeError("用户按下 Esc，流程已停止。")
        if self.window and self.uia.GetForegroundControl().NativeWindowHandle != self.window.NativeWindowHandle:
            raise RuntimeError("当前窗口发生变化，流程已停止，请切回B站后重新运行。")

    def controls(self):
        """只遍历选定浏览器窗口，控件不可见时不用于坐标操作。"""
        self.check()
        result = []
        for control, _ in self.uia.WalkControl(self.window, maxDepth=45):
            try:
                snapshot = ControlSnapshot(control)
            except COMError:
                # 页面关闭弹层后旧节点会暂时失效；仅丢弃读取失效节点，不重发输入。
                continue
            result.append(snapshot)
            if len(result) > 4000:
                raise RuntimeError("控件数量过多，停止以避免定位到其他区域。")
        return result

    def visible(self, control):
        rect = control.BoundingRectangle
        window = self.window.BoundingRectangle
        return (
            rect.width() > 0 and rect.height() > 0
            and window.left < (rect.left + rect.right) / 2 < window.right
            and window.top + 100 < (rect.top + rect.bottom) / 2 < window.bottom - 20
            and not control.IsOffscreen
        )

    def control_names(self):
        """读取上传/标签状态时即时捕获名称，跳过页面刷新中失效的节点。"""
        names = []
        for control in self.controls():
            try:
                names.append(control.Name)
            except COMError:
                continue
        return names

    def locate(self, name, editable=False):
        found = []
        for control in self.controls():
            try:
                if control.Name == name and self.visible(control) and (
                    not editable or control.ControlTypeName == "EditControl"
                ):
                    found.append(control)
            except COMError:
                continue
        return choose_control(found, editable)

    def find(self, name, editable=False):
        """从当前位置向下查找，处理完上一项后不再返回页首。"""
        control = self.locate(name, editable)
        if control:
            return control
        for _ in range(14):
            control = self.locate(name, editable)
            if control:
                return control
            self.scroll_page("down", 4)
            time.sleep(0.12)
        raise RuntimeError(f"没有找到“{name}”，页面或浏览器可访问性可能发生变化。")

    def scroll_page(self, direction, amount):
        """鼠标滚轮滚动表单右侧空白处，避免在输入框内按PageDown只移动光标。"""
        self.check()
        rect = self.window.BoundingRectangle
        self.desktop.scroll(
            loc=(rect.right - 120, (rect.top + rect.bottom) // 2),
            direction=direction, wheel_times=amount,
        )
        time.sleep(0.15)

    def input_column(self):
        fields = [item for item in self.controls() if item.Name == "请输入稿件标题"]
        if len(fields) != 1:
            raise RuntimeError("无法识别表单输入列。")
        left = fields[0].BoundingRectangle.left
        if self.window.BoundingRectangle.left + 200 < left < self.window.BoundingRectangle.right - 100:
            self.form_left = left
        if self.form_left is None:
            raise RuntimeError("输入列不可见，请先定位标题。")
        return self.form_left

    def wait_name(self, name, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            control = self.locate(name)
            if control:
                return control
            time.sleep(0.15)
        raise RuntimeError(f"等待“{name}”超时。")

    def keys(self, keys):
        self.check()
        self.uia.SendKeys(keys, waitTime=0.12)

    def click(self, control):
        self.check()
        if not self.visible(control):
            raise RuntimeError("目标控件已离开可见区域，停止输入。")
        control.Click(simulateMove=True, waitTime=0.15)

    def paste(self, value):
        """通过剪贴板和Ctrl+V保留emoji；不调用网页赋值或控件SetValue。"""
        self.check()
        self.clipboard.copy(value)
        self.keys("{Ctrl}v")

    def verify_text(self, expected):
        """从当前编辑框复制回读，验证完整文本，禁止只看发送成功日志。"""
        self.keys("{Ctrl}a")
        self.clipboard.copy("")
        self.keys("{Ctrl}c")
        actual = self.clipboard.paste().replace("\r\n", "\n").strip()
        self.keys("{End}")
        if actual != expected.replace("\r\n", "\n").strip():
            raise RuntimeError("输入结果与文案不一致，流程已停止。")

    def fill(self, control, value):
        self.click(control)
        self.keys("{Ctrl}a")
        self.paste(value)
        self.verify_text(value)

    def select_browser(self):
        windows = [
            item for item in self.uia.GetRootControl().GetChildren()
            if "创作中心" in item.Name and "哔哩哔哩" in item.Name
            and any(browser in item.Name for browser in ("Edge", "Chrome", "Firefox"))
        ]
        if len(windows) != 1:
            raise RuntimeError("请只打开一个B站创作中心浏览器窗口。")
        self.window = windows[0]
        self.window.SetFocus()
        time.sleep(0.3)
        # 浏览器文档暴露页面URL时直接读取，避免地址栏复制受剪贴板竞争影响。
        for item in self.controls():
            if item.ControlTypeName == "DocumentControl" and "创作中心" in item.Name:
                pattern = item.GetValuePattern()
                if pattern and is_upload_url(pattern.Value):
                    return
        self.keys("{Ctrl}l")
        self.clipboard.copy("")
        self.keys("{Ctrl}c")
        url = self.clipboard.paste()
        self.keys("{Esc}")
        if not is_upload_url(url):
            raise RuntimeError("当前标签页不是B站视频投稿页面。")

    def upload(self, video):
        names = self.control_names()
        if "请输入稿件标题" in names:
            if video.stem not in names:
                raise RuntimeError("当前稿件的视频名与素材不一致，请打开空白投稿页面后重试。")
            print("检测到已有稿件，填写当前稿件，不重复上传。", flush=True)
            return
        # 上传区域的文本节点也有矩形，使用真实鼠标点击它。
        self.click(self.find("上传视频"))
        self.choose_file(video)

    def choose_file(self, path):
        """共用系统文件选择框：填写明确路径，返回浏览器后再执行后续步骤。"""
        deadline = time.monotonic() + 8
        dialog = None
        while time.monotonic() < deadline:
            foreground = self.uia.GetForegroundControl()
            if foreground.Name == "打开":
                dialog = foreground
                break
            time.sleep(0.1)
        if dialog is None:
            raise RuntimeError("文件选择窗口未出现。")
        # 文件窗口是唯一允许的临时焦点切换；文件名仅为视频路径，不执行命令。
        browser = self.window
        self.window = dialog
        entries = [
            item for item, _ in self.uia.WalkControl(dialog, maxDepth=12)
            if item.ControlTypeName == "EditControl" and "文件名" in item.Name
        ]
        if len(entries) == 1:
            self.fill(entries[0], str(path))
        elif not entries:
            # 系统文件框部分版本不暴露子控件；Alt+N是“文件名”的原生快捷键。
            # 回读路径一致才确认，避免把文件路径写入其他控件。
            self.keys("{Alt}n")
            self.keys("{Ctrl}a")
            self.paste(str(path))
            self.verify_text(str(path))
        else:
            raise RuntimeError("存在多个文件名输入框。")
        self.keys("{Enter}")
        deadline = time.monotonic() + 8
        while self.uia.GetForegroundControl().NativeWindowHandle != browser.NativeWindowHandle:
            if time.monotonic() > deadline:
                raise RuntimeError("文件选择窗口未关闭，请检查文件路径。")
            time.sleep(0.1)
        self.window = browser

    def cover(self, path):
        label = self.find("封面")
        rect = label.BoundingRectangle
        # 由表单输入列和封面所在行定位预览，避免固定屏幕坐标。
        self.desktop.click((self.input_column() + 65, (rect.top + rect.bottom) // 2 + 30))
        self.wait_name("封面制作")
        self.click(self.wait_name("上传封面"))
        self.choose_file(path)
        self.wait_name("双比例同步改动")
        # 新上传图片使用页面默认居中位置；同步开启时同一图片用于两种比例。
        sync = self.locate("双比例同步改动")
        rect = sync.BoundingRectangle
        checkbox = [
            item for item in self.controls()
            if item.ControlTypeName == "CheckBoxControl" and self.visible(item)
            and abs(item.BoundingRectangle.top - rect.top) < 25
        ]
        if checkbox and len(checkbox) == 1:
            pattern = checkbox[0].GetTogglePattern()
            if int(pattern.ToggleState) == 0:
                self.click(checkbox[0])
        # 保留上传后的默认居中和缩放，不点击顶部滑块或移动图片。
        self.click(self.wait_name("完成"))
        deadline = time.monotonic() + 10
        while self.locate("封面制作"):
            if time.monotonic() > deadline:
                raise RuntimeError("封面编辑器未关闭，停止后续操作。")
            time.sleep(0.2)
        print("同一封面已上传；使用默认居中位置，请最终检查两种比例的文字。", flush=True)

    def declaration(self):
        entry = self.find("请选择符合您视频内容的创作声明", editable=True)
        if entry.GetValuePattern().Value == "含AI生成内容":
            return
        if entry.BoundingRectangle.bottom > self.window.BoundingRectangle.bottom - 250:
            self.scroll_page("down", 4)
            entry = self.find("请选择符合您视频内容的创作声明", editable=True)
        self.click(entry)
        self.click(self.wait_name("含AI生成内容"))
        entry = self.find("请选择符合您视频内容的创作声明", editable=True)
        if entry.GetValuePattern().Value != "含AI生成内容":
            raise RuntimeError("未确认AI创作声明。")

    def category(self, value):
        label = self.find("分区")
        rect = label.BoundingRectangle
        if any(
            item.Name == value and self.visible(item)
            and abs(item.BoundingRectangle.top - rect.top) < 30
            for item in self.controls()
        ):
            return
        self.desktop.click((self.input_column() + 100, (rect.top + rect.bottom) // 2))
        loc = (self.input_column() + 100, rect.bottom + 130)
        self.desktop.scroll(loc=loc, direction="up", wheel_times=30)
        for _ in range(16):
            option = self.locate(value)
            if option:
                self.click(option)
                break
            self.check()
            self.desktop.scroll(loc=loc, direction="down", wheel_times=2)
            time.sleep(0.15)
        else:
            raise RuntimeError(f"分区列表中没有找到{value}。")
        time.sleep(0.2)
        label = self.find("分区")
        if not any(
            item.Name == value and self.visible(item)
            and abs(item.BoundingRectangle.top - label.BoundingRectangle.top) < 30
            for item in self.controls()
        ):
            raise RuntimeError(f"未确认{value}分区。")

    def wait_uploaded(self):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            names = self.control_names()
            if "上传完成" in names:
                print("视频上传完成。", flush=True)
                return
            if any("上传失败" in name for name in names):
                raise RuntimeError("视频上传失败，请检查网络或文件。")
            time.sleep(0.5)
        raise RuntimeError("上传等待超过3分钟，流程已停止。")

    def fill_tags(self, tags):
        entry = self.find("按回车键Enter创建标签", editable=True)
        self.click(entry)
        self.keys("{Ctrl}a{Back}")
        # 空输入框Backspace逐个删除标签；以页面剩余容量确认，不用固定点击X坐标。
        for _ in range(21):
            if any("还可以添加10个标签" in name for name in self.control_names()):
                break
            self.keys("{Back}")
        else:
            raise RuntimeError("旧标签未能清理，请手动清空标签后重试。")
        for index, tag in enumerate(tags, 1):
            self.click(self.find("按回车键Enter创建标签", editable=True))
            self.paste(tag)
            self.keys("{Enter}")
            deadline = time.monotonic() + 3
            expected = f"还可以添加{10 - index}个标签"
            while time.monotonic() < deadline:
                if any(expected in name for name in self.control_names()):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError(f"未确认标签关联：{tag}。")

    def description(self, value):
        hint = "填写更全面的相关信息，让更多的人能找到你的视频吧"
        for control in self.controls():
            if control.Name == hint and self.visible(control):
                self.fill(control, value)
                return
        # 已填内容时提示消失：以“简介”所在行和标题输入框的列定位正文区域。
        # ponytail: 只支持B站当前表单布局；标签与输入列无法同时确认时停止。
        label = self.find("简介")
        title_controls = [item for item in self.controls() if item.Name == "请输入稿件标题"]
        if len(title_controls) != 1:
            raise RuntimeError("无法识别简介所在的表单输入列。")
        left = self.input_column()
        rect = label.BoundingRectangle
        self.check()
        self.desktop.click((left + 30, (rect.top + rect.bottom) // 2))
        self.keys("{Ctrl}a")
        # 先确认焦点处于正文，而非页面或其他输入框。
        focus = self.uia.GetFocusedControl()
        editor_types = ("EditControl", "DocumentControl", "GroupControl", "CustomControl")
        if focus is None or focus.ControlTypeName not in editor_types:
            raise RuntimeError("简介未获得编辑焦点，停止输入。")
        if focus.AutomationId == "RootWebArea":
            raise RuntimeError("焦点为整个页面，停止输入。")
        self.paste(value)
        self.verify_text(value)

    def schedule_fields(self):
        """仅识别定时发布行下方的日期/时间文本，不混淆时区输入框。"""
        label = self.find("定时发布")
        top = label.BoundingRectangle.top
        fields = [
            item for item in self.controls()
            if self.visible(item) and item.ControlTypeName == "TextControl"
            and top + 25 < item.BoundingRectangle.top < top + 90
        ]
        dates = [item for item in fields if re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.Name)]
        times = [item for item in fields if re.fullmatch(r"\d{2}:\d{2}", item.Name)]
        return choose_control(dates), choose_control(times)

    def schedule(self, selected):
        """通过日历和小时/分钟滚动列选择时间，并回读最终日期时间。"""
        label = self.find("定时发布")
        date, clock = self.schedule_fields()
        if bool(date) != bool(selected):
            rect = label.BoundingRectangle
            self.check()
            self.desktop.click((self.input_column() + 16, (rect.top + rect.bottom) // 2))
            time.sleep(0.2)
        if selected is None:
            if self.schedule_fields()[0] is not None:
                raise RuntimeError("未确认关闭定时发布。")
            return
        parse_publish_time(selected.strftime("%Y-%m-%d %H:%M"))
        date, clock = self.schedule_fields()
        if date is None or clock is None:
            raise RuntimeError("无法识别定时发布日期和时间。")
        self.click(date)
        target_month = selected.strftime("%Y年%m月").replace("年0", "年")
        for _ in range(2):
            headers = [
                item for item in self.controls() if self.visible(item)
                and re.fullmatch(r"\d{4}年\d{1,2}月", item.Name)
            ]
            header = choose_control(headers)
            if header is None:
                raise RuntimeError("无法识别日期日历。")
            if header.Name == target_month:
                break
            # 日期范围最多15天，仅跨到下一个月；箭头相对日历标题定位。
            rect = header.BoundingRectangle
            self.check()
            self.desktop.click(((rect.left + rect.right) // 2 + 80, (rect.top + rect.bottom) // 2))
            time.sleep(0.2)
        else:
            raise RuntimeError("日历月份不符合所选日期。")
        rect = header.BoundingRectangle
        day = choose_control([
            item for item in self.controls()
            if item.Name == str(selected.day) and self.visible(item)
            and rect.top + 45 < item.BoundingRectangle.top < rect.top + 240
            and rect.left - 130 < item.BoundingRectangle.left < rect.right + 130
        ])
        if day is None:
            raise RuntimeError("所选日期没有可点击的日历项。")
        self.click(day)
        _, clock = self.schedule_fields()
        self.click(clock)
        clock_rect = clock.BoundingRectangle
        for offset, value in ((15, f"{selected.hour:02d}"), (82, f"{selected.minute:02d}")):
            # 每列先滚到顶部，再逐步寻找可见文字，避免固定等待或盲点位置。
            loc = (clock_rect.left + offset, clock_rect.top - 100)
            self.check()
            self.desktop.scroll(loc=loc, direction="up", wheel_times=30)
            for _ in range(30):
                options = [
                    item for item in self.controls()
                    if item.Name == value and self.visible(item)
                    and clock_rect.top - 245 < item.BoundingRectangle.top < clock_rect.top - 15
                    and abs((item.BoundingRectangle.left + item.BoundingRectangle.right) / 2 - loc[0]) < 25
                ]
                option = choose_control(options)
                if option:
                    self.click(option)
                    break
                self.desktop.scroll(loc=loc, direction="down", wheel_times=1)
                time.sleep(0.1)
            else:
                raise RuntimeError(f"没有找到时间选项{value}。")
        self.click(self.find("定时发布"))
        date, clock = self.schedule_fields()
        if date is None or clock is None or (
            date.Name != selected.strftime("%Y-%m-%d")
            or clock.Name != selected.strftime("%H:%M")
        ):
            raise RuntimeError("定时发布结果与所选时间不一致。")

    def run(self, video, title, description, tags, cover, category, publish_at):
        self.select_browser()
        self.upload(video)
        self.wait_uploaded()
        # 一次回到表单开头；后续查找只向下，先封面再标题。
        self.scroll_page("up", 30)
        self.input_column()
        self.cover(cover)
        self.fill(self.find("请输入稿件标题", editable=True), title)
        print("标题已核对。", flush=True)
        self.declaration()
        self.category(category)
        self.fill_tags(tags)
        print("标签已确认。", flush=True)
        self.description(description)
        print("简介已核对。", flush=True)
        self.schedule(publish_at)
        self.find("立即投稿")  # 只定位并滚动到提交区域，绝不点击该控件。
        print("准备完成，已停在立即投稿前。请检查封面、分区和创作声明。", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", type=Path)
    parser.add_argument("--check", action="store_true", help="只检查素材，不操作鼠标键盘")
    parser.add_argument("--publish-at", help="北京时间 YYYY-MM-DD HH:MM；空字符串表示不定时")
    args = parser.parse_args()
    if args.check:
        if args.folder is None:
            parser.error("--check需要指定素材目录")
        prepared = prepare_files(args.folder)
        cover = cover_from_folder(args.folder)
        category = category_from_folder(args.folder)
        parse_publish_time(args.publish_at or "")
        print(f"素材检查通过：{prepared[0]}；封面：{cover.name}；分区：{category}")
        return
    root = tk.Tk()
    root.withdraw()
    status = Path(__file__).with_name("bilibili_auto_status.json")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, False, "Local\\CreatorPublishHelperBilibiliDraft")
    if not mutex:
        root.destroy()
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        messagebox.showinfo("任务已在运行", "请等待当前任务结束，并关闭结果提示后再启动。")
        root.destroy()
        return
    try:
        folder = args.folder
        if folder is None:
            chosen = filedialog.askdirectory(title="选择含视频和发布文案的视频目录")
            if not chosen:
                return
            folder = Path(chosen)
        prepared = prepare_files(folder)
        cover = cover_from_folder(folder)
        category = category_from_folder(folder)
        publish_at = args.publish_at
        if publish_at is None:
            publish_at = simpledialog.askstring(
                "定时发布", "输入北京时间 YYYY-MM-DD HH:MM（5分钟间隔）。\n留空不定时；取消则结束。",
                parent=root,
            )
            if publish_at is None:
                return
        selected = parse_publish_time(publish_at)
        BilibiliDraft().run(*prepared, cover, category, selected)
        status.write_text(json.dumps({"ok": True, "message": "已停在投稿前"}, ensure_ascii=False), encoding="utf-8")
        schedule_text = selected.strftime("%Y-%m-%d %H:%M 北京时间") if selected else "未开启定时"
        messagebox.showinfo(
            "B站准备完成", f"已停在立即投稿前。\n分区：{category}；声明：含AI生成内容\n{schedule_text}\n请检查封面两种比例，再自行提交。",
        )
    except Exception as error:
        status.write_text(json.dumps({
            "ok": False, "message": str(error), "traceback": traceback.format_exc(),
        }, ensure_ascii=False), encoding="utf-8")
        print(f"流程停止：{error}", flush=True)
        messagebox.showerror("B站自动化已停止", str(error))
    finally:
        kernel.CloseHandle(mutex)
        root.destroy()


if __name__ == "__main__":
    main()

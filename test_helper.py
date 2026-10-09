"""不触发输入的离线检查。"""

from pathlib import Path
import tempfile
from types import SimpleNamespace
from datetime import datetime, timedelta

from PIL import Image, ImageDraw

from fill_helper import candidate_stable, candidate_visible, detect_platform, read_copy, discard_pending_hotkeys
from focus_detection import classify_field
from bilibili_auto import (
    BilibiliDraft, CHINA_TIME, ControlSnapshot, category_from_folder, choose_control, cover_from_folder,
    is_upload_url, parse_publish_time, prepare_files,
)


def main():
    source = SimpleNamespace(
        Name="上传完成", ControlTypeName="TextControl",
        BoundingRectangle=object(), IsOffscreen=False,
    )
    snapshot = ControlSnapshot(source)
    source.Name = "页面已刷新"
    assert snapshot.Name == "上传完成"
    # 控件寻找只向下滚动；正确声明和分区不得发送点击或滚动。
    draft = object.__new__(BilibiliDraft)
    target = object()
    observations = iter((None, None, target))
    scrolls = []
    draft.locate = lambda name, editable=False: next(observations)
    draft.scroll_page = lambda direction, amount: scrolls.append(direction)
    assert draft.find("标题") is target
    assert scrolls == ["down"]
    correct = SimpleNamespace(GetValuePattern=lambda: SimpleNamespace(Value="含AI生成内容"))
    draft.find = lambda name, editable=False: correct
    draft.click = lambda control: (_ for _ in ()).throw(AssertionError("正确声明不应点击"))
    draft.declaration()
    label = SimpleNamespace(BoundingRectangle=SimpleNamespace(top=300))
    draft.find = lambda name, editable=False: label
    draft.controls = lambda: [SimpleNamespace(Name="舞蹈", BoundingRectangle=SimpleNamespace(top=300))]
    draft.visible = lambda control: True
    draft.category("舞蹈")
    now = datetime(2026, 10, 9, 12, 0, tzinfo=CHINA_TIME)
    assert parse_publish_time("", now) is None
    assert parse_publish_time("2026-10-09 12:05", now) == now + timedelta(minutes=5)
    assert parse_publish_time("2026-10-24 12:00", now) == now + timedelta(days=15)
    for value in (
        "2026-10-09 12:04", "2026-10-09 13:01", "2026-10-24 12:01",
        "2026-02-30 12:00", "下午六点",
    ):
        try:
            parse_publish_time(value, now)
        except ValueError:
            pass
        else:
            raise AssertionError("应拒绝格式错误或超出范围的定时时间")
    assert category_from_folder(Path("028_跳舞_测试")) == "舞蹈"
    assert category_from_folder(Path("028_唱歌_测试")) == "音乐"
    for folder_name in ("未知", "028_跳舞_唱歌"):
        try:
            category_from_folder(Path(folder_name))
        except ValueError:
            pass
        else:
            raise AssertionError("不应猜测分区")
    with tempfile.TemporaryDirectory() as folder:
        try:
            cover_from_folder(Path(folder))
        except ValueError:
            pass
        else:
            raise AssertionError("缺少封面必须停止")
        for name in ("封面.jpg", "封面.png", "B站4x3.png"):
            (Path(folder) / name).touch()
            assert cover_from_folder(Path(folder)).name == name
        path = Path(folder) / "文案.txt"
        path.write_text("标题：\n测试\n简介：\n第一行💃\n第二行\n标签：\n#舞蹈 #穿搭 #舞蹈", encoding="utf-8")
        title, description, tags = read_copy(path)
        assert title == "测试" and "💃" in description and "\n" in description
        assert tags == ["舞蹈", "穿搭"]
        (Path(folder) / "发布文案.txt").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        (Path(folder) / "最终成片.mp4").touch()
        video, auto_title, auto_description, auto_tags = prepare_files(Path(folder))
        assert video.name == "最终成片.mp4" and auto_title == title
        assert auto_description == description and auto_tags == tags
        (Path(folder) / "最终成片.mp4").unlink()
        for name in ("一.mp4", "二.mp4"):
            (Path(folder) / name).touch()
        try:
            prepare_files(Path(folder))
        except ValueError:
            pass
        else:
            raise AssertionError("应拒绝不明确的视频选择")
        path.write_text("标题：只有标题", encoding="utf-8")
        try:
            read_copy(path)
        except ValueError:
            pass
        else:
            raise AssertionError("应拒绝缺失章节的文案")
    assert detect_platform("创作中心 - 哔哩哔哩 - Microsoft Edge") == "bilibili"
    assert is_upload_url("https://member.bilibili.com/platform/upload/video/frame")
    assert not is_upload_url("https://member.bilibili.com.evil.test/platform/upload/video")
    assert not is_upload_url("https://member.bilibili.com/platform/home")
    def node(kind, left, top, width=30, height=20):
        box = SimpleNamespace(
            left=left, top=top, right=left + width, bottom=top + height,
            width=lambda: width, height=lambda: height,
        )
        return SimpleNamespace(ControlTypeName=kind, BoundingRectangle=box)

    label = node("TextControl", 100, 200)
    container = node("GroupControl", 100, 200, 600, 160)
    nested_label = node("TextControl", 102, 202)
    assert choose_control([container, label, nested_label]) is label
    assert choose_control([]) is None
    try:
        choose_control([label, node("TextControl", 100, 500)])
    except RuntimeError:
        pass
    else:
        raise AssertionError("不能合并不同位置的同名控件")
    assert detect_platform("抖音创作者中心") == "douyin"
    assert detect_platform("小红书创作服务平台") == "xiaohongshu"
    for title in ["其他网页", "抖音 - 小红书"]:
        try:
            detect_platform(title)
        except ValueError:
            pass
        else:
            raise AssertionError("应拒绝未知或歧义平台")
    before = Image.new("RGB", (400, 200), "white")
    after = before.copy()
    ImageDraw.Draw(after).rectangle((10, 10, 300, 100), fill=(245, 245, 245))
    assert candidate_visible(before, after)
    assert not candidate_visible(before, before)
    assert candidate_stable(after, after)
    assert not candidate_stable(before, after)
    def observation(name="", labels=(), focused=True):
        return {"controls": [{"name": name, "focused": focused}], "nearby_labels": list(labels)}

    assert classify_field("xiaohongshu", observation("填写标题会有更多赞哦")) == "title"
    assert classify_field("xiaohongshu", observation("输入正文描述，真诚有价值的分享予人温暖")) == "description"
    assert classify_field("douyin", observation("添加作品描述")) == "description"
    assert classify_field("bilibili", observation("按回车键Enter创建标签")) == "tags"
    assert classify_field("bilibili", observation(labels=["* 标题"])) == "title"
    assert classify_field("bilibili", observation(labels=["简介"])) == "description"
    assert classify_field("xiaohongshu", observation(labels=["输入正文描述，真诚有价值的分享予人温暖"])) == "description"
    assert classify_field("bilibili", observation("填写标题", labels=["简介"])) == "title"
    assert classify_field("douyin", observation("添加作品简介")) == "description"
    assert classify_field("bilibili", observation("请输入稿件标题")) == "title"
    rich_editor = {"controls": [{
        "focus_origin": True, "focused": False, "control_type": "ControlType.Group",
        "text_read_only": False,
    }]}
    assert classify_field("douyin", rich_editor) == "description"
    for control in [
        {"focus_origin": True, "automation_id": "RootWebArea", "text_read_only": False},
        {"focus_origin": True, "control_type": "ControlType.Group", "text_read_only": True},
        {"focus_origin": True, "control_type": "ControlType.Edit", "text_read_only": False},
    ]:
        try:
            classify_field("douyin", {"controls": [control]})
        except ValueError:
            pass
        else:
            raise AssertionError("整页、只读控件和未知单行输入框不能视为正文")
    for invalid in [observation(), observation(labels=["标题", "简介"]), observation("标题", focused=False)]:
        try:
            classify_field("bilibili", invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("未知、歧义或未聚焦控件必须拒绝填写")
    class PendingMessages:
        def __init__(self, actions):
            self.actions = list(actions)

        def PeekMessageW(self, pointer, window, minimum, maximum, remove):
            assert minimum == maximum == 0x312 and remove == 1
            if not self.actions:
                return 0
            pointer._obj.wParam = self.actions.pop(0)
            return 1

    assert discard_pending_hotkeys(PendingMessages([1, 1, 5])) == (3, False)
    assert discard_pending_hotkeys(PendingMessages([1, 4, 1])) == (2, True)
    assert discard_pending_hotkeys(PendingMessages([])) == (0, False)
    print("文案、平台、焦点、候选检测及重复热键队列检查通过")


if __name__ == "__main__":
    main()

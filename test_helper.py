"""不触发输入的离线检查。"""

from pathlib import Path
import tempfile

from PIL import Image, ImageDraw

from fill_helper import candidate_stable, candidate_visible, detect_platform, read_copy
from focus_detection import classify_field


def main():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "文案.txt"
        path.write_text("标题：\n测试\n简介：\n第一行💃\n第二行\n标签：\n#舞蹈 #穿搭 #舞蹈", encoding="utf-8")
        title, description, tags = read_copy(path)
        assert title == "测试" and "💃" in description and "\n" in description
        assert tags == ["舞蹈", "穿搭"]
        path.write_text("标题：只有标题", encoding="utf-8")
        try:
            read_copy(path)
        except ValueError:
            pass
        else:
            raise AssertionError("应拒绝缺失章节的文案")
    assert detect_platform("创作中心 - 哔哩哔哩 - Microsoft Edge") == "bilibili"
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
    print("文案解析、平台识别、焦点字段识别与候选检测检查通过")


if __name__ == "__main__":
    main()

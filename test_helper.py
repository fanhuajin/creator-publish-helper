"""不触发输入的离线检查。"""

from pathlib import Path
import tempfile

from PIL import Image, ImageDraw

from fill_helper import candidate_stable, candidate_visible, detect_platform, read_copy


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
    print("文案解析、平台识别与候选检测检查通过")


if __name__ == "__main__":
    main()

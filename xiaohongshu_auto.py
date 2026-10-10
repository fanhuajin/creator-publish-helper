"""小红书作品文件夹批量发布。"""
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from douyin_auto import DouyinDraft


class XiaohongshuDraft(DouyinDraft):
    page_title = "小红书创作服务平台"

    def select_browser(self):
        windows = [w for w in self.uia.GetRootControl().GetChildren()
                   if any(browser in w.Name for browser in ("Edge", "Chrome"))]
        candidates = []
        for window in windows:
            for item, _ in self.uia.WalkControl(window, maxDepth=20):
                if item.ControlTypeName == "TabItemControl" and "小红书创作服务平台" in item.Name:
                    candidates.append((window, item))
        if len(candidates) != 1:
            raise RuntimeError("请只打开一个小红书创作服务平台标签页。")
        self.window, tab = candidates[0]
        self.window.SetFocus()
        time.sleep(0.4)
        r = tab.BoundingRectangle
        if r.width() <= 0:
            raise RuntimeError("小红书标签页不可见。")
        self.click_at(((r.left+r.right)//2,(r.top+r.bottom)//2))
        time.sleep(0.3)
        from browser_page import read_browser_url
        url = urlsplit(read_browser_url(self.uia, self.window, self.page_title))
        if url.hostname != "creator.xiaohongshu.com":
            raise RuntimeError("当前页面不是小红书创作服务平台。")

    def dump(self):
        data=[]
        for c in self.controls():
            r=c.BoundingRectangle
            data.append({"name":c.Name,"type":c.ControlTypeName,"visible":self.visible(c),"rect":[r.left,r.top,r.right,r.bottom]})
        Path(__file__).with_name("xiaohongshu_controls.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")


    def scroll_form(self, direction, amount=5):
        button = next(c for c in self.controls() if c.Name == "暂存离开" and self.visible(c))
        r = button.BoundingRectangle
        self.move_pointer((r.left-300, r.top-150))
        self.scroll_at(direction, amount)
        time.sleep(0.4)

    def form_find(self, name, editable=False, direction="down"):
        for _ in range(20):
            self.check()
            target = self.locate(name, editable)
            if target:
                return target
            self.scroll_form(direction, 4)
        raise RuntimeError(f"未找到小红书控件：{name}")

    def set_cover(self, path):
        if self.locate("完成"):
            self.finish_cover()
        label = self.form_find("设置封面", direction="up")
        r = label.BoundingRectangle
        previews = [c for c in self.controls() if c.ControlTypeName == "GroupControl" and not c.Name
                    and self.visible(c) and abs(c.BoundingRectangle.left-r.left)<25
                    and r.bottom<c.BoundingRectangle.top<r.bottom+180
                    and 100<c.BoundingRectangle.width()<250 and c.BoundingRectangle.height()>150]
        if not previews:
            raise RuntimeError("未找到封面预览。")
        p = previews[0].BoundingRectangle
        self.move_pointer(((p.left+p.right)//2,p.bottom-40))
        self.click(self.wait_name("编辑封面"))
        self.click(self.wait_name("上传"))
        self.choose_file(path)
        self.wait_name("已上传封面", timeout=30)
        self.finish_cover()
        self.wait_name("封面效果评估通过，未发现封面质量问题", timeout=60)

    def finish_cover(self):
        # 文件名出现时图片仍可能加载；等待按钮可用，并确认编辑窗口确实关闭。
        deadline = self.now() + 90
        ready_since = None
        last_click = 0
        while self.now() < deadline:
            self.check()
            button = self.locate("完成")
            if button is None:
                return
            uploaded = self.locate("已上传封面")
            if uploaded and button.IsEnabled:
                ready_since = ready_since or self.now()
                if self.now()-ready_since >= 3 and self.now()-last_click >= 5:
                    self.click(button)
                    last_click = self.now()
            else:
                ready_since = None
            time.sleep(0.4)
        raise RuntimeError("封面加载或保存超过90秒，已保留当前稿件。")

    def schedule(self, selected):
        label = self.form_find("定时发布")
        def entry():
            return next((c for c in self.controls() if c.ControlTypeName == "EditControl"
                         and self.visible(c) and c.BoundingRectangle.width()>300
                         and c.BoundingRectangle.top>label.BoundingRectangle.top-20), None)
        e = entry()
        if bool(e) != bool(selected):
            r = label.BoundingRectangle
            toggle = next(c for c in self.controls() if c.ControlTypeName == "GroupControl" and not c.Name
                          and self.visible(c) and abs(c.BoundingRectangle.top-r.top)<10
                          and 40<c.BoundingRectangle.width()<60 and c.BoundingRectangle.left>r.right)
            self.click(toggle)
            time.sleep(0.4)
        if not selected:
            return
        e = entry()
        if e is None:
            raise RuntimeError("定时时间输入框未出现。")
        self.click(e)
        time.sleep(0.4)
        from datetime import datetime, timedelta
        for _ in range(3):
            cs = self.controls()
            year = next(c for c in cs if c.Name.endswith("年") and c.Name[:-1].isdigit() and self.visible(c))
            month = next(c for c in cs if c.Name.endswith("月") and c.Name[:-1].isdigit() and self.visible(c))
            if int(year.Name[:-1]) == selected.year and int(month.Name[:-1]) == selected.month:
                break
            buttons = [c for c in cs if self.visible(c) and c.ControlTypeName == "ButtonControl"
                       and any(word in c.Name for word in ("下个月", "下一月", "Next month"))]
            if not buttons:
                raise RuntimeError("无法找到日历下月按钮。")
            self.click(buttons[0])
        else:
            raise RuntimeError("日历月份不匹配。")
        # 六行日历从当月1号所在周的周一开始；排除相邻月份同名日期。
        first = datetime(selected.year,selected.month,1)
        index = selected.day-1+first.weekday()
        mr = month.BoundingRectangle
        days = [c for c in self.controls() if self.visible(c) and c.Name.isdigit()
                and mr.left-210<c.BoundingRectangle.left<mr.left+160
                and mr.bottom+50<c.BoundingRectangle.top<mr.bottom+340]
        days.sort(key=lambda c:(c.BoundingRectangle.top,c.BoundingRectangle.left))
        unique = {}
        for c in days:
            r=c.BoundingRectangle
            unique.setdefault((r.left,r.top),c)
        days=list(unique.values())
        if len(days)<index+1 or days[index].Name != str(selected.day):
            raise RuntimeError("日历日期布局变化，停止选择。")
        self.click(days[index])
        hour_label = self.wait_name("时")
        hr=hour_label.BoundingRectangle
        self.move_pointer((hr.left-10,hr.top+120))
        self.scroll_at("up", 15)
        time.sleep(0.3)
        for _ in range(30):
            self.check()
            options=[c for c in self.controls() if self.visible(c) and c.Name==f"{selected.hour:02d}"
                     and hr.left-50<c.BoundingRectangle.left<hr.right
                     and hr.top-10<c.BoundingRectangle.top<hr.top+370]
            if options:
                self.click(options[0])
                break
            self.scroll_at("down", 1)
            time.sleep(0.15)
        else:
            raise RuntimeError("小时列表未找到目标小时。")
        r=e.BoundingRectangle
        self.click_at((r.left-35,r.top-40))
        value=entry().GetValuePattern().Value
        actual=datetime.strptime(value,"%Y-%m-%d %H:%M").replace(tzinfo=selected.tzinfo)
        if (actual.date(),actual.hour)!=(selected.date(),selected.hour):
            raise RuntimeError("页面日期或小时与队列不一致。")
        now=datetime.now(selected.tzinfo)
        if not now+timedelta(hours=1)<=actual<=now+timedelta(days=14):
            raise RuntimeError("页面时间须在1小时后、14天内。")
        self.actual_publish_at=value

    def run(self, video, title, description, tags, cover, category, publish_at):
        self.select_browser()
        if self.locate("完成"):
            self.finish_cover()
        hint="填写标题会有更多赞哦"
        existing=next((c for c in self.controls() if c.Name==hint and c.ControlTypeName=="EditControl"),None)
        if existing:
            if existing.GetValuePattern().Value != title:
                raise RuntimeError("当前小红书稿件与队列作品不一致，请先处理当前稿件。")
        else:
            self.next_upload()
            upload=next(c for c in self.controls() if c.Name=="上传视频" and c.ControlTypeName=="ButtonControl" and self.visible(c))
            self.click(upload)
            self.choose_file(video)
            self.wait_name(hint, timeout=60)
        self.start_keyboard_helper(video.parent/"发布文案.txt")
        self.keyboard_fill(self.form_find(hint,editable=True,direction="up"),"title",title)
        body=self.locate("输入正文描述，真诚有价值的分享予人温暖")
        if not body:
            body=next((c for c in self.controls() if self.visible(c) and c.Name.strip()==description.strip()),None)
        if body is None:
            raise RuntimeError("未找到正文编辑区。")
        self.click(body)
        # 重启续跑时先清空已有正文，让原始提示恢复，按键助手才能明确识别字段。
        self.keys("{Ctrl}a{Back}")
        self.click(self.wait_name("输入正文描述，真诚有价值的分享予人温暖"))
        self.keyboard_field("description")
        self.set_cover(cover)
        declaration=self.form_find("添加内容类型声明")
        if not self.locate("笔记含AI合成内容"):
            self.click(declaration)
            self.click(self.wait_name("笔记含AI合成内容"))
        self.schedule(publish_at)
        self.wait_uploaded()
        name="定时发布" if publish_at else "发布"
        button=next(c for c in self.controls() if c.Name==name and c.ControlTypeName=="ButtonControl" and self.visible(c))
        self.click(button)
        deadline=self.now()+60
        while self.now()<deadline:
            self.check()
            names=self.control_names()
            if any(n in names for n in ("发布成功", "笔记发布成功", "定时发布成功")):
                return
            form=any(c.Name==hint and c.ControlTypeName=="EditControl" for c in self.controls())
            if not form and "笔记管理" in names and any(title in n for n in names):
                return
            time.sleep(0.5)
        raise RuntimeError("已点击发布，但未确认成功；请检查笔记管理，避免重复提交。")

    def next_upload(self):
        if self.locate("上传视频"):
            return
        self.click(self.wait_name("发布笔记",timeout=30))
        self.wait_name("上传视频",timeout=30)


def prepare_xiaohongshu(folder):
    from bilibili_auto import prepare_files
    data=prepare_files(folder)
    if len(data[1])>20:
        raise ValueError("小红书标题最多20字，请修改发布文案。")
    return data


def xiaohongshu_cover(folder):
    path=folder/"抖音3x4.png"
    if not path.is_file():
        raise ValueError("作品缺少抖音3x4.png封面。")
    return path.resolve()


def select_xiaohongshu_hour(date,hour):
    from datetime import datetime,timedelta
    from bilibili_auto import CHINA_TIME
    now=datetime.now(CHINA_TIME)
    start=datetime.strptime(f"{date} {hour}","%Y-%m-%d %H").replace(tzinfo=CHINA_TIME)
    if start+timedelta(minutes=59)<now+timedelta(hours=1) or start>now+timedelta(days=14):
        raise ValueError("小红书定时应在北京时间1小时后、14天内。")
    return start


def main():
    import tkinter as tk
    from publish_queue import PublishQueue
    from bilibili_auto import CHINA_TIME
    root=tk.Tk()
    root.withdraw()
    PublishQueue(root,XiaohongshuDraft,select_xiaohongshu_hour,prepare_xiaohongshu,xiaohongshu_cover,
                 lambda folder:None,CHINA_TIME,Path(__file__).with_name("xiaohongshu_auto_status.json"),
                 publish_at="2026-10-10 01:00",platform="xiaohongshu").show()


if __name__ == "__main__":
    main()

"""小红书小时列表定位和失败诊断；不输入日期/时间文本。"""
import json
import re
from datetime import datetime
from pathlib import Path


def hour_options(draft):
    from bilibili_auto import CHINA_TIME, choose_control
    controls=draft.controls()
    # 保存本轮已读取的时间相关节点，失败时不重新抓全页或抢回焦点。
    visible=[c for c in controls if draft.visible(c)
             and re.fullmatch(r"(?:\d{1,2}(?:时|分)?|\d{2}:\d{2}|时|分)",c.Name)]
    def record(c):
        r=c.BoundingRectangle
        return {"name":c.Name,"type":c.ControlTypeName,"rect":[r.left,r.top,r.right,r.bottom]}
    draft.xiaohongshu_hour_snapshot={"captured_at":datetime.now(CHINA_TIME).isoformat(timespec="seconds"),
                                   "candidates":[record(c) for c in visible]}
    labels=[c for c in visible if c.Name=="时"]
    if not labels:
        # 未选中的小时不会暴露“时”；用分钟列和连续垂直小时列共同确认。
        minute_labels=[c for c in visible if c.Name=="分"]
        if len(minute_labels)!=1:
            return []
        minute=minute_labels[0].BoundingRectangle
        groups={}
        for c in visible:
            r=c.BoundingRectangle
            if (re.fullmatch(r"\d{2}",c.Name)
                    and c.ControlTypeName in ("TextControl","ListItemControl")
                    and minute.left-160<r.left<minute.left-40
                    and minute.top-10<r.top<minute.top+370):
                groups.setdefault(round(r.left/8),[]).append(c)
        columns=[]
        for group in groups.values():
            group.sort(key=lambda c:c.BoundingRectangle.top)
            values=[int(c.Name) for c in group]
            gaps=[b.BoundingRectangle.top-a.BoundingRectangle.top for a,b in zip(group,group[1:])]
            if (len(group)>=3 and all(0<=v<=23 for v in values)
                    and all(b==a+1 for a,b in zip(values,values[1:]))
                    and all(25<=gap<=65 for gap in gaps)):
                columns.append(group)
        return columns[0] if len(columns)==1 else []
    label=choose_control(labels)
    hr=label.BoundingRectangle
    options=[c for c in visible if re.fullmatch(r"\d{2}(?:时)?",c.Name)
             and c.ControlTypeName in ("TextControl","ListItemControl")
             and hr.left-50<c.BoundingRectangle.left<hr.right
             and hr.top-10<c.BoundingRectangle.top<hr.top+370]
    if any(int(c.Name.removesuffix("时"))>23 for c in options):
        raise RuntimeError("小红书小时列包含无效小时，未滚动或发布。")
    return options


def choose_hour(draft, selected):
    from schedule_controls import scroll_select
    try:
        scroll_select(draft,draft.xiaohongshu_hour_options,selected.hour,"小红书小时")
    except RuntimeError as error:
        diagnostic={**getattr(draft,"xiaohongshu_hour_snapshot",{}),
                    "target":str(selected),"error":str(error)}
        path=Path(__file__).with_name("xiaohongshu_time_diagnostic.json")
        try:
            path.write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding="utf-8")
        except OSError:
            raise error
        raise RuntimeError(f"{error} 时间控件诊断已保存至{path.name}。") from error

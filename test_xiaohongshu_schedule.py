"""重放小红书小时标题延迟、滚动中消失和分钟列混淆，不操作网页。"""
import json
import time
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from bilibili_auto import CHINA_TIME
from xiaohongshu_auto import XiaohongshuDraft
from xiaohongshu_schedule import choose_hour


def control(name,x,y):
    return NS(Name=name,ControlTypeName="TextControl",
        BoundingRectangle=NS(left=x,top=y,right=x+24,bottom=y+20))


class XiaohongshuScheduleTests(unittest.TestCase):
    selected=datetime(2026,10,12,6,tzinfo=CHINA_TIME)

    def draft(self):
        d=object.__new__(XiaohongshuDraft)
        d.check=Mock();d.visible=lambda c:True;d.now=time.monotonic
        d.click=Mock();d.scroll_at=Mock()
        return d

    def test_missing_hour_heading_returns_unready_without_guessing_numeric_column(self):
        d=self.draft();d.controls=lambda:[control("06",290,530),control("分",360,500)]
        self.assertEqual(d.xiaohongshu_hour_options(),[])
        d.click.assert_not_called();d.scroll_at.assert_not_called()

    def test_real_failure_snapshot_identifies_hour_column_without_heading(self):
        from xiaohongshu_schedule import hour_options
        d=self.draft()
        d.controls=lambda:([control(str(v),2011,782+(v-12)*48) for v in range(12,20)]
            +[control("分",2109,785)]
            +[control(str(v),2098,785+(v-40)*48) for v in range(40,48)]
            +[control(str(v),1610+(v%7)*50,968) for v in range(12,24)])
        self.assertEqual([c.Name for c in hour_options(d)],list(map(str,range(12,20))))

    def test_hour_heading_delay_waits_without_reopening_picker(self):
        d=self.draft();label=control("时",300,500);hour=control("06",290,530)
        d.controls=Mock(side_effect=[[control("06",290,530)],[label,hour]])
        with patch("schedule_controls.time.sleep"):
            choose_hour(d,self.selected)
        d.click.assert_called_once_with(hour)
        d.scroll_at.assert_not_called()

    def test_top_hour_and_shifted_bottom_edge_remain_identifiable(self):
        d=self.draft()
        hours=[control(str(v),2011,881+(v-10)*48) for v in range(10,17)]
        d.controls=lambda:hours+[control("17",2011,1240),control("分",2109,910),control("04",2087,910)]
        self.assertEqual(d.xiaohongshu_hour_options(),hours)
        with patch("schedule_controls.time.sleep"):
            choose_hour(d,self.selected.replace(hour=10))
        d.click.assert_called_once_with(hours[0])
        d.scroll_at.assert_not_called()

    def test_heading_present_but_hour_nodes_loading_also_waits(self):
        d=self.draft();label=control("时",300,500);hour=control("06",290,530)
        d.controls=Mock(side_effect=[[label],[label,hour]])
        with patch("schedule_controls.time.sleep"):
            choose_hour(d,self.selected)
        d.click.assert_called_once_with(hour)
        d.scroll_at.assert_not_called()

    def test_same_number_in_minute_column_is_not_selected(self):
        d=self.draft();label=control("时",300,500)
        hour=control("12",290,530);minute=control("06",360,530)
        d.controls=lambda:[label,hour,control("分",370,500),minute]
        self.assertEqual(d.xiaohongshu_hour_options(),[hour])

    def test_heading_disappearing_after_scroll_stops_and_saves_last_read(self):
        d=self.draft();label=control("时",300,500)
        d.controls=Mock(side_effect=[[label,control("12",290,530),control("13",290,555)],
                                    [control("分",370,500),control("06",360,530)]])
        with TemporaryDirectory() as folder,patch("xiaohongshu_schedule.Path",return_value=Path(folder)/"module.py"),patch("schedule_controls.time.sleep"):
            with self.assertRaisesRegex(RuntimeError,"已关闭.*诊断已保存"):
                choose_hour(d,self.selected)
            diagnostic=json.loads((Path(folder)/"xiaohongshu_time_diagnostic.json").read_text(encoding="utf-8"))
            self.assertEqual(diagnostic["target"],str(self.selected))
            self.assertNotIn("时",[c["name"] for c in diagnostic["candidates"]])
        d.click.assert_not_called()
        self.assertEqual(d.scroll_at.call_count,1)

    def test_heading_never_appears_does_not_scroll_page_or_click(self):
        d=self.draft();d.now=Mock(side_effect=[0,6]);d.controls=lambda:[]
        with TemporaryDirectory() as folder,patch("xiaohongshu_schedule.Path",return_value=Path(folder)/"module.py"):
            with self.assertRaisesRegex(RuntimeError,"列表未出现.*诊断已保存"):
                choose_hour(d,self.selected)
        d.click.assert_not_called();d.scroll_at.assert_not_called()

    def test_moving_hour_panel_refreshes_scroll_anchor(self):
        d=self.draft();last=control("06",490,730)
        d.controls=Mock(side_effect=[
            [control("时",300,500),control("12",290,530),control("13",290,555)],
            [control("时",500,700),control("09",490,730),control("10",490,755)],
            [control("时",500,700),last]])
        with patch("schedule_controls.time.sleep"):
            choose_hour(d,self.selected)
        self.assertEqual([c.args[2][0] for c in d.scroll_at.call_args_list],[302,502])
        d.click.assert_called_once_with(last)


if __name__=="__main__":
    unittest.main()

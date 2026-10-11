"""离线检查三端续跑及发布结果不确定时的保护，不操作网页。"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from unittest.mock import patch
from types import SimpleNamespace
from bilibili_auto import BilibiliDraft, CHINA_TIME
from multi_publish import SubmissionTracking
from multi_publish import MultiQueue, PLATFORMS, recover_item, pending_platforms, save_state, mark_manual_completed


class QueueTests(unittest.TestCase):
    def test_not_publishing_is_saved_and_skipped_only_on_selected_platform(self):
        item=self.item(); q=self.queue(item,{})
        q.set_platform_state("work","bilibili","不发布")
        self.assertEqual(pending_platforms(recover_item(item)),["douyin","xiaohongshu"])
        q.save_queue.assert_called_once()
        q.set_platform_state("work","bilibili","待发布")
        self.assertIn("bilibili",pending_platforms(item))

    def test_completed_or_unverified_submission_cannot_be_reset_from_selector(self):
        for state in ("已完成","待核对","发布中"):
            item=self.item();item["states"]["bilibili"]=state
            q=self.queue(item,{})
            q.set_platform_state("work","bilibili","不发布")
            self.assertEqual(item["states"]["bilibili"],state)
            q.save_queue.assert_not_called()
    def test_manual_completion_preserves_failure_and_skips_retry(self):
        item=self.item()
        item.update(date="2026-10-12",hour="01",scheduled=True)
        item["states"]["xiaohongshu"]="失败"
        item["details"]["xiaohongshu"]={"submitted":False,"error":"候选未确认"}
        mark_manual_completed(item,"xiaohongshu","2026-10-11T12:00:00+08:00")
        self.assertNotIn("xiaohongshu",pending_platforms(recover_item(item)))
        self.assertEqual(item["details"]["xiaohongshu"]["previous_attempt"]["error"],"候选未确认")
        self.assertTrue(item["details"]["xiaohongshu"]["submitted"])
        self.assertIsNone(item["details"]["xiaohongshu"]["publish_at"])
        self.assertFalse(item["details"]["xiaohongshu"]["publish_time_verified"])
        self.assertEqual(item["details"]["xiaohongshu"]["requested_time"],"2026-10-12 01:00")
        self.assertEqual(item["states"]["douyin"],"待发布")

    def item(self):
        return {"folder":Path("work"),"scheduled":False,"states":{p:"待发布" for p in PLATFORMS},"details":{}}

    def queue(self,item,adapters):
        q=MultiQueue.__new__(MultiQueue)
        q.items={"work":item}; q.adapters=adapters
        q.running=q.closed=False
        q.timezone=CHINA_TIME
        for name in ("root","tree","notice","start_button"):
            setattr(q,name,Mock())
        q.save_queue=Mock()
        return q

    def test_interrupted_mouse_move_does_not_record_submission(self):
        cls=type("Tracked",(SubmissionTracking,BilibiliDraft),{})
        draft=object.__new__(cls)
        draft.check=Mock(); draft.visible=lambda c:True
        draft.move_pointer=Mock(side_effect=RuntimeError("窗口切换"))
        draft.on_submit=Mock()
        control=SimpleNamespace(Name="发布",ControlTypeName="ButtonControl",IsEnabled=True,
            BoundingRectangle=SimpleNamespace(left=10,top=10,right=30,bottom=30))
        with patch("bilibili_auto.mouse_event") as mouse:
            with self.assertRaisesRegex(RuntimeError,"窗口切换"):
                draft.submit(control)
            mouse.assert_not_called()
        draft.on_submit.assert_not_called()
        self.assertIsNone(draft.before_click_press)

    def test_submission_recorded_after_move_immediately_before_press(self):
        cls=type("Tracked",(SubmissionTracking,BilibiliDraft),{})
        draft=object.__new__(cls); events=[]
        draft.check=Mock(); draft.visible=lambda c:True
        draft.move_pointer=lambda target:events.append("move")
        draft.on_submit=lambda:events.append("submitted")
        draft.uia=SimpleNamespace(GetCursorPos=lambda:(20,20))
        control=SimpleNamespace(Name="发布",ControlTypeName="ButtonControl",IsEnabled=True,
            BoundingRectangle=SimpleNamespace(left=10,top=10,right=30,bottom=30))
        with patch("bilibili_auto.mouse_event",side_effect=lambda flag:events.append(flag)),patch("bilibili_auto.time.sleep"):
            draft.submit(control)
        self.assertEqual(events,["move","submitted",0x0002,0x0004])

    def test_disabled_submission_button_is_not_marked_or_pressed(self):
        cls=type("Tracked",(SubmissionTracking,BilibiliDraft),{})
        draft=object.__new__(cls)
        draft.check=Mock(); draft.visible=lambda c:True; draft.move_pointer=Mock(); draft.on_submit=Mock()
        control=SimpleNamespace(Name="发布",ControlTypeName="ButtonControl",IsEnabled=False,
            BoundingRectangle=SimpleNamespace(left=10,top=10,right=30,bottom=30))
        with patch("bilibili_auto.mouse_event") as mouse:
            with self.assertRaisesRegex(RuntimeError,"尚不可用"):
                draft.submit(control)
            mouse.assert_not_called()
        draft.on_submit.assert_not_called()

    def test_moved_button_repositions_before_single_press(self):
        cls=type("Tracked",(SubmissionTracking,BilibiliDraft),{})
        draft=object.__new__(cls)
        draft.check=Mock(); draft.visible=lambda c:True; draft.move_pointer=Mock(); draft.on_submit=Mock()
        draft.uia=SimpleNamespace(GetCursorPos=Mock(side_effect=[(0,0),(20,20)]))
        control=SimpleNamespace(Name="发布",ControlTypeName="ButtonControl",IsEnabled=True,
            BoundingRectangle=SimpleNamespace(left=10,top=10,right=30,bottom=30))
        with patch("bilibili_auto.mouse_event") as mouse,patch("bilibili_auto.time.sleep"):
            draft.submit(control)
        self.assertEqual(draft.move_pointer.call_count,2)
        draft.on_submit.assert_called_once()
        self.assertEqual([c.args[0] for c in mouse.call_args_list],[0x0002,0x0004])

    def test_persistent_cursor_mismatch_stops_without_press(self):
        cls=type("Tracked",(SubmissionTracking,BilibiliDraft),{})
        draft=object.__new__(cls)
        draft.check=Mock(); draft.visible=lambda c:True; draft.move_pointer=Mock(); draft.on_submit=Mock()
        draft.uia=SimpleNamespace(GetCursorPos=lambda:(0,0))
        control=SimpleNamespace(Name="发布",ControlTypeName="ButtonControl",IsEnabled=True,
            BoundingRectangle=SimpleNamespace(left=10,top=10,right=30,bottom=30))
        with patch("bilibili_auto.mouse_event") as mouse:
            with self.assertRaisesRegex(RuntimeError,"鼠标=\\(0, 0\\)"):
                draft.submit(control)
            mouse.assert_not_called()
        self.assertEqual(draft.move_pointer.call_count,3)
        draft.on_submit.assert_not_called()

    def test_submit_ready_failure_resumes_settings_without_reupload(self):
        item=self.item(); item["states"]["douyin"]="失败"
        item["details"]["douyin"]={"submitted":False,"stage":"submit_ready"}
        drafts={p:Mock() for p in PLATFORMS}
        self.queue(item,self.adapters(drafts)).start()
        self.assertEqual(drafts["douyin"].resume_stage,"settings")

    def test_schedule_label_click_is_not_a_submission(self):
        cls=type("Tracked",(SubmissionTracking,BilibiliDraft),{})
        draft=object.__new__(cls);draft.check=Mock();draft.visible=lambda c:True;draft.click_at=Mock();draft.on_submit=Mock()
        control=SimpleNamespace(Name="定时发布",ControlTypeName="ButtonControl",
            BoundingRectangle=SimpleNamespace(left=10,top=10,right=30,bottom=30))
        draft.click(control)
        draft.on_submit.assert_not_called()
        draft.click_at.assert_called_once()

    def test_text_control_final_submission_is_tracked(self):
        cls=type("Tracked",(SubmissionTracking,BilibiliDraft),{})
        draft=object.__new__(cls);draft.check=Mock();draft.visible=lambda c:True;draft.move_pointer=Mock();draft.on_submit=Mock()
        draft.uia=SimpleNamespace(GetCursorPos=lambda:(20,20))
        control=SimpleNamespace(Name="立即投稿",ControlTypeName="TextControl",IsEnabled=True,
            BoundingRectangle=SimpleNamespace(left=10,top=10,right=30,bottom=30))
        with patch("bilibili_auto.mouse_event"),patch("bilibili_auto.time.sleep"):
            draft.submit(control)
        draft.on_submit.assert_called_once()
        self.assertFalse(draft.submission_requested)

    def test_corrupt_queue_is_not_overwritten_during_recovery_or_save(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/"state.json";path.write_text("broken",encoding="utf-8")
            q=MultiQueue.__new__(MultiQueue);q.queue_file=path;q.items={};q.directory="";q.notice=Mock()
            q.restore_queue();q.save_queue()
            self.assertTrue(q.state_read_failed)
            self.assertEqual(path.read_text(encoding="utf-8"),"broken")

    def adapters(self,drafts):
        return {p:(lambda p=p:drafts[p],lambda f:("v","title","body",[]),lambda f:"cover",lambda f:None,lambda d,h:None) for p in PLATFORMS}

    def test_completed_kept_and_skipped(self):
        item=self.item(); item["states"]["bilibili"]="已完成"
        drafts={p:Mock() for p in PLATFORMS}
        q=self.queue(item,self.adapters(drafts)); q.start()
        drafts["bilibili"].run.assert_not_called()
        self.assertEqual(len(q.items),1)
        self.assertTrue(all(s=="已完成" for s in item["states"].values()))
        q.start()
        self.assertEqual(drafts["douyin"].run.call_count,1)

    def test_failure_resume_skips_success(self):
        item=self.item(); drafts={p:Mock() for p in PLATFORMS}
        drafts["xiaohongshu"].run.side_effect=RuntimeError("上传失败")
        q=self.queue(item,self.adapters(drafts)); q.start()
        self.assertEqual(item["states"]["douyin"],"已完成")
        self.assertEqual(item["states"]["xiaohongshu"],"失败")
        drafts["bilibili"].run.assert_not_called()
        drafts["xiaohongshu"].run.side_effect=None
        q.start()
        self.assertEqual(drafts["douyin"].run.call_count,1)
        self.assertTrue(all(s=="已完成" for s in item["states"].values()))

    def test_one_platform_runs_without_touching_other_states_or_history(self):
        item=self.item()
        item["states"]["douyin"]="失败"
        item["details"]["douyin"]={"submitted":False,"error":"日历失败"}
        item["states"]["xiaohongshu"]="待核对"
        item["details"]["xiaohongshu"]={"submitted":True,"error":"待确认"}
        import copy
        previous=copy.deepcopy(item)
        drafts={p:Mock() for p in PLATFORMS}
        self.queue(item,self.adapters(drafts)).start("bilibili")
        drafts["bilibili"].run.assert_called_once()
        for p in ("douyin","xiaohongshu"):
            drafts[p].run.assert_not_called()
            self.assertEqual(item["states"][p],previous["states"][p])
            self.assertEqual(item["details"][p],previous["details"][p])

    def test_single_platform_only_validates_selected_adapter(self):
        item=self.item(); drafts={p:Mock() for p in PLATFORMS}
        adapters=self.adapters(drafts)
        for p in ("douyin","xiaohongshu"):
            adapters[p]=(Mock(side_effect=AssertionError("不应初始化其他端")),)*5
        self.queue(item,adapters).start("bilibili")
        self.assertEqual(item["states"]["bilibili"],"已完成")

    def test_selected_platform_uncertainty_still_blocks_its_own_retry(self):
        item=self.item();item["states"]["douyin"]="待核对"
        drafts={p:Mock() for p in PLATFORMS}
        self.queue(item,self.adapters(drafts)).start("douyin")
        drafts["douyin"].run.assert_not_called()

    def test_single_platform_failure_preserves_other_pending_tasks(self):
        item=self.item();drafts={p:Mock() for p in PLATFORMS}
        drafts["douyin"].run.side_effect=RuntimeError("小时未就绪")
        q=self.queue(item,self.adapters(drafts));q.start("douyin")
        self.assertEqual(item["states"],dict(douyin="失败",xiaohongshu="待发布",bilibili="待发布"))
        q.start("bilibili")
        self.assertEqual(item["states"]["bilibili"],"已完成")
        self.assertEqual(drafts["douyin"].run.call_count,1)
        drafts["xiaohongshu"].run.assert_not_called()

    def test_adapter_initialization_failure_is_saved_in_its_own_state(self):
        item=self.item();drafts={p:Mock() for p in PLATFORMS}
        adapters=self.adapters(drafts)
        adapters["douyin"]=(Mock(side_effect=RuntimeError("UIA初始化失败")),)+adapters["douyin"][1:]
        q=self.queue(item,adapters);q.start("douyin")
        self.assertEqual(item["states"]["douyin"],"失败")
        self.assertIn("UIA初始化失败",item["details"]["douyin"]["traceback"])
        self.assertFalse(item["details"]["douyin"]["submitted"])
        self.assertEqual(item["states"]["bilibili"],"待发布")

    def test_calendar_failure_stage_resumes_douyin_settings(self):
        item=self.item();item["states"]["douyin"]="失败"
        item["details"]["douyin"]={"submitted":False,"stage":"schedule_date","error":"日历失败"}
        drafts={p:Mock() for p in PLATFORMS}
        self.queue(item,self.adapters(drafts)).start("douyin")
        self.assertEqual(drafts["douyin"].resume_stage,"settings")
        self.assertEqual(item["details"]["douyin"]["attempts"][0]["stage"],"schedule_date")

    def test_all_platforms_finish_one_platform_before_switching(self):
        item=self.item();drafts={p:Mock() for p in PLATFORMS}
        q=self.queue(item,self.adapters(drafts));second=self.item();second["folder"]=Path("work2")
        q.items["work2"]=second
        order=[]
        for p,draft in drafts.items():
            draft.run.side_effect=lambda *args,p=p:order.append((p,str(args[0])))
        q.start()
        self.assertEqual([p for p,_ in order],["douyin","douyin","xiaohongshu","xiaohongshu","bilibili","bilibili"])

    def test_publish_order(self):
        item=self.item(); drafts={p:Mock() for p in PLATFORMS}
        order=[]
        for p,draft in drafts.items():
            draft.run.side_effect=lambda *args,p=p:order.append(p)
        self.queue(item,self.adapters(drafts)).start()
        self.assertEqual(order,["douyin","xiaohongshu","bilibili"])

    def test_legacy_saving_error_resumes_settings(self):
        item=self.item()
        item["states"]["douyin"]="失败"
        item["details"]["douyin"]={"submitted":False,
            "error":"没有找到“不允许”，页面或浏览器可访问性可能发生变化。"}
        drafts={p:Mock() for p in PLATFORMS}
        self.queue(item,self.adapters(drafts)).start()
        self.assertEqual(drafts["douyin"].resume_stage,"settings")
        self.assertEqual(item["details"]["douyin"]["stage"],"settings")

    def test_submission_uncertain_blocks_retry(self):
        item=self.item(); drafts={p:Mock() for p in PLATFORMS}
        def uncertain(*args):
            drafts["bilibili"].on_submit()
            raise RuntimeError("未确认成功")
        drafts["bilibili"].run.side_effect=uncertain
        q=self.queue(item,self.adapters(drafts)); q.start(); q.start()
        self.assertEqual(item["states"]["bilibili"],"待核对")
        self.assertEqual(drafts["bilibili"].run.call_count,1)

    def test_empty_exception_records_type_and_location(self):
        item=self.item(); item["states"]["douyin"]="已完成"
        drafts={p:Mock() for p in PLATFORMS}
        drafts["xiaohongshu"].run.side_effect=StopIteration()
        self.queue(item,self.adapters(drafts)).start()
        detail=item["details"]["xiaohongshu"]
        self.assertIn("StopIteration",detail["error"])
        self.assertIn("StopIteration",detail["traceback"])
        self.assertFalse(detail["submitted"])
        drafts["douyin"].run.assert_not_called()

    def test_restart_and_disk_roundtrip(self):
        item=self.item(); item["states"]["bilibili"]="已完成"
        item["states"]["douyin"]="发布中"
        item["details"]["douyin"]={"submitted":True}
        item["states"]["xiaohongshu"]="发布中"
        recover_item(item)
        self.assertEqual(item["states"],dict(bilibili="已完成",douyin="待核对",xiaohongshu="失败"))
        self.assertEqual(pending_platforms(item),["xiaohongshu"])
        with TemporaryDirectory() as folder:
            import json
            path=Path(folder)/"state.json"
            save_state(path,{"items":[dict(item,folder=str(item["folder"]))]})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["items"][0]["states"],item["states"])


if __name__=="__main__":
    unittest.main()

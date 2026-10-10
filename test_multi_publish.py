"""离线检查三端续跑及发布结果不确定时的保护，不操作网页。"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from multi_publish import MultiQueue, PLATFORMS, recover_item, pending_platforms, save_state


class QueueTests(unittest.TestCase):
    def item(self):
        return {"folder":Path("work"),"scheduled":False,"states":{p:"待发布" for p in PLATFORMS},"details":{}}

    def queue(self,item,adapters):
        q=MultiQueue.__new__(MultiQueue)
        q.items={"work":item}; q.adapters=adapters
        q.running=q.closed=False
        for name in ("root","tree","notice","start_button"):
            setattr(q,name,Mock())
        q.save_queue=Mock()
        return q

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

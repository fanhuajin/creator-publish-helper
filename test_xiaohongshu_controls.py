import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path
from xiaohongshu_auto import XiaohongshuDraft


class ControlsTests(unittest.TestCase):
    def test_correct_title_skips_f6(self):
        draft=object.__new__(XiaohongshuDraft)
        control=SimpleNamespace(GetValuePattern=lambda:SimpleNamespace(Value="早上好～ "))
        draft.keyboard_field=Mock(); draft.click=Mock()
        draft.keyboard_fill(control,"title","早上好～")
        draft.keyboard_field.assert_not_called(); draft.click.assert_not_called()

    def test_title_waits_for_input_focus_before_f6(self):
        draft=object.__new__(XiaohongshuDraft)
        control=SimpleNamespace(GetValuePattern=lambda:SimpleNamespace(Value=""))
        hint="填写标题会有更多赞哦"
        draft.form_find=Mock(return_value=control); draft.click=Mock(); draft.check=Mock()
        draft.now=Mock(side_effect=range(10))
        focused=SimpleNamespace(Name=hint,ControlTypeName="EditControl",AutomationId="")
        draft.uia=SimpleNamespace(GetFocusedControl=Mock(side_effect=[None,focused]))
        draft.keyboard_field=Mock(); draft.verify_edit_value=Mock()
        with patch("xiaohongshu_auto.time.sleep"):
            draft.keyboard_fill(control,"title","早上好～")
        draft.keyboard_field.assert_called_once_with("title")

    def test_description_wrong_focus_prevents_clear(self):
        draft=object.__new__(XiaohongshuDraft)
        draft.window=SimpleNamespace(NativeWindowHandle=123)
        draft.click=Mock(); draft.keys=Mock()
        with patch("focus_detection.focused_field",return_value="title"):
            with self.assertRaisesRegex(RuntimeError,"未清空"):
                draft.focus_description(object())
        draft.keys.assert_not_called()

    def test_cover_clicks_as_soon_as_upload_and_button_are_ready(self):
        draft=object.__new__(XiaohongshuDraft)
        button=SimpleNamespace(IsEnabled=True)
        draft.now=Mock(side_effect=[0,0.1,0.2,0.3])
        draft.check=Mock(); draft.click=Mock()
        draft.locate=Mock(side_effect=[button,object(),None])
        with patch("xiaohongshu_auto.time.sleep"):
            draft.finish_cover()
        draft.click.assert_called_once_with(button)

    def test_cover_does_not_click_disabled_button(self):
        draft=object.__new__(XiaohongshuDraft)
        disabled=SimpleNamespace(IsEnabled=False); ready=SimpleNamespace(IsEnabled=True)
        draft.now=Mock(side_effect=[0,0.1,0.2,0.3,0.4])
        draft.check=Mock(); draft.click=Mock()
        draft.locate=Mock(side_effect=[disabled,object(),ready,object(),None])
        with patch("xiaohongshu_auto.time.sleep"):
            draft.finish_cover()
        draft.click.assert_called_once_with(ready)

    def test_missing_control_has_actionable_error(self):
        draft=object.__new__(XiaohongshuDraft)
        with self.assertRaisesRegex(RuntimeError,"定时发布开关"):
            draft.require_control([],lambda c:True,"定时发布开关")

    def test_upload_entry_accepts_text_control(self):
        draft=object.__new__(XiaohongshuDraft)
        draft.select_browser=Mock(); draft.locate=Mock(return_value=None)
        draft.controls=lambda:[]; draft.next_upload=Mock()
        entry=SimpleNamespace(Name="上传视频",ControlTypeName="TextControl")
        draft.wait_name=Mock(side_effect=[entry,RuntimeError("停止在上传后")])
        draft.click=Mock(); draft.choose_file=Mock()
        with self.assertRaisesRegex(RuntimeError,"停止在上传后"):
            draft.run(Path("work/video.mp4"),"标题","正文",[],None,None,None)
        draft.click.assert_called_once_with(entry)
        draft.choose_file.assert_called_once_with(Path("work/video.mp4"))


if __name__ == "__main__":
    unittest.main()

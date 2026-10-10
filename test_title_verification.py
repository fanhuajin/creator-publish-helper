import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from bilibili_auto import BilibiliDraft


def title_control(value):
    return SimpleNamespace(Name="标题输入提示",GetValuePattern=lambda:SimpleNamespace(Value=value))


class TitleTests(unittest.TestCase):
    def draft(self):
        draft=object.__new__(BilibiliDraft)
        draft.check=Mock(); draft.click=Mock(); draft.keyboard_field=Mock()
        draft.clipboard=Mock(); draft.keys=Mock()
        draft.now=Mock(side_effect=range(30))
        return draft

    def test_correct_title_does_not_rewrite(self):
        draft=self.draft()
        draft.keyboard_fill(title_control("早上好～"),"title","早上好～")
        draft.click.assert_not_called(); draft.keyboard_field.assert_not_called()

    def test_title_verification_reads_native_value_without_clipboard(self):
        draft=self.draft(); draft.locate=Mock(return_value=title_control("标题"))
        draft.verify_edit_value("标题输入提示","标题")
        draft.clipboard.paste.assert_not_called(); draft.keys.assert_not_called()

    def test_wrong_title_cannot_pass_successful_f6(self):
        draft=self.draft(); draft.locate=Mock(return_value=title_control("别的标题"))
        with patch("bilibili_auto.time.sleep"),self.assertRaisesRegex(RuntimeError,"别的标题"):
            draft.verify_edit_value("标题输入提示","目标标题")

    def test_page_focus_cannot_trigger_title_f6(self):
        draft=self.draft()
        draft.uia=SimpleNamespace(GetFocusedControl=lambda:SimpleNamespace(ControlTypeName="DocumentControl"))
        with patch("bilibili_auto.time.sleep"),self.assertRaisesRegex(RuntimeError,"输入焦点"):
            draft.keyboard_fill(title_control(""),"title","标题")
        draft.keyboard_field.assert_not_called()

    def test_delayed_clipboard_copy_can_complete_without_retyping(self):
        draft=self.draft(); draft.now=Mock(side_effect=[0,0.1,0.2])
        draft.clipboard.paste.side_effect=["","正文"]
        with patch("bilibili_auto.time.sleep"):
            draft.verify_text("正文")
        self.assertEqual([call.args[0] for call in draft.keys.call_args_list],
                         ["{Ctrl}a","{Ctrl}c","{End}"])


if __name__=="__main__":
    unittest.main()

import json
import time
from pathlib import Path
from douyin_auto import DouyinDraft, prepare_douyin

state_file = Path(__file__).with_name("douyin_queue_state.json")
state = json.loads(state_file.read_text(encoding="utf-8"))
if not state["items"]:
    raise RuntimeError("队列为空。")
item = state["items"][0]
folder = Path(item["folder"])
_, title, description, tags = prepare_douyin(folder)
draft = DouyinDraft()
draft.select_browser()
hint = "填写作品标题，为作品获得更多流量"
controls = draft.controls()
entry = next((c for c in controls if c.Name == hint and c.ControlTypeName == "EditControl"), None)
if entry is None or entry.GetValuePattern().Value != title:
    raise RuntimeError("当前稿件标题与队列首个作品不一致，未发布。")
clock = draft.find("日期和时间", editable=True).GetValuePattern().Value
if clock[:10] != item["date"] or clock[11:13] != item["hour"]:
    raise RuntimeError("当前日期和小时与队列不一致，未发布。")
saving = [c for c in draft.controls() if c.Name == "不允许" and c.ControlTypeName == "CheckBoxControl"]
if len(saving) != 1 or int(saving[0].GetTogglePattern().ToggleState) != 1:
    raise RuntimeError("保存权限未确认不允许，未发布。")
if "内容由AI生成" not in draft.control_names():
    raise RuntimeError("AI声明未确认，未发布。")
draft.wait_uploaded()
draft.click(draft.find("发布"))
deadline = draft.now() + 60
while draft.now() < deadline:
    controls = draft.controls()
    names = [c.Name for c in controls]
    form_present = any(c.Name == hint and c.ControlTypeName == "EditControl" for c in controls)
    if "发布成功" in names or (not form_present and "内容管理" in names and any(title in name for name in names)):
        break
    time.sleep(0.5)
else:
    raise RuntimeError("已点击发布但未确认成功；保留队列，请检查作品管理。")
completed = {"folder": str(folder), "publish_at": clock}
state.setdefault("completed", []).append(completed)
state["items"] = [row for row in state["items"] if row["folder"] != item["folder"]]
temporary = state_file.with_suffix(".tmp")
temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(state_file)
Path(__file__).with_name("douyin_auto_status.json").write_text(json.dumps({"ok":True,"completed":state["completed"],"pending":[row["folder"] for row in state["items"]]},ensure_ascii=False),encoding="utf-8")
print(f"发布成功，已移除：{folder.name}；时间：{clock}",flush=True)
draft.next_upload()

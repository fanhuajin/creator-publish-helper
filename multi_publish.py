"""三端发布队列：保留状态，继续未完成平台，由用户删除记录。"""
import json
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from publish_queue import PublishQueue, WorkRows

PLATFORMS = ("douyin", "xiaohongshu", "bilibili")
LABELS = {"bilibili": "B站", "douyin": "抖音", "xiaohongshu": "小红书"}
STATE_FILE = Path(__file__).with_name("multi_publish_state.json")


def save_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def recover_item(item):
    item.setdefault("states", {p: "待发布" for p in PLATFORMS})
    item.setdefault("details", {})
    for p in PLATFORMS:
        if item["states"].get(p) == "发布中":
            item["states"][p] = "待核对" if item["details"].get(p, {}).get("submitted") else "失败"
    return item


def pending_platforms(item):
    return [p for p in PLATFORMS if item["states"][p] in ("待发布", "失败")]


class ThreeRows(WorkRows):
    def __init__(self, parent, change, timezone):
        super().__init__(parent, change, timezone)
        header = self.winfo_children()[0]
        header.winfo_children()[-1].destroy()
        for p in PLATFORMS:
            ttk.Label(header, text=LABELS[p], width=12).pack(side="left")

    def insert(self, parent, position, iid, text, values):
        super().insert(parent, position, iid, text, values)
        row = self.rows[iid]
        row["frame"].winfo_children()[-1].destroy()
        row["platforms"] = {}
        for p in PLATFORMS:
            var = tk.StringVar(value="待发布")
            row["platforms"][p] = var
            ttk.Label(row["frame"], textvariable=var, width=12).pack(side="left", padx=4)

    def update_states(self, key, states):
        for p, var in self.rows[key]["platforms"].items():
            var.set(states[p])


class MultiQueue(PublishQueue):
    def __init__(self, root, adapters, timezone):
        # 延用已有文件夹选择、逐行时间修改和 Esc 暂停流程。
        self.root, self.adapters, self.timezone = root, adapters, timezone
        self.items, self.completed = {}, []
        self.queue_file = STATE_FILE
        self.loading = self.running = self.paused = self.closed = False
        self.directory = "E:/AI_Exports/H3-MotionStudio/往期成品/20261008/dance"
        tomorrow = datetime.now(timezone)+timedelta(days=1)
        self.date = tk.StringVar(value=tomorrow.strftime("%Y-%m-%d"))
        self.hour = tk.StringVar(value="01")
        self.scheduled = tk.BooleanVar(value=True)
        self.notice = tk.StringVar(value="选择作品文件夹，设置共用日期和小时。三端完成后保留记录，由你主动删除。")
        root.title("三端批量发布")
        icon=Path(__file__).with_name("assets")/"creator-publish.ico"
        if icon.exists():
            root.iconbitmap(str(icon))
        root.geometry("1250x650")
        panel = ttk.Frame(root, padding=16)
        panel.pack(fill="both", expand=True)
        toolbar = ttk.Frame(panel)
        toolbar.pack(fill="x")
        ttk.Button(toolbar,text="批量选择作品文件夹",command=self.choose_many).pack(side="left")
        ttk.Button(toolbar,text="添加一个作品文件夹",command=self.choose_one).pack(side="left",padx=8)
        ttk.Button(toolbar,text="全选",command=lambda:self.tree.select_all()).pack(side="left",padx=4)
        ttk.Button(toolbar,text="取消全选",command=lambda:self.tree.select_all(False)).pack(side="left",padx=4)
        ttk.Button(toolbar,text="删除选中记录",command=self.remove).pack(side="left")
        ttk.Button(toolbar,text="核对待确认结果",command=self.review).pack(side="left",padx=8)
        self.tree=ThreeRows(panel,self.set_item_time,timezone)
        self.tree.pack(fill="both",expand=True,pady=14)
        ttk.Label(panel,textvariable=self.notice,wraplength=1180).pack(anchor="w",pady=12)
        ttk.Label(panel,text="Esc 暂停；继续只处理未完成的平台。删除记录不会删除素材文件夹。").pack(anchor="w")
        self.start_button=ttk.Button(panel,text="开始 / 继续三端发布",command=self.start)
        self.start_button.pack(anchor="e",pady=10)
        root.protocol("WM_DELETE_WINDOW",self.close)
        root.bind("<Escape>",lambda event:self.request_pause())
        self.restore_queue()

    def add(self, folder):
        folder=Path(folder).resolve()
        key=str(folder)
        if key in self.items:
            return
        self.validate(folder)
        item={"folder":folder,"date":self.date.get(),"hour":self.hour.get(),"scheduled":self.scheduled.get(),
              "states":{p:"待发布" for p in PLATFORMS},"details":{}}
        self.items[key]=item
        self.tree.insert("","end",iid=key,text=folder.name,values=self.values(item))
        self.tree.update_states(key,item["states"])
        self.save_queue()

    def validate(self, folder):
        for p, adapter in self.adapters.items():
            adapter[1](folder)
            adapter[2](folder)
            adapter[3](folder)

    def save_queue(self):
        if not self.loading:
            save_state(self.queue_file,{"directory":self.directory,
                       "items":[dict(i,folder=str(i["folder"])) for i in self.items.values()]})

    def restore_queue(self):
        if not self.queue_file.exists():
            return
        self.loading=True
        try:
            state=json.loads(self.queue_file.read_text(encoding="utf-8"))
            self.directory=state.get("directory",self.directory)
            for saved in state.get("items",[]):
                item=recover_item(saved)
                item["folder"]=Path(item["folder"])
                key=str(item["folder"])
                self.items[key]=item
                self.tree.insert("","end",iid=key,text=item["folder"].name,values=self.values(item))
                self.tree.update_states(key,item["states"])
            self.notice.set(f"已恢复 {len(self.items)} 条记录；已完成平台会跳过。")
        except Exception as error:
            self.notice.set(f"读取列表失败：{error}")
        finally:
            self.loading=False
        self.save_queue()

    def review(self):
        if self.running:
            return
        for key in self.tree.selection():
            item=self.items[key]
            for p in PLATFORMS:
                if item["states"][p]!="待核对":
                    continue
                answer=messagebox.askyesnocancel("核对发布结果",
                    f"请在{LABELS[p]}核对《{item['folder'].name}》。\n已发布成功选“是”；确认未发布选“否”；未确认选“取消”。",parent=self.root)
                if answer is None:
                    continue
                item["states"][p]="已完成" if answer else "待发布"
                item["details"][p]={"manual_review":True,"submitted":bool(answer)}
                self.tree.update_states(key,item["states"])
                self.save_queue()

    def start(self):
        if self.running or not self.items:
            return
        if any("待核对" in i["states"].values() for i in self.items.values()):
            self.notice.set("请先勾选待核对作品，点击“核对待确认结果”，确认是否已发布。")
            return
        try:
            for item in self.items.values():
                for p in pending_platforms(item):
                    _,prepare,cover,category,select=self.adapters[p]
                    prepare(item["folder"]); cover(item["folder"]); category(item["folder"])
                    if item["scheduled"]:
                        select(item["date"],item["hour"])
        except Exception as error:
            messagebox.showerror("请检查作品与时间",str(error),parent=self.root)
            return
        self.running=True
        self.tree.set_enabled(False)
        self.start_button.configure(text="运行中",state="disabled")
        self.root.withdraw()
        try:
            for key,item in self.items.items():
                for p in pending_platforms(item):
                    cls,prepare,cover,category,select=self.adapters[p]
                    draft=cls()
                    previous = item["details"].get(p, {})
                    if p == "douyin":
                        draft.resume_stage = previous.get("stage")
                        if previous.get("error") in (
                            "未确认保存权限为不允许。",
                            "没有找到“不允许”，页面或浏览器可访问性可能发生变化。",
                        ) and not previous.get("submitted"):
                            draft.resume_stage = "settings"
                        draft.on_stage = lambda stage,i=item,platform=p:self.stage(i,platform,stage)
                    draft.on_tick=self.tick
                    draft.on_pause=self.pause
                    draft.on_submit=lambda i=item,platform=p:self.submitted(i,platform)
                    item["states"][p]="发布中"
                    item["details"][p]={"submitted":False}
                    if previous.get("stage"):
                        item["details"][p]["stage"] = previous["stage"]
                    elif p == "douyin" and draft.resume_stage:
                        item["details"][p]["stage"] = draft.resume_stage
                    self.tree.update_states(key,item["states"])
                    self.save_queue()
                    self.notice.set(f"正在发布 {item['folder'].name} → {LABELS[p]}")
                    try:
                        selected=select(item["date"],item["hour"]) if item["scheduled"] else None
                        draft.run(*prepare(item["folder"]),cover(item["folder"]),category(item["folder"]),selected)
                    except Exception as error:
                        item["states"][p]="待核对" if item["details"][p]["submitted"] else "失败"
                        error_text = str(error) or f"{type(error).__name__}：查找控件失败，详见错误位置"
                        item["details"][p]["error"]=error_text
                        item["details"][p]["traceback"]=traceback.format_exc()
                        self.tree.update_states(key,item["states"])
                        self.save_queue()
                        raise
                    item["states"][p]="已完成"
                    item["details"][p]["publish_at"]=str(getattr(draft,"actual_publish_at",selected) or "不定时")
                    self.tree.update_states(key,item["states"])
                    self.save_queue()
            self.notice.set("三端全部完成，记录已保留。你可勾选后主动删除。")
        except Exception as error:
            self.notice.set(f"流程已停止：{str(error) or type(error).__name__}。已完成平台已保存，继续时跳过。")
        finally:
            self.running=False
            self.tree.set_enabled(True)
            self.start_button.configure(text="开始 / 继续三端发布",state="normal",command=self.start)
            if not self.closed:
                self.root.deiconify(); self.root.lift()
            else:
                self.root.quit()

    def submitted(self,item,p):
        item["details"][p]["submitted"]=True
        self.save_queue()

    def stage(self,item,p,stage):
        item["details"][p]["stage"] = stage
        self.save_queue()


class SubmissionTracking:
    on_submit=None
    tab_hint=""

    def select_browser(self):
        candidates=[]
        for window in self.uia.GetRootControl().GetChildren():
            if not any(b in window.Name for b in ("Edge","Chrome","Firefox")):
                continue
            for tab,_ in self.uia.WalkControl(window,maxDepth=20):
                if tab.ControlTypeName=="TabItemControl" and self.tab_hint in tab.Name:
                    candidates.append((window,tab))
        if len(candidates)!=1:
            raise RuntimeError(f"请保留一个{self.tab_hint}标签页。")
        self.window,tab=candidates[0]
        self.window.SetFocus()
        time.sleep(0.4)
        r=tab.BoundingRectangle
        if r.width()<=0:
            raise RuntimeError("目标平台标签页不可见，请展开浏览器标签栏。")
        self.click_at(((r.left+r.right)//2,(r.top+r.bottom)//2))
        time.sleep(0.4)
        return super().select_browser()

    def click(self, control):
        if control and control.ControlTypeName=="ButtonControl" and control.Name in ("立即投稿","发布","定时发布"):
            self.check()
            if self.on_submit:
                self.on_submit()
        return super().click(control)


def main():
    import ctypes
    from bilibili_auto import BilibiliDraft,prepare_files,cover_from_folder,category_from_folder,select_hour,CHINA_TIME
    from douyin_auto import DouyinDraft,prepare_douyin,douyin_covers,select_douyin_hour
    from xiaohongshu_auto import XiaohongshuDraft,prepare_xiaohongshu,xiaohongshu_cover,select_xiaohongshu_hour
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    mutex=kernel.CreateMutexW(None,False,"Local\\CreatorPublishHelperMulti")
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error()==183:
        kernel.CloseHandle(mutex)
        return
    root=tk.Tk(); root.withdraw()
    try:
        adapters={
            "bilibili":(type("TrackedBili",(SubmissionTracking,BilibiliDraft),{"tab_hint":"创作中心"}),prepare_files,cover_from_folder,category_from_folder,select_hour),
            "douyin":(type("TrackedDouyin",(SubmissionTracking,DouyinDraft),{"tab_hint":"抖音创作者中心"}),prepare_douyin,douyin_covers,lambda f:None,select_douyin_hour),
            "xiaohongshu":(type("TrackedXhs",(SubmissionTracking,XiaohongshuDraft),{"tab_hint":"小红书创作服务平台"}),prepare_xiaohongshu,xiaohongshu_cover,lambda f:None,select_xiaohongshu_hour)}
        MultiQueue(root,adapters,CHINA_TIME).show()
    finally:
        root.destroy(); kernel.CloseHandle(mutex)


if __name__=="__main__":
    main()

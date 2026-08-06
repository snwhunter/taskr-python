"""Tk desktop UI for loading and viewing Tasks."""

from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date, timedelta
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from taskr.models.task import Status, Task, VISIBLE_COLUMNS
from taskr.storage.apps_script import AppsScriptTaskStore
from taskr.storage.config import AppConfig


def target_date(kind: str, today: date | None = None) -> date | None:
    today = today or date.today()
    if kind == "EOD": return today
    if kind == "EOW": return today + timedelta(days=6 - today.weekday())
    if kind == "EOM": return date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    return None


class TaskrApp(ttk.Frame):
    def __init__(self, master: tk.Tk, config: AppConfig, store: AppsScriptTaskStore) -> None:
        super().__init__(master, padding=10); self.pack(fill="both", expand=True)
        self.config, self.store, self.tasks = config, store, []
        master.title("taskr"); master.geometry("1180x650")
        tabs = ttk.Notebook(self); tabs.pack(fill="both", expand=True)
        self.load_tab, self.view_tab = ttk.Frame(tabs, padding=10), ttk.Frame(tabs, padding=10)
        tabs.add(self.load_tab, text="Load Tasks"); tabs.add(self.view_tab, text="View Tasks")
        self._build_load(); self._build_view(); self.refresh()

    def _build_load(self) -> None:
        self.inputs = {}
        for row, (label, values) in enumerate((("Category", self.config.categories), ("Reference", self.config.references), ("Assigned", self.config.assigned))):
            ttk.Label(self.load_tab, text=label).grid(row=row, column=0, sticky="w", pady=4)
            box = ttk.Combobox(self.load_tab, values=values); box.grid(row=row, column=1, sticky="ew"); self.inputs[label] = box
        for row, label in enumerate(("Task", "Details"), 3):
            ttk.Label(self.load_tab, text=label).grid(row=row, column=0, sticky="nw", pady=4)
            widget = tk.Text(self.load_tab, height=2 if label == "Task" else 5, width=70); widget.grid(row=row, column=1, sticky="ew"); self.inputs[label] = widget
        ttk.Label(self.load_tab, text="Target").grid(row=5, column=0, sticky="w")
        self.target = tk.StringVar()
        target_frame = ttk.Frame(self.load_tab); target_frame.grid(row=5, column=1, sticky="w")
        for name in ("EOD", "EOW", "EOM"):
            ttk.Button(target_frame, text=name, command=lambda n=name: self.target.set(target_date(n).isoformat())).pack(side="left")
        ttk.Button(target_frame, text="Future date…", command=self._pick_date).pack(side="left")
        ttk.Button(target_frame, text="No date", command=lambda: self.target.set("")).pack(side="left")
        ttk.Label(target_frame, textvariable=self.target, width=12).pack(side="left", padx=8)
        ttk.Button(self.load_tab, text="Create task", command=self.create).grid(row=6, column=1, sticky="e", pady=12)
        self.load_tab.columnconfigure(1, weight=1)

    def _build_view(self) -> None:
        filters = ttk.Frame(self.view_tab); filters.pack(fill="x")
        self.category_filter, self.reference_filter = tk.StringVar(), tk.StringVar()
        self.from_filter, self.to_filter = tk.StringVar(), tk.StringVar()
        for label, variable in (("Category", self.category_filter), ("Reference", self.reference_filter), ("From YYYY-MM-DD", self.from_filter), ("To YYYY-MM-DD", self.to_filter)):
            ttk.Label(filters, text=label).pack(side="left"); ttk.Entry(filters, textvariable=variable, width=14).pack(side="left", padx=(2, 8))
        ttk.Button(filters, text="Apply", command=self.render).pack(side="left")
        self.table = ttk.Treeview(self.view_tab, columns=VISIBLE_COLUMNS, show="headings", selectmode="browse")
        for name in VISIBLE_COLUMNS: self.table.heading(name, text=name); self.table.column(name, width=105)
        self.table.column("Task", width=220); self.table.pack(fill="both", expand=True, pady=8)
        self.table.bind("<Double-1>", self.edit_cell)
        buttons = ttk.Frame(self.view_tab); buttons.pack(fill="x")
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(buttons, text="Complete task", command=self.complete).pack(side="right")

    def _pick_date(self) -> None:
        value = simpledialog.askstring("Future date", "Date (YYYY-MM-DD):", parent=self)
        if value:
            try:
                chosen = date.fromisoformat(value)
                if chosen < date.today(): raise ValueError
                self.target.set(chosen.isoformat())
            except ValueError: messagebox.showerror("Invalid date", "Choose today or a future date in YYYY-MM-DD format.")

    def create(self) -> None:
        try:
            values = {key.lower(): widget.get().strip() for key, widget in self.inputs.items() if isinstance(widget, ttk.Combobox)}
            values["task"] = self.inputs["Task"].get("1.0", "end").strip(); values["details"] = self.inputs["Details"].get("1.0", "end").strip()
            values["target"] = date.fromisoformat(self.target.get()) if self.target.get() else None
            self.store.create(Task.new(user=self.config.user, **values))
            self.config.remember(values["category"], values["reference"], values["assigned"]); self.config.save()
            histories = {"Category": self.config.categories, "Reference": self.config.references, "Assigned": self.config.assigned}
            for key in histories: self.inputs[key]["values"] = histories[key]
            for key in ("Task", "Details"): self.inputs[key].delete("1.0", "end")
            self.refresh(); messagebox.showinfo("Created", "Task created.")
        except Exception as error: messagebox.showerror("Create failed", str(error))

    def refresh(self) -> None:
        try: self.tasks = self.store.list(); self.render()
        except Exception as error: messagebox.showerror("Load failed", str(error))

    def render(self) -> None:
        self.table.delete(*self.table.get_children())
        try:
            start = date.fromisoformat(self.from_filter.get()) if self.from_filter.get() else None
            end = date.fromisoformat(self.to_filter.get()) if self.to_filter.get() else None
        except ValueError: messagebox.showerror("Invalid filter", "Dates must use YYYY-MM-DD."); return
        for task in self.tasks:
            if self.category_filter.get() and task.category != self.category_filter.get(): continue
            if self.reference_filter.get() and task.reference != self.reference_filter.get(): continue
            if task.target and ((start and task.target < start) or (end and task.target > end)): continue
            record = task.to_record(); self.table.insert("", "end", iid=task.id, values=[record[name] for name in VISIBLE_COLUMNS])

    def edit_cell(self, event: tk.Event) -> None:
        task_id, column = self.table.identify_row(event.y), self.table.identify_column(event.x)
        if not task_id or not column: return
        name = VISIBLE_COLUMNS[int(column[1:]) - 1]
        if name == "ID": return
        task = next(item for item in self.tasks if item.id == task_id)
        value = simpledialog.askstring("Edit task", name, initialvalue=task.to_record()[name], parent=self)
        if value is None: return
        field = name.lower(); converted = value
        try:
            if name == "Target": converted = date.fromisoformat(value) if value else None
            if name == "Status": converted = Status(value)
            updated = replace(task, **{field: converted}); self.store.update(updated); self.refresh()
        except Exception as error: messagebox.showerror("Update failed", str(error))

    def complete(self) -> None:
        selected = self.table.selection()
        if not selected: messagebox.showinfo("Complete", "Select a task first."); return
        try: self.store.complete(selected[0]); self.refresh()
        except Exception as error: messagebox.showerror("Complete failed", str(error))


def main() -> None:
    config = AppConfig.load()
    if not config.api_url:
        raise SystemExit("Set TASKR_API_URL or api_url in ~/.config/taskr/config.json")
    root = tk.Tk(); TaskrApp(root, config, AppsScriptTaskStore(config.api_url)); root.mainloop()


if __name__ == "__main__": main()

"""Tk desktop UI for adding and viewing Tasks."""

from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date, timedelta
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from taskr.models.task import Status, Task, VISIBLE_COLUMNS, creation_timestamp_id
from taskr.storage.apps_script import AppsScriptTaskStore
from taskr.storage.config import AppConfig, ViewConfig


# A launch/build-style version keeps the lightweight desktop client free from a
# separate release-numbering system while still making a running instance easy
# to identify in screenshots and support requests.
APP_VERSION = creation_timestamp_id()


def window_title(version: str = APP_VERSION) -> str:
    return f"taskr - version: {version}"


def target_date(kind: str, today: date | None = None) -> date | None:
    today = today or date.today()
    if kind == "EOD": return today
    if kind == "EOW": return today + timedelta(days=6 - today.weekday())
    if kind == "EOM": return date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    return None


def task_matches(task: Task, view: ViewConfig) -> bool:
    """Return whether a task belongs in a configured view."""
    try:
        start = date.fromisoformat(view.date_from) if view.date_from else None
        end = date.fromisoformat(view.date_to) if view.date_to else None
    except ValueError as error:
        raise ValueError("Dates must use YYYY-MM-DD.") from error
    if (
        (view.category and task.category != view.category)
        or (view.reference and task.reference != view.reference)
        or (view.status and task.status.value != view.status)
        or (task.target and ((start and task.target < start) or (end and task.target > end)))
    ):
        return False
    record = task.to_record()
    return all(record.get(column, "") in selected
               for column, selected in view.column_filters.items())


class ColumnFilterDialog(tk.Toplevel):
    """Spreadsheet-style, searchable checkbox filter for one table column."""

    def __init__(self, parent: ViewPane, column: str, values: list[str], selected: list[str] | None) -> None:
        super().__init__(parent)
        self.parent, self.column, self.values = parent, column, values
        self.title(f"Filter {column}"); self.transient(parent.winfo_toplevel()); self.grab_set()
        self.resizable(False, True)
        body = ttk.Frame(self, padding=12); body.pack(fill="both", expand=True)
        self.search = tk.StringVar(); search = ttk.Entry(body, textvariable=self.search, width=34)
        search.pack(fill="x", pady=(0, 8)); search.bind("<KeyRelease>", self._show)
        self.listbox = tk.Listbox(body, selectmode="multiple", exportselection=False, height=12, width=38)
        self.listbox.pack(fill="both", expand=True)
        self.initial = set(values if selected is None else selected)
        actions = ttk.Frame(body); actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="OK", command=self.accept).pack(side="right", padx=(0, 8))
        ttk.Button(actions, text="Select all", command=lambda: self.listbox.selection_set(0, "end")).pack(side="left")
        ttk.Button(actions, text="Clear", command=lambda: self.listbox.selection_clear(0, "end")).pack(side="left", padx=4)
        self._show(); search.focus_set()

    def _show(self, _event: tk.Event | None = None) -> None:
        # Retain selections while narrowing or widening the search.
        if self.listbox.size():
            displayed = list(self.listbox.get(0, "end"))
            for index in self.listbox.curselection(): self.initial.add(displayed[index])
            for index, value in enumerate(displayed):
                if index not in self.listbox.curselection(): self.initial.discard(value)
        needle = self.search.get().casefold()
        self.listbox.delete(0, "end")
        for value in (item for item in self.values if needle in item.casefold()):
            self.listbox.insert("end", value)
            if value in self.initial: self.listbox.selection_set("end")

    def accept(self) -> None:
        displayed = list(self.listbox.get(0, "end"))
        for index, value in enumerate(displayed):
            if index in self.listbox.curselection(): self.initial.add(value)
            else: self.initial.discard(value)
        self.parent.set_column_filter(self.column, sorted(self.initial, key=str.casefold))
        self.destroy()


class ViewPane(ttk.Frame):
    def __init__(self, app: TaskrApp, notebook: ttk.Notebook, settings: ViewConfig) -> None:
        super().__init__(notebook, padding=8)
        self.app, self.settings = app, settings
        self.table = ttk.Treeview(self, columns=VISIBLE_COLUMNS, show="tree headings", selectmode="browse")
        self.table.heading("#0", text=""); self.table.column("#0", width=28, stretch=False)
        for name in VISIBLE_COLUMNS:
            self.table.heading(name, text=name, command=lambda column=name: self.open_filter(column))
            self.table.column(name, width=100)
        self.table.column("Task", width=220); self.table.pack(fill="both", expand=True, pady=8)
        self.table.tag_configure("child", font=("TkDefaultFont", 9, "italic"))
        self.table.bind("<Double-1>", self.edit_cell)
        buttons = ttk.Frame(self); buttons.pack(fill="x")
        ttk.Button(buttons, text="Refresh", command=app.refresh).pack(side="left")
        ttk.Button(buttons, text="Set parent…", command=self.set_parent).pack(side="right")
        ttk.Button(buttons, text="Complete task", command=self.complete).pack(side="right", padx=6)

    def open_filter(self, column: str) -> None:
        values = sorted({task.to_record()[column] for task in self.app.tasks}, key=str.casefold)
        selected = self.settings.column_filters.get(column)
        ColumnFilterDialog(self, column, values, selected)

    def set_column_filter(self, column: str, selected: list[str]) -> None:
        all_values = {task.to_record()[column] for task in self.app.tasks}
        if set(selected) == all_values:
            self.settings.column_filters.pop(column, None)
        else:
            self.settings.column_filters[column] = selected
        self.app.save_views(); self.render(); self.update_headings()

    def update_headings(self) -> None:
        for name in VISIBLE_COLUMNS:
            marker = " ▼" if name in self.settings.column_filters else " ▾"
            self.table.heading(name, text=name + marker)

    def rename(self) -> None:
        value = simpledialog.askstring("Rename view", "View name:", initialvalue=self.settings.name, parent=self)
        if value and value.strip():
            self.settings.name = value.strip(); self.app.tabs.tab(self, text=self.settings.name); self.app.save_views()

    def render(self) -> None:
        self.update_headings()
        self.table.delete(*self.table.get_children())
        try: visible = [task for task in self.app.tasks if task_matches(task, self.settings)]
        except ValueError as error: messagebox.showerror("Invalid filter", str(error)); return
        ids = {task.id for task in visible}
        pending = list(visible)
        # Insert each generation after its parent. Broken/cyclic references safely
        # fall back to the root rather than hiding a task.
        ordered: list[tuple[Task, str]] = []
        inserted: set[str] = set()
        while pending:
            ready = [task for task in pending
                     if not (task.tags or {}).get("parent")
                     or (task.tags or {}).get("parent") not in ids
                     or (task.tags or {}).get("parent") in inserted]
            if not ready: ready = pending[:]
            for task in ready:
                parent = str((task.tags or {}).get("parent", ""))
                ordered.append((task, parent if parent in inserted else ""))
                inserted.add(task.id); pending.remove(task)
        for task, tree_parent in ordered:
            record = task.to_record()
            self.table.insert(tree_parent, "end", iid=task.id,
                              values=[record[name] for name in VISIBLE_COLUMNS],
                              tags=("child",) if tree_parent else ())
            if tree_parent: self.table.item(tree_parent, open=True)

    def selected_task(self) -> Task | None:
        selected = self.table.selection()
        return next((task for task in self.app.tasks if selected and task.id == selected[0]), None)

    def edit_cell(self, event: tk.Event) -> None:
        task_id, column = self.table.identify_row(event.y), self.table.identify_column(event.x)
        if not task_id or column in ("", "#0"): return
        name = VISIBLE_COLUMNS[int(column[1:]) - 1]
        if name == "ID": return
        task = next(item for item in self.app.tasks if item.id == task_id)
        value = simpledialog.askstring("Edit task", name, initialvalue=task.to_record()[name], parent=self)
        if value is None: return
        converted: object = value
        try:
            if name == "Target": converted = date.fromisoformat(value) if value else None
            if name == "Status": converted = Status(value)
            self.app.store.update(replace(task, **{name.lower(): converted})); self.app.refresh()
        except Exception as error: messagebox.showerror("Update failed", str(error))

    def complete(self) -> None:
        task = self.selected_task()
        if not task: messagebox.showinfo("Complete", "Select a task first."); return
        try: self.app.store.complete(task.id); self.app.refresh()
        except Exception as error: messagebox.showerror("Complete failed", str(error))

    def set_parent(self) -> None:
        task = self.selected_task()
        if not task: messagebox.showinfo("Set parent", "Select a child task first."); return
        candidates = [item for item in self.app.tasks if item.id != task.id]
        prompt = "Parent task ID (blank removes parent):\n\n" + "\n".join(f"{item.id} — {item.task}" for item in candidates)
        parent_id = simpledialog.askstring("Set parent", prompt, initialvalue=str((task.tags or {}).get("parent", "")), parent=self)
        if parent_id is None: return
        parent_id = parent_id.strip()
        if parent_id and parent_id not in {item.id for item in candidates}:
            messagebox.showerror("Set parent", "Choose an ID shown in the list."); return
        tags = dict(task.tags or {})
        if parent_id: tags["parent"] = parent_id
        else: tags.pop("parent", None)
        try: self.app.store.update(replace(task, tags=tags)); self.app.refresh()
        except Exception as error: messagebox.showerror("Update failed", str(error))


class TaskrApp(ttk.Frame):
    def __init__(self, master: tk.Tk, config: AppConfig, store: AppsScriptTaskStore) -> None:
        super().__init__(master, padding=10); self.pack(fill="both", expand=True)
        self.config, self.store, self.tasks = config, store, []
        master.title(window_title()); master.geometry("1180x650")
        toolbar = ttk.Frame(self); toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Add Tasks", command=self.open_add_tasks).pack(side="left")
        ttk.Button(toolbar, text="+ View", command=self.add_view).pack(side="left", padx=6)
        ttk.Button(toolbar, text="− View", command=self.remove_view).pack(side="left")
        ttk.Button(toolbar, text="Rename", command=self.rename_view).pack(side="left", padx=6)
        self.tabs = ttk.Notebook(self); self.tabs.pack(fill="both", expand=True)
        self.views: list[ViewPane] = []
        for settings in config.views: self._append_view(settings)
        self.refresh()

    def _append_view(self, settings: ViewConfig) -> None:
        pane = ViewPane(self, self.tabs, settings); self.views.append(pane); self.tabs.add(pane, text=settings.name)

    def add_view(self) -> None:
        settings = ViewConfig(name=f"View {len(self.views) + 1}")
        self.config.views.append(settings); self._append_view(settings); self.tabs.select(self.views[-1]); self.save_views()

    def remove_view(self) -> None:
        if len(self.views) == 1: messagebox.showinfo("Remove view", "At least one view is required."); return
        index = self.tabs.index("current"); self.tabs.forget(index); self.views.pop(index); self.config.views.pop(index); self.save_views()

    def rename_view(self) -> None:
        self.views[self.tabs.index("current")].rename()

    def save_views(self) -> None:
        try: self.config.save()
        except OSError as error: messagebox.showerror("Save failed", str(error))

    def open_add_tasks(self) -> None:
        window = tk.Toplevel(self); window.title("Add Tasks"); window.transient(self.winfo_toplevel()); window.grab_set()
        body = ttk.Frame(window, padding=12); body.pack(fill="both", expand=True)
        inputs: dict[str, object] = {}
        for row, (label, values) in enumerate((("Category", self.config.categories), ("Reference", self.config.references), ("Assigned", self.config.assigned))):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4)
            box = ttk.Combobox(body, values=values, width=55); box.grid(row=row, column=1, sticky="ew"); inputs[label] = box
        for row, label in enumerate(("Task", "Details"), 3):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="nw", pady=4)
            widget = tk.Text(body, height=2 if label == "Task" else 5, width=55); widget.grid(row=row, column=1, sticky="ew"); inputs[label] = widget
        ttk.Label(body, text="Create for").grid(row=5, column=0, sticky="w")
        buttons = ttk.Frame(body); buttons.grid(row=5, column=1, sticky="w", pady=8)

        def create_for(target: date | None) -> None:
            try:
                values = {key.lower(): widget.get().strip() for key, widget in inputs.items() if isinstance(widget, ttk.Combobox)}
                values["task"] = inputs["Task"].get("1.0", "end").strip(); values["details"] = inputs["Details"].get("1.0", "end").strip()
                self.store.create(Task.new(user=self.config.user, target=target, **values))
                self.config.remember(values["category"], values["reference"], values["assigned"]); self.config.save()
                window.destroy(); self.refresh()
            except Exception as error: messagebox.showerror("Create failed", str(error), parent=window)

        def future() -> None:
            value = simpledialog.askstring("Future date", "Date (YYYY-MM-DD):", parent=window)
            if not value: return
            try:
                chosen = date.fromisoformat(value)
                if chosen < date.today(): raise ValueError
                create_for(chosen)
            except ValueError: messagebox.showerror("Invalid date", "Choose today or a future date in YYYY-MM-DD format.", parent=window)

        for name in ("EOD", "EOW", "EOM"):
            ttk.Button(buttons, text=name, command=lambda n=name: create_for(target_date(n))).pack(side="left")
        ttk.Button(buttons, text="Future date…", command=future).pack(side="left")
        ttk.Button(buttons, text="No date", command=lambda: create_for(None)).pack(side="left")
        ttk.Label(body, text="Selecting a date creates the task.").grid(row=6, column=1, sticky="w")
        body.columnconfigure(1, weight=1)

    def refresh(self) -> None:
        try:
            self.tasks = self.store.list()
            for view in self.views: view.render()
        except Exception as error: messagebox.showerror("Load failed", str(error))


def main() -> None:
    config = AppConfig.load()
    if not config.api_url: raise SystemExit("Set TASKR_API_URL or api_url in ~/.config/taskr/config.json")
    root = tk.Tk(); TaskrApp(root, config, AppsScriptTaskStore(config.api_url)); root.mainloop()


if __name__ == "__main__": main()

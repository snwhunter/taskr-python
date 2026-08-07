"""Tk desktop UI for adding and viewing Tasks."""

from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date, timedelta
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from taskr.models.task import Status, Task, VISIBLE_COLUMNS, creation_timestamp_id
from taskr.storage.apps_script import AppsScriptTaskStore
from taskr.storage.config import AppConfig, ViewConfig, default_cache_path
from taskr.storage.sqlite import SQLiteTaskStore


# A launch/build-style version keeps the lightweight desktop client free from a
# separate release-numbering system while still making a running instance easy
# to identify in screenshots and support requests.
APP_VERSION = creation_timestamp_id()
TABLE_COLUMNS = tuple(column for column in VISIBLE_COLUMNS if column != "Task")


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


def add_task_filter_value(view: ViewConfig, column: str) -> str:
    """Return an unambiguous Category/Reference value from the active view."""
    configured = getattr(view, column.lower())
    if configured:
        return configured
    selected = view.column_filters.get(column, [])
    return selected[0] if len(selected) == 1 else ""


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
        self.table = ttk.Treeview(self, columns=TABLE_COLUMNS, show="tree headings", selectmode="browse")
        self.table.heading("#0", text="Task", command=lambda: self.open_filter("Task"))
        self.table.column("#0", width=240, anchor="w")
        for name in TABLE_COLUMNS:
            self.table.heading(name, text=name, command=lambda column=name: self.open_filter(column))
            self.table.column(name, width=100, anchor="w" if name in ("Details", "Notes") else "center")
        self.table.pack(fill="both", expand=True, pady=8)
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
            self.table.heading("#0" if name == "Task" else name, text=name + marker)

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
                              text=record["Task"],
                              values=[record[name] for name in TABLE_COLUMNS])
            if tree_parent: self.table.item(tree_parent, open=True)

    def selected_task(self) -> Task | None:
        selected = self.table.selection()
        return next((task for task in self.app.tasks if selected and task.id == selected[0]), None)

    def edit_cell(self, event: tk.Event) -> None:
        task_id, column = self.table.identify_row(event.y), self.table.identify_column(event.x)
        if not task_id or not column: return
        name = "Task" if column == "#0" else TABLE_COLUMNS[int(column[1:]) - 1]
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
        parent_id = ParentTaskDialog.choose(self, candidates, str((task.tags or {}).get("parent", "")))
        if parent_id is None: return
        tags = dict(task.tags or {})
        if parent_id: tags["parent"] = parent_id
        else: tags.pop("parent", None)
        try: self.app.store.update(replace(task, tags=tags)); self.app.refresh()
        except Exception as error: messagebox.showerror("Update failed", str(error))


class ParentTaskDialog(tk.Toplevel):
    """Choose a task from either a compact pull-down or a clickable row list."""

    def __init__(self, parent: tk.Misc, tasks: list[Task], initial: str = "") -> None:
        super().__init__(parent)
        self.result: str | None = None
        self.tasks = tasks
        self.title("Set parent"); self.transient(parent.winfo_toplevel()); self.grab_set()
        body = ttk.Frame(self, padding=12); body.pack(fill="both", expand=True)
        ttk.Label(body, text="Parent task (blank removes parent)").pack(anchor="w")
        self.labels = [""] + [f"{task.task} — {task.id}" for task in tasks]
        self.ids = [""] + [task.id for task in tasks]
        self.choice = ttk.Combobox(body, values=self.labels, state="readonly", width=64)
        self.choice.pack(fill="x", pady=(4, 10)); self.choice.current(self.ids.index(initial) if initial in self.ids else 0)
        table = ttk.Treeview(body, columns=("Task", "ID"), show="headings", height=min(10, max(3, len(tasks))))
        table.heading("Task", text="Task"); table.heading("ID", text="ID")
        table.column("Task", width=340, anchor="w"); table.column("ID", width=130, anchor="center")
        for task in tasks: table.insert("", "end", iid=task.id, values=(task.task, task.id))
        table.pack(fill="both", expand=True)
        table.bind("<<TreeviewSelect>>", lambda _event: self.choice.current(self.ids.index(table.selection()[0])))
        table.bind("<Double-1>", lambda _event: self.accept())
        actions = ttk.Frame(body); actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Set parent", command=self.accept).pack(side="right", padx=6)

    def accept(self) -> None:
        self.result = self.ids[self.choice.current()]
        self.destroy()

    @classmethod
    def choose(cls, parent: tk.Misc, tasks: list[Task], initial: str = "") -> str | None:
        dialog = cls(parent, tasks, initial)
        parent.wait_window(dialog)
        return dialog.result


class TaskrApp(ttk.Frame):
    def __init__(self, master: tk.Tk, config: AppConfig, store: SQLiteTaskStore) -> None:
        super().__init__(master, padding=10); self.pack(fill="both", expand=True)
        self.config, self.store, self.tasks = config, store, []
        master.title(window_title()); master.geometry("1180x650")
        toolbar = ttk.Frame(self); toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Add Tasks", command=self.open_add_tasks).pack(side="left")
        ttk.Button(toolbar, text="+ View", command=self.add_view).pack(side="left", padx=6)
        ttk.Button(toolbar, text="− View", command=self.remove_view).pack(side="left")
        ttk.Button(toolbar, text="Rename", command=self.rename_view).pack(side="left", padx=6)
        self.sync_text = tk.StringVar(value="Sync: checking…")
        ttk.Label(toolbar, textvariable=self.sync_text).pack(side="right")
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
        active_view = self.views[self.tabs.index("current")].settings
        for row, (label, values) in enumerate((("Category", self.config.categories), ("Reference", self.config.references), ("Assigned", self.config.assigned))):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4)
            filtered = add_task_filter_value(active_view, label) if label in ("Category", "Reference") else ""
            choices = list(dict.fromkeys(([filtered] if filtered else []) + list(values)))
            box = ttk.Combobox(body, values=choices, width=55); box.grid(row=row, column=1, sticky="ew")
            if filtered: box.set(filtered)
            inputs[label] = box
        ttk.Label(body, text="Parent").grid(row=3, column=0, sticky="w", pady=4)
        parent_tasks = [task for task in self.tasks if task_matches(task, active_view)]
        parent_labels = [""] + [f"{task.task} — {task.id}" for task in parent_tasks]
        parent = ttk.Combobox(body, values=parent_labels, state="readonly", width=55)
        parent.grid(row=3, column=1, sticky="ew"); parent.current(0); inputs["Parent"] = parent
        for row, label in enumerate(("Task", "Details"), 4):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="nw", pady=4)
            widget = tk.Text(body, height=2 if label == "Task" else 5, width=55); widget.grid(row=row, column=1, sticky="ew"); inputs[label] = widget
        ttk.Label(body, text="Create for").grid(row=6, column=0, sticky="w")
        buttons = ttk.Frame(body); buttons.grid(row=6, column=1, sticky="w", pady=8)

        def create_for(target: date | None) -> None:
            try:
                values = {key.lower(): inputs[key].get().strip() for key in ("Category", "Reference", "Assigned")}
                values["task"] = inputs["Task"].get("1.0", "end").strip(); values["details"] = inputs["Details"].get("1.0", "end").strip()
                parent_index = parent.current()
                if parent_index > 0: values["tags"] = {"parent": parent_tasks[parent_index - 1].id}
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
        ttk.Label(body, text="Selecting a date creates the task.").grid(row=7, column=1, sticky="w")
        body.columnconfigure(1, weight=1)

    def refresh(self) -> None:
        try:
            self.tasks = self.store.list()
            for view in self.views: view.render()
            state = self.store.state()
            self.sync_text.set(f"Sync: {state.pending} pending" if state.pending else
                               (f"Sync: last {state.last_sync.replace('T', ' ')[:19]} UTC"
                                if state.last_sync else "Sync: never"))
            self._start_sync()
        except Exception as error: messagebox.showerror("Load failed", str(error))

    def _start_sync(self) -> None:
        if getattr(self, "_syncing", False): return
        self._syncing = True; self.sync_text.set("Sync: syncing…")
        results: queue.Queue[Exception | None] = queue.Queue()

        def work() -> None:
            try:
                self.store.sync()
                results.put(None)
            except Exception as error:
                results.put(error)

        def finished(error: Exception | None) -> None:
            self._syncing = False
            if error:
                pending = self.store.state().pending
                self.sync_text.set(f"Sync: offline ({pending} pending)")
                return
            self.tasks = self.store.list()
            for view in self.views: view.render()
            state = self.store.state()
            self.sync_text.set(f"Sync: last {state.last_sync.replace('T', ' ')[:19]} UTC")
            if state.pending: self._start_sync()

        def poll() -> None:
            try: result = results.get_nowait()
            except queue.Empty: self.after(50, poll)
            else: finished(result)

        threading.Thread(target=work, name="taskr-sync", daemon=True).start()
        self.after(50, poll)


def main() -> None:
    config = AppConfig.load()
    if not config.api_url: raise SystemExit("Set TASKR_API_URL or api_url in ~/.config/taskr/config.json")
    remote = AppsScriptTaskStore(config.api_url)
    root = tk.Tk(); TaskrApp(root, config, SQLiteTaskStore(default_cache_path(), remote)); root.mainloop()


if __name__ == "__main__": main()

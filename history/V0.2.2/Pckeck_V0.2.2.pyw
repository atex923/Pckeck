"""Pckeck V0.2.2 - PDF comparison with a difference-page sidebar."""
from __future__ import annotations

import ast
from itertools import zip_longest
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
)


ROOT = Path(__file__).resolve().parent
LAYOUT_BASE = ROOT / "runtime" / "pcheck_v021_layout_base.pyw"


def load_layout_base():
    tree = ast.parse(LAYOUT_BASE.read_text(encoding="utf-8"), filename=str(LAYOUT_BASE))
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        call = tree.body[-1].value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "main":
            tree.body.pop()
    namespace = {"__name__": "_pcheck_v021_layout_base", "__file__": str(LAYOUT_BASE)}
    exec(compile(tree, str(LAYOUT_BASE), "exec"), namespace)
    return namespace


base = load_layout_base()
core = base["core"]
implementation = base["implementation"]
LibraryWindow = base["LibraryWindow"]
base["previous"]["APP_VERSION"] = "V0.2.2"
core.VERSION = "V0.2.2"


class DifferencePageWindow(LibraryWindow):
    def __init__(self, old_path="", new_path=""):
        super().__init__(old_path, new_path)
        self.setWindowTitle("文檔校對工")
        self._arrange_two_toolbar_rows()
        self._build_difference_sidebar()

    @staticmethod
    def _action_widget(action):
        return action.defaultWidget() if hasattr(action, "defaultWidget") else None

    def _arrange_two_toolbar_rows(self):
        toolbars = self.findChildren(core.QToolBar)
        main_toolbar = next((bar for bar in toolbars if bar.windowTitle() == "工具"), None)
        library_toolbar = next((bar for bar in toolbars if bar.windowTitle() == "比對庫"), None)
        if not main_toolbar or not library_toolbar:
            return

        actions = main_toolbar.actions()
        marker_index = None
        for index, action in enumerate(actions):
            widget = self._action_widget(action)
            if widget is not None and getattr(widget, "text", lambda: "")() == "同步頁：舊":
                marker_index = index
                break

        if marker_index is not None:
            library_toolbar.addSeparator()
            for action in actions[marker_index:]:
                main_toolbar.removeAction(action)
                library_toolbar.addAction(action)

        while main_toolbar.actions() and main_toolbar.actions()[-1].isSeparator():
            main_toolbar.removeAction(main_toolbar.actions()[-1])

        self.insertToolBarBreak(library_toolbar)

    def _build_difference_sidebar(self):
        main_splitter = self.centralWidget()
        self.chapter_table.setMaximumWidth(16777215)

        self.difference_table = QTableWidget(0, 4)
        self.difference_table.setHorizontalHeaderLabels(
            ["舊檔頁", "新檔頁", "類型", "標線"]
        )
        header = self.difference_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.difference_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.difference_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.difference_table.cellDoubleClicked.connect(self.jump_difference)

        self.sidebar_tabs = QTabWidget()
        self.sidebar_tabs.setMaximumWidth(430)
        self.sidebar_tabs.addTab(self.difference_table, "不同處頁碼")
        self.sidebar_tabs.addTab(self.chapter_table, "篇章節")
        main_splitter.insertWidget(0, self.sidebar_tabs)
        main_splitter.setSizes([360, 1140])

    def open_side(self, side, path):
        super().open_side(side, path)
        if hasattr(self, "difference_table"):
            self.difference_table.setRowCount(0)

    def start_compare(self):
        if hasattr(self, "difference_table"):
            self.difference_table.setRowCount(0)
        super().start_compare()

    @staticmethod
    def _difference_rows(result):
        rows = result.get("difference_pages", [])
        if rows:
            return rows

        old_pages = sorted(int(page) for page in result.get("old_marks", {}))
        new_pages = sorted(int(page) for page in result.get("new_marks", {}))
        return [
            {
                "old_page": old_page,
                "new_page": new_page,
                "kind": "差異",
                "mark_count": (
                    len(result.get("old_marks", {}).get(old_page, []))
                    + len(result.get("new_marks", {}).get(new_page, []))
                ),
            }
            for old_page, new_page in zip_longest(old_pages, new_pages)
        ]

    def _populate_difference_pages(self, result):
        rows = self._difference_rows(result)
        self.difference_table.setRowCount(len(rows))
        for row_index, difference in enumerate(rows):
            old_page = difference.get("old_page")
            new_page = difference.get("new_page")
            values = (
                "-" if old_page is None else str(old_page + 1),
                "-" if new_page is None else str(new_page + 1),
                difference.get("kind", "差異"),
                str(difference.get("mark_count", 0)),
            )
            for column, value in enumerate(values):
                self.difference_table.setItem(
                    row_index, column, QTableWidgetItem(value)
                )
            self.difference_table.item(row_index, 0).setData(
                core.Qt.UserRole, difference
            )

    def on_finished(self, result):
        super().on_finished(result)
        self._populate_difference_pages(result)

    def open_library(self, path, show_message=True):
        opened = super().open_library(path, show_message=show_message)
        if opened and self.result:
            self._populate_difference_pages(self.result)
        return opened

    def jump_difference(self, row, _column):
        item = self.difference_table.item(row, 0)
        if not item:
            return
        difference = item.data(core.Qt.UserRole)
        if difference.get("old_page") is not None:
            self.old_pane.goto_page(difference["old_page"])
        if difference.get("new_page") is not None:
            self.new_pane.goto_page(difference["new_page"])


core.MainWindow = DifferencePageWindow
implementation.main()

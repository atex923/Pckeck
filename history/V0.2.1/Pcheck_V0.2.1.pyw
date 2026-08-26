"""Pcheck V0.2.1 - fixed two-row toolbar layout."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LAYOUT_BASE = ROOT / "pcheck_v021_layout_base.pyw"


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
base["previous"]["APP_VERSION"] = "V0.2.1"
core.VERSION = "V0.2.1"


class TwoRowWindow(LibraryWindow):
    def __init__(self, old_path="", new_path=""):
        super().__init__(old_path, new_path)
        self.setWindowTitle("文檔校對工")
        self._arrange_two_toolbar_rows()

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


core.MainWindow = TwoRowWindow
implementation.main()

"""Pcheck V0.2.1 - fixed two-row toolbar layout."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PREVIOUS_VERSION = ROOT / "Pcheck_V0.2.0.pyw"


def load_previous_runtime():
    tree = ast.parse(PREVIOUS_VERSION.read_text(encoding="utf-8"), filename=str(PREVIOUS_VERSION))
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        call = tree.body[-1].value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "main":
            tree.body.pop()
    namespace = {"__name__": "_pcheck_v020_runtime", "__file__": str(PREVIOUS_VERSION)}
    exec(compile(tree, str(PREVIOUS_VERSION), "exec"), namespace)
    return namespace


previous = load_previous_runtime()
core = previous["core"]
implementation = previous["implementation"]
LibraryWindow = previous["LibraryWindow"]
previous["APP_VERSION"] = "V0.2.1"
core.VERSION = "V0.2.1"


class TwoRowWindow(LibraryWindow):
    def __init__(self, old_path="", new_path=""):
        super().__init__(old_path, new_path)
        self.setWindowTitle("文檔校對工")
        self._arrange_two_toolbar_rows()

    def _arrange_two_toolbar_rows(self):
        toolbars = self.findChildren(core.QToolBar)
        main_toolbar = next((bar for bar in toolbars if bar.windowTitle() == "工具"), None)
        library_toolbar = next((bar for bar in toolbars if bar.windowTitle() == "比對庫"), None)
        if not main_toolbar or not library_toolbar:
            return

        # 將「同步頁：舊」開始的全部控制項移至第二列。
        actions = main_toolbar.actions()
        marker_index = None
        for index, action in enumerate(actions):
            widget = action.defaultWidget()
            if widget is not None and getattr(widget, "text", lambda: "")() == "同步頁：舊":
                marker_index = index
                break
        if marker_index is not None:
            library_toolbar.addSeparator()
            for action in actions[marker_index:]:
                main_toolbar.removeAction(action)
                library_toolbar.addAction(action)

        # 移除第一列末端因搬移控制項而留下的多餘分隔線。
        while main_toolbar.actions() and main_toolbar.actions()[-1].isSeparator():
            main_toolbar.removeAction(main_toolbar.actions()[-1])

        # 強制比對庫工具列從下一列開始，視窗再寬也維持兩列。
        self.insertToolBarBreak(library_toolbar)


core.MainWindow = TwoRowWindow
implementation.main()

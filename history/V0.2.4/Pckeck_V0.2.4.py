"""Pckeck V0.2.4 - PDF comparison with reusable right-pane mark data."""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
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
base["previous"]["APP_VERSION"] = "V0.2.4"
core.VERSION = "V0.2.4"


BasePdfPane = core.PdfPane


class MarkupPdfPane(BasePdfPane):
    manualMarksChanged = Signal()

    def __init__(self, role):
        super().__init__(role)
        self.manual_marks = []
        self.markup_tool = "browse"
        self.markup_color = "#fff176"
        self.markup_width = 8.0
        self._drag_page = None
        self._drag_start = None
        self._drag_current = None

    def load_pdf(self, path):
        super().load_pdf(path)
        self.manual_marks = []
        self._cancel_drag()

    def set_markup_tool(self, tool):
        self.markup_tool = tool
        if tool == "browse":
            self.viewport().unsetCursor()
            self._cancel_drag()
        else:
            self.viewport().setCursor(core.Qt.CrossCursor)

    def set_markup_style(self, color, width):
        self.markup_color = QColor(color).name()
        self.markup_width = max(0.5, min(40.0, float(width)))

    def set_manual_marks(self, marks):
        restored = []
        for mark in marks or []:
            if mark.get("tool") not in {"highlight", "double_strike"}:
                continue
            restored.append({
                "page": int(mark["page"]),
                "tool": mark["tool"],
                "start": [float(value) for value in mark["start"]],
                "end": [float(value) for value in mark["end"]],
                "color": QColor(mark.get("color", "#fff176")).name(),
                "width": max(0.5, min(40.0, float(mark.get("width", 8.0)))),
            })
        self.manual_marks = restored
        self.viewport().update()

    def undo_manual_mark(self):
        if not self.manual_marks:
            return False
        self.manual_marks.pop()
        self.viewport().update()
        self.manualMarksChanged.emit()
        return True

    def clear_manual_marks(self):
        if not self.manual_marks:
            return False
        self.manual_marks.clear()
        self.viewport().update()
        self.manualMarksChanged.emit()
        return True

    def _cancel_drag(self):
        self._drag_page = None
        self._drag_start = None
        self._drag_current = None
        self.viewport().update()

    def _page_point(self, page_no, position, clamp=False):
        if not self.doc or page_no < 0 or page_no >= len(self.page_sizes):
            return None
        width, height = self.page_sizes[page_no]
        draw_w = width * self.zoom
        draw_x = max(core.PAGE_GAP / 2, (self.viewport().width() - draw_w) / 2)
        document_y = position.y() + self.verticalScrollBar().value()
        x = (position.x() - draw_x) / self.zoom
        y = (document_y - self.page_tops[page_no]) / self.zoom
        if clamp:
            return (
                max(0.0, min(width, x)),
                max(0.0, min(height, y)),
            )
        if 0.0 <= x <= width and 0.0 <= y <= height:
            return x, y
        return None

    def _point_at(self, position):
        if not self.doc:
            return None
        document_y = position.y() + self.verticalScrollBar().value()
        page_no = self._page_index_at(document_y)
        point = self._page_point(page_no, position)
        return (page_no, point) if point is not None else None

    def mousePressEvent(self, event):
        if self.markup_tool != "browse" and event.button() == core.Qt.LeftButton:
            located = self._point_at(event.position())
            if located:
                self._drag_page, self._drag_start = located
                self._drag_current = self._drag_start
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_page is not None:
            self._drag_current = self._page_point(
                self._drag_page, event.position(), clamp=True
            )
            self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_page is not None and event.button() == core.Qt.LeftButton:
            end = self._page_point(self._drag_page, event.position(), clamp=True)
            start = self._drag_start
            page_no = self._drag_page
            self._cancel_drag()
            if end and start and math.dist(start, end) >= 1.0:
                self.manual_marks.append({
                    "page": page_no,
                    "tool": self.markup_tool,
                    "start": [start[0], start[1]],
                    "end": [end[0], end[1]],
                    "color": self.markup_color,
                    "width": self.markup_width,
                })
                self.viewport().update()
                self.manualMarksChanged.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    @staticmethod
    def _parallel_offsets(start, end, gap):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = max(1e-9, math.hypot(dx, dy))
        return (-dy / length * gap, dx / length * gap)

    def _draw_manual_mark(self, painter, mark):
        page_no = int(mark["page"])
        if page_no < 0 or page_no >= len(self.page_sizes):
            return
        width, _height = self.page_sizes[page_no]
        draw_w = width * self.zoom
        draw_x = max(core.PAGE_GAP / 2, (self.viewport().width() - draw_w) / 2)
        draw_y = self.page_tops[page_no] - self.verticalScrollBar().value()
        start = mark["start"]
        end = mark["end"]
        p1 = core.QPoint(
            int(draw_x + start[0] * self.zoom),
            int(draw_y + start[1] * self.zoom),
        )
        p2 = core.QPoint(
            int(draw_x + end[0] * self.zoom),
            int(draw_y + end[1] * self.zoom),
        )
        color = QColor(mark["color"])
        mark_width = float(mark["width"])
        if mark["tool"] == "highlight":
            color.setAlpha(105)
            pen = QPen(color)
            pen.setWidthF(max(1.0, mark_width * self.zoom))
            pen.setCapStyle(core.Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(p1, p2)
            return

        color.setAlpha(230)
        pen = QPen(color)
        pen.setWidthF(max(0.7, mark_width * self.zoom))
        pen.setCapStyle(core.Qt.RoundCap)
        painter.setPen(pen)
        offset = self._parallel_offsets(start, end, mark_width * 1.4 + 1.2)
        ox = int(offset[0] * self.zoom)
        oy = int(offset[1] * self.zoom)
        painter.drawLine(p1 + core.QPoint(ox, oy), p2 + core.QPoint(ox, oy))
        painter.drawLine(p1 - core.QPoint(ox, oy), p2 - core.QPoint(ox, oy))

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.doc:
            return
        painter = QPainter(self.viewport())
        for mark in self.manual_marks:
            self._draw_manual_mark(painter, mark)
        if self._drag_page is not None and self._drag_current is not None:
            self._draw_manual_mark(painter, {
                "page": self._drag_page,
                "tool": self.markup_tool,
                "start": self._drag_start,
                "end": self._drag_current,
                "color": self.markup_color,
                "width": self.markup_width,
            })


core.PdfPane = MarkupPdfPane


class DifferencePageWindow(LibraryWindow):
    def __init__(self, old_path="", new_path=""):
        super().__init__(old_path, new_path)
        self.setWindowTitle("文檔校對工")
        self._arrange_two_toolbar_rows()
        self._build_difference_sidebar()
        self._build_markup_toolbar()

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

    def _build_markup_toolbar(self):
        self.addToolBarBreak(core.Qt.TopToolBarArea)
        toolbar = QToolBar("自訂標記")
        toolbar.setMovable(False)
        self.addToolBar(core.Qt.TopToolBarArea, toolbar)

        self.markup_action_group = QActionGroup(self)
        self.markup_action_group.setExclusive(True)
        for text, tool in (
            ("瀏覽", "browse"),
            ("螢光筆", "highlight"),
            ("雙刪除線", "double_strike"),
        ):
            action = QAction(text, self)
            action.setCheckable(True)
            action.setData(tool)
            action.setToolTip(f"切換為{text}模式")
            self.markup_action_group.addAction(action)
            toolbar.addAction(action)
            if tool == "browse":
                action.setChecked(True)
        self.markup_action_group.triggered.connect(self._set_markup_tool)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("顏色"))
        self.markup_color = "#fff176"
        self.color_button = QPushButton()
        self.color_button.setFixedSize(34, 24)
        self.color_button.setToolTip("選擇自訂標記顏色")
        self.color_button.clicked.connect(self._choose_markup_color)
        toolbar.addWidget(self.color_button)
        self._refresh_color_button()

        toolbar.addWidget(QLabel("粗細"))
        self.markup_width_spin = QDoubleSpinBox()
        self.markup_width_spin.setRange(0.5, 40.0)
        self.markup_width_spin.setDecimals(1)
        self.markup_width_spin.setSingleStep(0.5)
        self.markup_width_spin.setValue(8.0)
        self.markup_width_spin.setSuffix(" pt")
        self.markup_width_spin.setFixedWidth(90)
        self.markup_width_spin.setToolTip("設定螢光筆寬度或雙刪除線線寬")
        self.markup_width_spin.valueChanged.connect(self._apply_markup_style)
        toolbar.addWidget(self.markup_width_spin)

        toolbar.addSeparator()
        for text, callback in (
            ("復原左", lambda _checked=False: self._undo_markup(self.old_pane)),
            ("復原右", lambda _checked=False: self._undo_markup(self.new_pane)),
            ("清除左", lambda _checked=False: self._clear_markup(self.old_pane)),
            ("清除右", lambda _checked=False: self._clear_markup(self.new_pane)),
        ):
            action = QAction(text, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)

        toolbar.addSeparator()
        self.export_right_marks_action = QAction("匯出右欄標記資料", self)
        self.export_right_marks_action.setToolTip(
            "匯出右側 PDF 的自動差異與自訂標記，供 PDF 找碴程式疊圖"
        )
        self.export_right_marks_action.triggered.connect(self.export_right_mark_data)
        toolbar.addAction(self.export_right_marks_action)

        self.old_pane.manualMarksChanged.connect(
            lambda: self._manual_marks_changed("左側")
        )
        self.new_pane.manualMarksChanged.connect(
            lambda: self._manual_marks_changed("右側")
        )
        self._apply_markup_style()

    def _set_markup_tool(self, action):
        tool = action.data()
        self.old_pane.set_markup_tool(tool)
        self.new_pane.set_markup_tool(tool)
        self.status_text.setText(f"自訂標記模式：{action.text()}")

    def _choose_markup_color(self):
        chosen = QColorDialog.getColor(
            QColor(self.markup_color), self, "選擇標記顏色"
        )
        if not chosen.isValid():
            return
        self.markup_color = chosen.name()
        self._refresh_color_button()
        self._apply_markup_style()

    def _refresh_color_button(self):
        color = QColor(self.markup_color)
        foreground = "#111111" if color.lightness() > 140 else "#ffffff"
        self.color_button.setStyleSheet(
            f"background:{color.name()};color:{foreground};border:1px solid #666;"
        )

    def _apply_markup_style(self):
        width = self.markup_width_spin.value()
        self.old_pane.set_markup_style(self.markup_color, width)
        self.new_pane.set_markup_style(self.markup_color, width)

    def _manual_marks_changed(self, side):
        total = len(self.old_pane.manual_marks) + len(self.new_pane.manual_marks)
        self.status_text.setText(f"{side}自訂標記已更新，共 {total} 筆")

    def _undo_markup(self, pane):
        if not pane.undo_manual_mark():
            self.status_text.setText(f"{pane.role}沒有可復原的自訂標記")

    def _clear_markup(self, pane):
        if not pane.manual_marks:
            self.status_text.setText(f"{pane.role}沒有自訂標記")
            return
        answer = QMessageBox.question(
            self, "清除自訂標記", f"確定清除{pane.role}的全部自訂標記嗎？"
        )
        if answer == QMessageBox.Yes:
            pane.clear_manual_marks()

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

    def _settings_snapshot(self):
        settings = super()._settings_snapshot()
        checked_action = self.markup_action_group.checkedAction()
        settings["manual_markup"] = {
            "old": self.old_pane.manual_marks,
            "new": self.new_pane.manual_marks,
            "tool": checked_action.data() if checked_action else "browse",
            "color": self.markup_color,
            "width": self.markup_width_spin.value(),
        }
        return settings

    def open_library(self, path, show_message=True):
        opened = super().open_library(path, show_message=show_message)
        if opened and self.result:
            self._populate_difference_pages(self.result)
        if opened:
            payload = self._read_library(Path(path))
            markup = payload["settings"].get("manual_markup", {})
            self.old_pane.set_manual_marks(markup.get("old", []))
            self.new_pane.set_manual_marks(markup.get("new", []))
            self.markup_color = QColor(
                markup.get("color", self.markup_color)
            ).name()
            self.markup_width_spin.setValue(
                float(markup.get("width", self.markup_width_spin.value()))
            )
            tool = markup.get("tool", "browse")
            for action in self.markup_action_group.actions():
                if action.data() == tool:
                    action.setChecked(True)
                    self.old_pane.set_markup_tool(tool)
                    self.new_pane.set_markup_tool(tool)
                    break
            self._refresh_color_button()
            self._apply_markup_style()
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

    @staticmethod
    def _file_sha256(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _right_overlay_records(self):
        overlays = []
        automatic_marks = self.result.get("new_marks", {}) if self.result else {}
        for page_no in sorted(automatic_marks, key=int):
            for rect, color in automatic_marks[page_no]:
                normalized_color = QColor(color).name()
                overlays.append({
                    "id": f"auto-{len(overlays) + 1:04d}",
                    "page_index": int(page_no),
                    "page_number": int(page_no) + 1,
                    "source": "automatic_difference",
                    "kind": "underline",
                    "difference_type": (
                        "addition" if color == core.BLUE else "modification"
                    ),
                    "rect": [float(value) for value in rect],
                    "color": normalized_color,
                    "width_pt": 1.5,
                    "opacity": 1.0,
                })

        automatic_count = len(overlays)
        for mark in self.new_pane.manual_marks:
            page_no = int(mark["page"])
            overlays.append({
                "id": f"manual-{len(overlays) - automatic_count + 1:04d}",
                "page_index": page_no,
                "page_number": page_no + 1,
                "source": "manual",
                "kind": mark["tool"],
                "start": [float(value) for value in mark["start"]],
                "end": [float(value) for value in mark["end"]],
                "color": QColor(mark["color"]).name(),
                "width_pt": float(mark["width"]),
                "opacity": 0.36 if mark["tool"] == "highlight" else 1.0,
            })
        return overlays

    def build_right_mark_payload(self):
        if not self.new_pane.path:
            raise ValueError("尚未載入右側 PDF。")

        source_path = Path(self.new_pane.path)
        overlays = self._right_overlay_records()
        automatic_count = sum(
            item["source"] == "automatic_difference" for item in overlays
        )
        page_links = []
        if self.result:
            for difference in self._difference_rows(self.result):
                if difference.get("new_page") is None:
                    continue
                page_links.append({
                    "old_page_index": difference.get("old_page"),
                    "old_page_number": (
                        None
                        if difference.get("old_page") is None
                        else int(difference["old_page"]) + 1
                    ),
                    "right_page_index": int(difference["new_page"]),
                    "right_page_number": int(difference["new_page"]) + 1,
                    "difference_type": difference.get("kind", "差異"),
                    "mark_count": int(difference.get("mark_count", 0)),
                })

        return {
            "format": "pckeck-right-mark-overlay",
            "schema_version": 1,
            "app": {"name": "Pckeck", "version": "V0.2.4"},
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "coordinate_system": {
                "unit": "pdf_point",
                "points_per_inch": 72,
                "origin": "top_left",
                "x_axis": "right",
                "y_axis": "down",
                "page_index_base": 0,
                "page_number_base": 1,
            },
            "source_pdf": {
                "filename": source_path.name,
                "sha256": self._file_sha256(source_path),
                "file_size_bytes": source_path.stat().st_size,
                "page_count": len(self.new_pane.page_sizes),
                "pages": [
                    {
                        "page_index": index,
                        "page_number": index + 1,
                        "width_pt": float(width),
                        "height_pt": float(height),
                    }
                    for index, (width, height) in enumerate(self.new_pane.page_sizes)
                ],
            },
            "page_links": page_links,
            "overlays": overlays,
            "summary": {
                "automatic_mark_count": automatic_count,
                "manual_mark_count": len(overlays) - automatic_count,
                "overlay_count": len(overlays),
            },
        }

    def write_right_mark_data(self, path):
        target = Path(path)
        if not target.name.lower().endswith(".json"):
            target = target.with_name(target.name + ".pcheckmarks.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        try:
            temporary.write_text(
                json.dumps(
                    self.build_right_mark_payload(), ensure_ascii=False, indent=2
                ) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, target)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
        return target

    def export_right_mark_data(self):
        if not self.new_pane.path:
            QMessageBox.information(self, "尚未載入", "請先載入右側 PDF。")
            return
        if not self._right_overlay_records():
            QMessageBox.information(self, "尚無標記", "右側頁面目前沒有可匯出的標記。")
            return

        default_name = (
            Path(self.new_pane.path).with_suffix("").name
            + "_右欄標記.pcheckmarks.json"
        )
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "匯出右欄標記資料",
            str(Path(self.new_pane.path).parent / default_name),
            "Pckeck 標記資料 (*.pcheckmarks.json);;JSON (*.json)",
        )
        if not selected:
            return
        try:
            target = self.write_right_mark_data(selected)
            self.status_text.setText(f"右欄標記資料已匯出：{target}")
            QMessageBox.information(
                self,
                "匯出完成",
                f"已輸出右欄標記資料：\n{target}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "匯出失敗", str(exc))

    @staticmethod
    def _color_rgb(color):
        qcolor = QColor(color)
        return qcolor.redF(), qcolor.greenF(), qcolor.blueF()

    @classmethod
    def _annotated_copy_with_manual(cls, source, automatic_marks, manual_marks, output):
        doc = core.fitz.open(source)
        try:
            for page_no, page_marks in (automatic_marks or {}).items():
                page = doc[int(page_no)]
                for rect, color in page_marks:
                    x0, _y0, x1, y1 = rect
                    annot = page.add_line_annot((x0, y1 - 0.8), (x1, y1 - 0.8))
                    rgb = (
                        (0.9, 0.12, 0.12)
                        if color == core.RED
                        else (0.05, 0.35, 0.88)
                    )
                    annot.set_colors(stroke=rgb)
                    annot.set_border(width=1.5)
                    annot.update()

            for mark in manual_marks:
                page = doc[int(mark["page"])]
                start = tuple(mark["start"])
                end = tuple(mark["end"])
                width = float(mark["width"])
                rgb = cls._color_rgb(mark["color"])
                if mark["tool"] == "highlight":
                    annot = page.add_ink_annot([[start, end]])
                    annot.set_colors(stroke=rgb)
                    annot.set_border(width=width)
                    annot.set_opacity(0.36)
                    annot.update()
                    continue

                offset = MarkupPdfPane._parallel_offsets(
                    start, end, width * 1.4 + 1.2
                )
                for sign in (-1.0, 1.0):
                    shifted_start = (
                        start[0] + offset[0] * sign,
                        start[1] + offset[1] * sign,
                    )
                    shifted_end = (
                        end[0] + offset[0] * sign,
                        end[1] + offset[1] * sign,
                    )
                    annot = page.add_line_annot(shifted_start, shifted_end)
                    annot.set_colors(stroke=rgb)
                    annot.set_border(width=width)
                    annot.update()
            doc.save(output, garbage=3, deflate=True)
        finally:
            doc.close()

    def export_pdfs(self):
        if not self.old_pane.path or not self.new_pane.path:
            QMessageBox.information(self, "尚未載入", "請先載入舊檔與新檔。")
            return
        automatic_old = self.result.get("old_marks", {}) if self.result else {}
        automatic_new = self.result.get("new_marks", {}) if self.result else {}
        has_marks = any((
            automatic_old,
            automatic_new,
            self.old_pane.manual_marks,
            self.new_pane.manual_marks,
        ))
        if not has_marks:
            QMessageBox.information(self, "尚無標記", "目前沒有可匯出的標記。")
            return
        folder = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾")
        if not folder:
            return
        try:
            old_out = str(Path(folder) / f"{Path(self.old_pane.path).stem}_比對標記.pdf")
            new_out = str(Path(folder) / f"{Path(self.new_pane.path).stem}_比對標記.pdf")
            self._annotated_copy_with_manual(
                self.old_pane.path,
                automatic_old,
                self.old_pane.manual_marks,
                old_out,
            )
            self._annotated_copy_with_manual(
                self.new_pane.path,
                automatic_new,
                self.new_pane.manual_marks,
                new_out,
            )
            QMessageBox.information(
                self, "匯出完成", f"已輸出：\n{old_out}\n{new_out}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "匯出失敗", str(exc))


core.MainWindow = DifferencePageWindow
implementation.main()

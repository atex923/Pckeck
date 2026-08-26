"""Pcheck V0.1.1 - PDF comparison with custom synchronized-page anchors."""
from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent / "PdfCompare_V1.0.0"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import pdf_compare_app_v101 as implementation
from PySide6.QtWidgets import QComboBox, QLabel, QMessageBox, QPushButton, QSpinBox


core = implementation.core
core.APP_NAME = "文檔校對工"
core.VERSION = "V0.1.1"


class HighResolutionPdfPane(core.PdfPane):
    """Render PDF pages at least 2x their logical display resolution."""

    RENDER_QUALITY = 2.0

    def _pixmap(self, page_no: int):
        quality = max(self.RENDER_QUALITY, float(self.devicePixelRatioF()))
        key = (page_no, int(self.zoom * 1000), int(quality * 100))
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        page = self.doc[page_no]
        render_zoom = self.zoom * quality
        pix = page.get_pixmap(
            matrix=core.fitz.Matrix(render_zoom, render_zoom),
            colorspace=core.fitz.csRGB,
            alpha=False,
        )
        image = core.QImage(
            pix.samples, pix.width, pix.height, pix.stride, core.QImage.Format_RGB888
        ).copy()
        result = core.QPixmap.fromImage(image)
        result.setDevicePixelRatio(quality)
        self.cache[key] = result
        while len(self.cache) > 6:
            self.cache.popitem(last=False)
        return result


BaseWindow = core.MainWindow


class PcheckWindow(BaseWindow):
    def __init__(self, old_path="", new_path=""):
        self.page_anchors: list[tuple[int, int]] = []  # zero-based (old, new)
        super().__init__(old_path, new_path)
        self.setWindowTitle("文檔校對工")
        self._build_anchor_controls()
        self._update_page_limits()

    def _build_anchor_controls(self):
        toolbar = self.findChild(core.QToolBar)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("同步頁：舊"))

        self.old_page_spin = QSpinBox()
        self.old_page_spin.setRange(1, max(1, len(self.old_pane.page_sizes)))
        self.old_page_spin.setFixedWidth(70)
        self.old_page_spin.setToolTip("輸入舊檔的顯示頁碼")
        toolbar.addWidget(self.old_page_spin)

        toolbar.addWidget(QLabel("↔ 新"))
        self.new_page_spin = QSpinBox()
        self.new_page_spin.setRange(1, max(1, len(self.new_pane.page_sizes)))
        self.new_page_spin.setFixedWidth(70)
        self.new_page_spin.setToolTip("輸入新檔的顯示頁碼")
        toolbar.addWidget(self.new_page_spin)

        current_button = QPushButton("取目前頁")
        current_button.setToolTip("把左右兩欄目前最上方頁碼帶入")
        current_button.clicked.connect(self.capture_current_pages)
        toolbar.addWidget(current_button)

        add_button = QPushButton("新增／更新")
        add_button.setToolTip("新增這一組同步頁面錨點")
        add_button.clicked.connect(self.add_page_anchor)
        toolbar.addWidget(add_button)

        self.anchor_combo = QComboBox()
        self.anchor_combo.setMinimumWidth(145)
        self.anchor_combo.setToolTip("目前已設定的同步頁面錨點")
        toolbar.addWidget(self.anchor_combo)

        remove_button = QPushButton("移除")
        remove_button.clicked.connect(self.remove_page_anchor)
        toolbar.addWidget(remove_button)

        clear_button = QPushButton("全部清除")
        clear_button.clicked.connect(self.clear_page_anchors)
        toolbar.addWidget(clear_button)

    def open_side(self, side, path):
        super().open_side(side, path)
        if hasattr(self, "old_page_spin"):
            self._update_page_limits()
            self.clear_page_anchors(ask=False)

    def _update_page_limits(self):
        self.old_page_spin.setMaximum(max(1, len(self.old_pane.page_sizes)))
        self.new_page_spin.setMaximum(max(1, len(self.new_pane.page_sizes)))

    def capture_current_pages(self):
        self.old_page_spin.setValue(self.old_pane.current_page() + 1)
        self.new_page_spin.setValue(self.new_pane.current_page() + 1)
        self.status_text.setText(
            f"已帶入目前頁：舊 {self.old_page_spin.value()} ↔ 新 {self.new_page_spin.value()}"
        )

    def add_page_anchor(self):
        if not self.old_pane.doc or not self.new_pane.doc:
            QMessageBox.information(self, "尚未載入", "請先載入舊檔與新檔。")
            return
        old_page = self.old_page_spin.value() - 1
        new_page = self.new_page_spin.value() - 1
        self._add_anchor_values(old_page, new_page, show_message=True)

    def _add_anchor_values(self, old_page: int, new_page: int, show_message=False):
        candidate = [(a, b) for a, b in self.page_anchors if a != old_page and b != new_page]
        candidate.append((old_page, new_page))
        candidate.sort()
        if any(candidate[index][1] >= candidate[index + 1][1] for index in range(len(candidate) - 1)):
            if show_message:
                QMessageBox.warning(
                    self,
                    "頁面順序不成立",
                    "同步錨點必須保持遞增，例如舊 10 ↔ 新 7、舊 28 ↔ 新 10。",
                )
            return False
        self.page_anchors = candidate
        self._refresh_anchor_combo(old_page, new_page)
        self.status_text.setText(
            f"已設定同步頁：舊 {old_page + 1} ↔ 新 {new_page + 1}（共 {len(candidate)} 組）"
        )
        return True

    def _refresh_anchor_combo(self, select_old=None, select_new=None):
        self.anchor_combo.clear()
        selected = 0
        for index, (old_page, new_page) in enumerate(self.page_anchors):
            self.anchor_combo.addItem(
                f"舊 {old_page + 1} ↔ 新 {new_page + 1}", (old_page, new_page)
            )
            if (old_page, new_page) == (select_old, select_new):
                selected = index
        if self.page_anchors:
            self.anchor_combo.setCurrentIndex(selected)
        else:
            self.anchor_combo.addItem("尚未設定")

    def remove_page_anchor(self):
        data = self.anchor_combo.currentData()
        if not data:
            return
        self.page_anchors = [pair for pair in self.page_anchors if pair != tuple(data)]
        self._refresh_anchor_combo()
        self.status_text.setText(f"已移除同步頁面錨點，剩餘 {len(self.page_anchors)} 組")

    def clear_page_anchors(self, _checked=False, ask=True):
        if ask and self.page_anchors:
            answer = QMessageBox.question(self, "清除同步頁", "確定清除所有自設同步頁面嗎？")
            if answer != QMessageBox.Yes:
                return
        self.page_anchors.clear()
        self._refresh_anchor_combo()
        if ask:
            self.status_text.setText("已清除自設同步頁面；同步捲動恢復使用整份文件比例")

    @staticmethod
    def _pane_position(pane) -> float:
        if not pane.page_tops:
            return 0.0
        scroll = float(pane.verticalScrollBar().value())
        page = pane._page_index_at(scroll + 1)
        top = pane.page_tops[page]
        if page + 1 < len(pane.page_tops):
            span = pane.page_tops[page + 1] - top
        else:
            span = pane.page_sizes[page][1] * pane.zoom + core.PAGE_GAP
        fraction = max(0.0, min(0.999, (scroll - top) / max(1.0, span)))
        return page + fraction

    @staticmethod
    def _set_pane_position(pane, position: float):
        if not pane.page_tops:
            return
        position = max(0.0, min(float(len(pane.page_tops) - 1) + 0.999, position))
        page = min(len(pane.page_tops) - 1, int(position))
        fraction = position - page
        top = pane.page_tops[page]
        if page + 1 < len(pane.page_tops):
            span = pane.page_tops[page + 1] - top
        else:
            span = pane.page_sizes[page][1] * pane.zoom + core.PAGE_GAP
        bar = pane.verticalScrollBar()
        bar.blockSignals(True)
        bar.setValue(int(top + fraction * span))
        bar.blockSignals(False)
        pane.viewport().update()

    @staticmethod
    def _map_position(position: float, anchors: list[tuple[int, int]]) -> float:
        if not anchors:
            return position
        if len(anchors) == 1:
            source, target = anchors[0]
            return position + target - source
        if position <= anchors[0][0]:
            source, target = anchors[0]
            return position + target - source
        if position >= anchors[-1][0]:
            source, target = anchors[-1]
            return position + target - source
        for (source_a, target_a), (source_b, target_b) in zip(anchors, anchors[1:]):
            if source_a <= position <= source_b:
                ratio = (position - source_a) / max(1e-9, source_b - source_a)
                return target_a + ratio * (target_b - target_a)
        return position

    def sync_scroll(self, source, ratio):
        if not self.sync_box.isChecked() or self._sync_guard:
            return
        if not self.page_anchors:
            super().sync_scroll(source, ratio)
            return
        self._sync_guard = True
        try:
            if source == "old":
                position = self._pane_position(self.old_pane)
                mapped = self._map_position(position, self.page_anchors)
                self._set_pane_position(self.new_pane, mapped)
            else:
                reverse = sorted((new, old) for old, new in self.page_anchors)
                position = self._pane_position(self.new_pane)
                mapped = self._map_position(position, reverse)
                self._set_pane_position(self.old_pane, mapped)
        finally:
            self._sync_guard = False

    def start_compare(self):
        super().start_compare()
        if self.thread is not None:
            self.thread.finished.connect(self._comparison_thread_finished)

    def _comparison_thread_finished(self):
        self.thread = None
        self.worker = None


core.PdfPane = HighResolutionPdfPane
core.MainWindow = PcheckWindow
implementation.main()

from __future__ import annotations

import argparse
import difflib
import json
import math
import re
import sys
import traceback
import unicodedata
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QDragEnterEvent, QDropEvent, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHeaderView, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QStatusBar, QTableWidget,
    QTableWidgetItem, QToolBar, QVBoxLayout, QWidget, QAbstractScrollArea,
)


APP_NAME = "PDF 文件內容比對器"
VERSION = "1.0.0"
RED = "#e53935"
BLUE = "#1976d2"
PAGE_GAP = 18

HEADING_RE = re.compile(
    r"^\s*(?:第\s*[一二三四五六七八九十百零〇0-9]+\s*[篇章節]|"
    r"[壹貳參肆伍陸柒捌玖拾]+[、.．]|"
    r"\d+(?:[.．-]\d+){0,3}[、.．\s]+\S)"
)


@dataclass(slots=True)
class CharRef:
    char: str
    page: int
    rect: tuple[float, float, float, float]


@dataclass(slots=True)
class Paragraph:
    text: str
    refs: list[CharRef]
    page: int
    display: str


@dataclass(slots=True)
class Section:
    title: str
    key: str
    page: int
    para_start: int
    para_end: int


def clean_char(value: str) -> str:
    if not value or value.isspace():
        return ""
    return unicodedata.normalize("NFKC", value)


def clean_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"[\s　:：、，,。.．·…()（）\[\]【】<>〈〉]+", "", value).lower()


def paragraph_key(value: str) -> str:
    value = clean_title(value)
    value = re.sub(r"\d+", "#", value)
    return value


def page_rawdict(page, use_ocr: bool):
    raw = page.get_text("rawdict")
    char_count = sum(
        len(span.get("chars", []))
        for block in raw.get("blocks", []) if block.get("type") == 0
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    )
    if char_count >= 10 or not use_ocr:
        return raw, False
    try:
        text_page = page.get_textpage_ocr(language="chi_tra+eng", dpi=180, full=True)
        return page.get_text("rawdict", textpage=text_page), True
    except Exception:
        return raw, False


def extract_document(path: str, use_ocr: bool, progress=None, progress_start=0, progress_end=45):
    doc = fitz.open(path)
    paragraphs: list[Paragraph] = []
    ocr_pages = 0
    total_chars = 0
    try:
        for page_no, page in enumerate(doc):
            raw, used_ocr = page_rawdict(page, use_ocr)
            ocr_pages += int(used_ocr)
            for block in raw.get("blocks", []):
                if block.get("type") != 0:
                    continue
                refs: list[CharRef] = []
                shown: list[str] = []
                for line in block.get("lines", []):
                    line_had_text = False
                    for span in line.get("spans", []):
                        for item in span.get("chars", []):
                            original = item.get("c", "")
                            normalized = clean_char(original)
                            shown.append(original)
                            if normalized:
                                bbox = tuple(float(v) for v in item["bbox"])
                                for normalized_char in normalized:
                                    refs.append(CharRef(normalized_char, page_no, bbox))
                                line_had_text = True
                    if line_had_text:
                        shown.append("\n")
                text = "".join(ref.char for ref in refs)
                display = "".join(shown).strip().replace("\n", " ")
                if text:
                    paragraphs.append(Paragraph(text, refs, page_no, display))
                    total_chars += len(text)
            if progress and (page_no % 4 == 0 or page_no + 1 == len(doc)):
                ratio = (page_no + 1) / max(1, len(doc))
                progress(int(progress_start + ratio * (progress_end - progress_start)), f"抽取文字：{Path(path).name} 第 {page_no + 1}/{len(doc)} 頁")
        return paragraphs, len(doc), total_chars, ocr_pages
    finally:
        doc.close()


def detect_sections(paragraphs: list[Paragraph], page_count: int) -> list[Section]:
    candidates: list[tuple[str, str, int, int]] = []
    for index, para in enumerate(paragraphs):
        title = para.display.strip()
        if 2 <= len(title) <= 90 and HEADING_RE.match(title):
            key = clean_title(title)
            candidates.append((title, key, para.page, index))

    # 目錄和正文常有同名標題。每個標題採最後一次出現，通常即正文起頁。
    chosen: dict[str, tuple[str, str, int, int]] = {}
    for item in candidates:
        chosen[item[1]] = item
    ordered = sorted(chosen.values(), key=lambda item: (item[2], item[3]))

    if not ordered:
        return [Section("全文", "全文", 0, 0, len(paragraphs))]

    sections: list[Section] = []
    if ordered[0][3] > 0:
        sections.append(Section("前置頁面", "前置頁面", 0, 0, ordered[0][3]))
    for pos, (title, key, page, para_index) in enumerate(ordered):
        end = ordered[pos + 1][3] if pos + 1 < len(ordered) else len(paragraphs)
        sections.append(Section(title, key, page, para_index, end))
    return sections


def match_sections(old: list[Section], new: list[Section]):
    old_keys = [s.key for s in old]
    new_keys = [s.key for s in new]
    matcher = difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    pairs: list[tuple[Section | None, Section | None]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs.extend(zip(old[i1:i2], new[j1:j2]))
            continue
        left = old[i1:i2]
        right = new[j1:j2]
        used_right: set[int] = set()
        for left_section in left:
            best_index = -1
            best_ratio = 0.0
            for idx, right_section in enumerate(right):
                if idx in used_right:
                    continue
                ratio = difflib.SequenceMatcher(None, left_section.key, right_section.key).ratio()
                if ratio > best_ratio:
                    best_index, best_ratio = idx, ratio
            if best_index >= 0 and best_ratio >= 0.58:
                used_right.add(best_index)
                pairs.append((left_section, right[best_index]))
            else:
                pairs.append((left_section, None))
        for idx, right_section in enumerate(right):
            if idx not in used_right:
                pairs.append((None, right_section))
    return pairs


def merge_refs(refs: Iterable[CharRef]) -> list[tuple[int, tuple[float, float, float, float]]]:
    result: list[tuple[int, tuple[float, float, float, float]]] = []
    current_page = -1
    current = None
    for ref in refs:
        x0, y0, x1, y1 = ref.rect
        if current is not None:
            cx0, cy0, cx1, cy1 = current
            same_line = ref.page == current_page and abs(y1 - cy1) <= max(2.2, (cy1 - cy0) * 0.35)
            close = x0 <= cx1 + max(4.0, (cy1 - cy0) * 0.7)
            if same_line and close:
                current = (min(cx0, x0), min(cy0, y0), max(cx1, x1), max(cy1, y1))
                continue
            result.append((current_page, current))
        current_page = ref.page
        current = (x0, y0, x1, y1)
    if current is not None:
        result.append((current_page, current))
    return result


def append_marks(target, refs: Iterable[CharRef], color: str):
    for page, rect in merge_refs(refs):
        target[page].append((rect, color))


def compare_text_refs(old_refs: list[CharRef], new_refs: list[CharRef], old_marks, new_marks):
    old_text = "".join(item.char for item in old_refs)
    new_text = "".join(item.char for item in new_refs)
    matcher = difflib.SequenceMatcher(None, old_text, new_text, autojunk=True)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("delete", "replace"):
            append_marks(old_marks, old_refs[i1:i2], RED)
        if tag == "replace":
            append_marks(new_marks, new_refs[j1:j2], RED)
        elif tag == "insert":
            append_marks(new_marks, new_refs[j1:j2], BLUE)


def section_refs(paragraphs: list[Paragraph], section: Section) -> list[CharRef]:
    return [ref for para in paragraphs[section.para_start:section.para_end] for ref in para.refs]


def compare_section_paragraphs(old_paras, new_paras, old_section, new_section, old_marks, new_marks):
    left = old_paras[old_section.para_start:old_section.para_end]
    right = new_paras[new_section.para_start:new_section.para_end]
    left_keys = [paragraph_key(p.text) for p in left]
    right_keys = [paragraph_key(p.text) for p in right]
    matcher = difflib.SequenceMatcher(None, left_keys, right_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_refs = [ref for para in left[i1:i2] for ref in para.refs]
        new_refs = [ref for para in right[j1:j2] for ref in para.refs]
        if tag == "delete":
            append_marks(old_marks, old_refs, RED)
        elif tag == "insert":
            append_marks(new_marks, new_refs, BLUE)
        else:
            compare_text_refs(old_refs, new_refs, old_marks, new_marks)


def run_comparison(old_path: str, new_path: str, use_ocr=True, progress=None):
    progress = progress or (lambda *_: None)
    old_paras, old_pages, old_chars, old_ocr = extract_document(old_path, use_ocr, progress, 0, 42)
    new_paras, new_pages, new_chars, new_ocr = extract_document(new_path, use_ocr, progress, 42, 78)
    progress(80, "分析篇章節起始頁")
    old_sections = detect_sections(old_paras, old_pages)
    new_sections = detect_sections(new_paras, new_pages)
    pairs = match_sections(old_sections, new_sections)
    old_marks = defaultdict(list)
    new_marks = defaultdict(list)

    for index, (old_section, new_section) in enumerate(pairs):
        progress(80 + int(19 * (index + 1) / max(1, len(pairs))), f"比對段落：{index + 1}/{len(pairs)}")
        if old_section and new_section:
            compare_section_paragraphs(old_paras, new_paras, old_section, new_section, old_marks, new_marks)
        elif old_section:
            append_marks(old_marks, section_refs(old_paras, old_section), RED)
        elif new_section:
            append_marks(new_marks, section_refs(new_paras, new_section), BLUE)

    chapter_rows = [{
        "title": (new_section or old_section).title,
        "old_page": old_section.page if old_section else None,
        "new_page": new_section.page if new_section else None,
    } for old_section, new_section in pairs]
    progress(100, "比對完成")
    return {
        "old_marks": dict(old_marks), "new_marks": dict(new_marks),
        "chapters": chapter_rows,
        "stats": {
            "old_pages": old_pages, "new_pages": new_pages,
            "old_chars": old_chars, "new_chars": new_chars,
            "old_ocr_pages": old_ocr, "new_ocr_pages": new_ocr,
            "old_mark_lines": sum(map(len, old_marks.values())),
            "new_mark_lines": sum(map(len, new_marks.values())),
        },
    }


class CompareWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, old_path, new_path, use_ocr):
        super().__init__()
        self.old_path = old_path
        self.new_path = new_path
        self.use_ocr = use_ocr

    def run(self):
        try:
            result = run_comparison(self.old_path, self.new_path, self.use_ocr, self.progress.emit)
            self.finished.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class PdfPane(QAbstractScrollArea):
    fileDropped = Signal(str)
    scrollRatioChanged = Signal(float)

    def __init__(self, role: str):
        super().__init__()
        self.role = role
        self.path = ""
        self.doc = None
        self.zoom = 1.0
        self.page_sizes: list[tuple[float, float]] = []
        self.page_tops: list[float] = []
        self.cache: OrderedDict[tuple[int, int], QPixmap] = OrderedDict()
        self.marks = {}
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("background:#303238; border:0;")
        self.verticalScrollBar().valueChanged.connect(self._scroll_changed)

    def close_document(self):
        if self.doc:
            self.doc.close()
        self.doc = None
        self.cache.clear()

    def load_pdf(self, path: str):
        self.close_document()
        self.doc = fitz.open(path)
        self.path = path
        self.page_sizes = [(float(page.rect.width), float(page.rect.height)) for page in self.doc]
        self.zoom = self.fit_width_zoom()
        self.marks = {}
        self._rebuild_layout()
        self.viewport().update()

    def fit_width_zoom(self):
        if not self.page_sizes:
            return 1.0
        widest = max(width for width, _ in self.page_sizes)
        return max(0.2, (max(200, self.viewport().width()) - 34) / widest)

    def _rebuild_layout(self):
        self.page_tops = []
        y = PAGE_GAP
        for _, height in self.page_sizes:
            self.page_tops.append(y)
            y += height * self.zoom + PAGE_GAP
        self.verticalScrollBar().setRange(0, max(0, int(y - self.viewport().height())))
        self.verticalScrollBar().setPageStep(self.viewport().height())
        self.horizontalScrollBar().setRange(0, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild_layout()

    def set_marks(self, marks):
        self.marks = marks or {}
        self.viewport().update()

    def set_zoom(self, value: float):
        if not self.doc:
            return
        old_total = max(1, self.verticalScrollBar().maximum())
        ratio = self.verticalScrollBar().value() / old_total
        self.zoom = max(0.2, min(4.0, value))
        self.cache.clear()
        self._rebuild_layout()
        self.verticalScrollBar().setValue(int(ratio * self.verticalScrollBar().maximum()))
        self.viewport().update()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            self.set_zoom(self.zoom * (1.12 if delta > 0 else 1 / 1.12))
            event.accept()
            return
        delta = event.pixelDelta().y() or event.angleDelta().y() / 3
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta))
        event.accept()

    def dragEnterEvent(self, event: QDragEnterEvent):
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith(".pdf"):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        path = event.mimeData().urls()[0].toLocalFile()
        self.fileDropped.emit(path)
        event.acceptProposedAction()

    def _page_index_at(self, document_y: float):
        if not self.page_tops:
            return 0
        low, high = 0, len(self.page_tops) - 1
        while low <= high:
            mid = (low + high) // 2
            if self.page_tops[mid] <= document_y:
                low = mid + 1
            else:
                high = mid - 1
        return max(0, min(len(self.page_tops) - 1, high))

    def current_page(self):
        return self._page_index_at(self.verticalScrollBar().value() + 5)

    def goto_page(self, page: int):
        if not self.page_tops:
            return
        page = max(0, min(page, len(self.page_tops) - 1))
        self.verticalScrollBar().setValue(int(self.page_tops[page]))

    def set_scroll_ratio(self, ratio: float):
        self.verticalScrollBar().blockSignals(True)
        self.verticalScrollBar().setValue(int(max(0.0, min(1.0, ratio)) * self.verticalScrollBar().maximum()))
        self.verticalScrollBar().blockSignals(False)
        self.viewport().update()

    def _scroll_changed(self):
        maximum = self.verticalScrollBar().maximum()
        self.scrollRatioChanged.emit(self.verticalScrollBar().value() / maximum if maximum else 0.0)
        self.viewport().update()

    def _pixmap(self, page_no: int):
        key = (page_no, int(self.zoom * 1000))
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        page = self.doc[page_no]
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), colorspace=fitz.csRGB, alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        result = QPixmap.fromImage(image)
        self.cache[key] = result
        while len(self.cache) > 8:
            self.cache.popitem(last=False)
        return result

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), QColor("#303238"))
        if not self.doc:
            painter.setPen(QColor("#d8dbe2"))
            painter.drawText(self.viewport().rect(), Qt.AlignCenter, f"拖曳 PDF 到{self.role}欄\n或使用上方開啟按鈕")
            return
        scroll_y = self.verticalScrollBar().value()
        top_page = self._page_index_at(scroll_y)
        for page_no in range(top_page, len(self.page_sizes)):
            width, height = self.page_sizes[page_no]
            draw_w, draw_h = width * self.zoom, height * self.zoom
            draw_y = self.page_tops[page_no] - scroll_y
            if draw_y > self.viewport().height():
                break
            if draw_y + draw_h < 0:
                continue
            draw_x = max(PAGE_GAP / 2, (self.viewport().width() - draw_w) / 2)
            painter.drawPixmap(QPoint(int(draw_x), int(draw_y)), self._pixmap(page_no))
            for rect, color in self.marks.get(page_no, []):
                x0, y0, x1, y1 = rect
                pen = QPen(QColor(color))
                pen.setWidthF(1.5)
                painter.setPen(pen)
                underline_y = draw_y + (y1 - 0.8) * self.zoom
                painter.drawLine(QPoint(int(draw_x + x0 * self.zoom), int(underline_y)), QPoint(int(draw_x + x1 * self.zoom), int(underline_y)))
            painter.setPen(QColor("#b8bbc2"))
            painter.drawText(QRectF(draw_x, draw_y + draw_h + 1, draw_w, PAGE_GAP - 2), Qt.AlignCenter, str(page_no + 1))


class MainWindow(QMainWindow):
    def __init__(self, old_path="", new_path=""):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.resize(1500, 920)
        self.result = None
        self.thread = None
        self.worker = None
        self._sync_guard = False
        self._build_ui()
        if old_path:
            self.open_side("old", old_path)
        if new_path:
            self.open_side("new", new_path)

    def _build_ui(self):
        toolbar = QToolBar("工具")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        old_action = QAction("開啟舊檔", self)
        new_action = QAction("開啟新檔", self)
        compare_action = QAction("開始比對", self)
        export_action = QAction("匯出標記 PDF", self)
        old_action.triggered.connect(lambda: self.choose_pdf("old"))
        new_action.triggered.connect(lambda: self.choose_pdf("new"))
        compare_action.triggered.connect(self.start_compare)
        export_action.triggered.connect(self.export_pdfs)
        toolbar.addActions([old_action, new_action, compare_action, export_action])
        toolbar.addSeparator()
        self.sync_box = QCheckBox("同步捲動")
        self.sync_box.setChecked(True)
        self.ocr_box = QCheckBox("掃描頁自動 OCR")
        self.ocr_box.setChecked(True)
        toolbar.addWidget(self.sync_box)
        toolbar.addWidget(self.ocr_box)
        toolbar.addSeparator()
        legend = QLabel(f"<span style='color:{RED};font-weight:700'>━━ 修改／刪除</span>　<span style='color:{BLUE};font-weight:700'>━━ 新增</span>")
        toolbar.addWidget(legend)

        self.old_pane = PdfPane("左側舊檔")
        self.new_pane = PdfPane("右側新檔")
        self.old_pane.fileDropped.connect(lambda path: self.open_side("old", path))
        self.new_pane.fileDropped.connect(lambda path: self.open_side("new", path))
        self.old_pane.scrollRatioChanged.connect(lambda ratio: self.sync_scroll("old", ratio))
        self.new_pane.scrollRatioChanged.connect(lambda ratio: self.sync_scroll("new", ratio))
        pdf_splitter = QSplitter(Qt.Horizontal)
        pdf_splitter.addWidget(self.old_pane)
        pdf_splitter.addWidget(self.new_pane)
        pdf_splitter.setSizes([750, 750])

        self.chapter_table = QTableWidget(0, 3)
        self.chapter_table.setHorizontalHeaderLabels(["篇章節", "舊檔起始頁", "新檔起始頁"])
        self.chapter_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.chapter_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.chapter_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.chapter_table.setMaximumWidth(360)
        self.chapter_table.cellDoubleClicked.connect(self.jump_chapter)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(self.chapter_table)
        main_splitter.addWidget(pdf_splitter)
        main_splitter.setSizes([300, 1200])
        self.setCentralWidget(main_splitter)

        status = QStatusBar()
        self.status_text = QLabel("請將舊 PDF 拖到左欄、新 PDF 拖到右欄")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(220)
        self.progress.hide()
        status.addWidget(self.status_text, 1)
        status.addPermanentWidget(self.progress)
        self.setStatusBar(status)

    def choose_pdf(self, side):
        path, _ = QFileDialog.getOpenFileName(self, "選擇 PDF", "", "PDF 文件 (*.pdf)")
        if path:
            self.open_side(side, path)

    def open_side(self, side, path):
        try:
            pane = self.old_pane if side == "old" else self.new_pane
            pane.load_pdf(path)
            self.result = None
            self.old_pane.set_marks({})
            self.new_pane.set_marks({})
            self.chapter_table.setRowCount(0)
            self.status_text.setText(f"已載入{pane.role}：{Path(path).name}")
        except Exception as exc:
            QMessageBox.critical(self, "無法開啟 PDF", str(exc))

    def sync_scroll(self, source, ratio):
        if not self.sync_box.isChecked() or self._sync_guard:
            return
        self._sync_guard = True
        try:
            (self.new_pane if source == "old" else self.old_pane).set_scroll_ratio(ratio)
        finally:
            self._sync_guard = False

    def start_compare(self):
        if not self.old_pane.path or not self.new_pane.path:
            QMessageBox.information(self, "尚未載入", "請先載入左側舊檔與右側新檔。")
            return
        if self.thread and self.thread.isRunning():
            return
        self.progress.show()
        self.progress.setValue(0)
        self.thread = QThread(self)
        self.worker = CompareWorker(self.old_pane.path, self.new_pane.path, self.ocr_box.isChecked())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def on_progress(self, value, text):
        self.progress.setValue(value)
        self.status_text.setText(text)

    def on_finished(self, result):
        self.result = result
        self.old_pane.set_marks(result["old_marks"])
        self.new_pane.set_marks(result["new_marks"])
        self.chapter_table.setRowCount(len(result["chapters"]))
        for row, chapter in enumerate(result["chapters"]):
            self.chapter_table.setItem(row, 0, QTableWidgetItem(chapter["title"]))
            self.chapter_table.setItem(row, 1, QTableWidgetItem("-" if chapter["old_page"] is None else str(chapter["old_page"] + 1)))
            self.chapter_table.setItem(row, 2, QTableWidgetItem("-" if chapter["new_page"] is None else str(chapter["new_page"] + 1)))
            self.chapter_table.item(row, 0).setData(Qt.UserRole, chapter)
        stats = result["stats"]
        self.status_text.setText(f"完成：舊檔 {stats['old_pages']} 頁／{stats['old_mark_lines']} 條標線；新檔 {stats['new_pages']} 頁／{stats['new_mark_lines']} 條標線")
        self.progress.hide()

    def on_failed(self, details):
        self.progress.hide()
        self.status_text.setText("比對失敗")
        QMessageBox.critical(self, "比對失敗", details)

    def jump_chapter(self, row, _column):
        item = self.chapter_table.item(row, 0)
        if not item:
            return
        chapter = item.data(Qt.UserRole)
        if chapter["old_page"] is not None:
            self.old_pane.goto_page(chapter["old_page"])
        if chapter["new_page"] is not None:
            self.new_pane.goto_page(chapter["new_page"])

    @staticmethod
    def _annotated_copy(source, marks, output):
        doc = fitz.open(source)
        try:
            for page_no, page_marks in marks.items():
                page = doc[int(page_no)]
                for rect, color in page_marks:
                    x0, _y0, x1, y1 = rect
                    annot = page.add_line_annot((x0, y1 - 0.8), (x1, y1 - 0.8))
                    rgb = (0.9, 0.12, 0.12) if color == RED else (0.05, 0.35, 0.88)
                    annot.set_colors(stroke=rgb)
                    annot.set_border(width=1.5)
                    annot.update()
            doc.save(output, garbage=3, deflate=True)
        finally:
            doc.close()

    def export_pdfs(self):
        if not self.result:
            QMessageBox.information(self, "尚無結果", "請先執行比對。")
            return
        folder = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾")
        if not folder:
            return
        try:
            old_out = str(Path(folder) / f"{Path(self.old_pane.path).stem}_比對標記.pdf")
            new_out = str(Path(folder) / f"{Path(self.new_pane.path).stem}_比對標記.pdf")
            self._annotated_copy(self.old_pane.path, self.result["old_marks"], old_out)
            self._annotated_copy(self.new_pane.path, self.result["new_marks"], new_out)
            QMessageBox.information(self, "匯出完成", f"已輸出：\n{old_out}\n{new_out}")
        except Exception as exc:
            QMessageBox.critical(self, "匯出失敗", str(exc))

    def closeEvent(self, event):
        self.old_pane.close_document()
        self.new_pane.close_document()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("old", nargs="?", default="")
    parser.add_argument("new", nargs="?", default="")
    parser.add_argument("--analyze", action="store_true", help="無介面執行並輸出 JSON 統計")
    parser.add_argument("--no-ocr", action="store_true")
    args = parser.parse_args()
    if args.analyze:
        if not args.old or not args.new:
            parser.error("--analyze 需要舊檔與新檔路徑")
        result = run_comparison(args.old, args.new, not args.no_ocr, lambda value, text: print(f"[{value:3d}%] {text}", file=sys.stderr))
        print(json.dumps({"chapters": result["chapters"], "stats": result["stats"]}, ensure_ascii=False, indent=2))
        return
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow(args.old, args.new)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

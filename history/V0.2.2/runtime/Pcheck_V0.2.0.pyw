"""Pcheck V0.2.0 - persistent, self-contained PDF comparison libraries."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PREVIOUS_VERSION = ROOT / "Pcheck_V0.1.1.pyw"


def load_previous_runtime():
    """Load V0.1.1 definitions without executing its final GUI main call."""
    tree = ast.parse(PREVIOUS_VERSION.read_text(encoding="utf-8"), filename=str(PREVIOUS_VERSION))
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        call = tree.body[-1].value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "main":
            tree.body.pop()
    namespace = {"__name__": "_pcheck_v011_runtime", "__file__": str(PREVIOUS_VERSION)}
    exec(compile(tree, str(PREVIOUS_VERSION), "exec"), namespace)
    return namespace


previous = load_previous_runtime()
core = previous["core"]
implementation = previous["implementation"]
AnchoredWindow = previous["PcheckWindow"]

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMessageBox, QToolBar


APP_VERSION = "V0.2.0"
SCHEMA_VERSION = 1
DEFAULT_LIBRARY_NAME = "PCdb.fck"
core.VERSION = APP_VERSION


def encode_result(result):
    if result is None:
        return None
    return result


def decode_result(result):
    if not result:
        return None
    restored = dict(result)
    for side in ("old_marks", "new_marks"):
        restored[side] = {
            int(page): [(tuple(rect), color) for rect, color in marks]
            for page, marks in result.get(side, {}).items()
        }
    return restored


class LibraryWindow(AnchoredWindow):
    def __init__(self, old_path="", new_path=""):
        self.library_path: Path | None = None
        self.library_temp: tempfile.TemporaryDirectory | None = None
        self._loading_library = False
        self._closing_after_save = False
        super().__init__(old_path, new_path)
        self.setWindowTitle("文檔校對工")
        self._build_library_toolbar()

    def _build_library_toolbar(self):
        toolbar = QToolBar("比對庫")
        toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        open_action = QAction("開啟比對庫", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.choose_open_library)

        save_action = QAction("儲存比對庫", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_library)

        save_as_action = QAction("比對庫另存", self)
        save_as_action.setShortcut(QKeySequence.SaveAs)
        save_as_action.triggered.connect(self.save_library_as)

        toolbar.addActions([open_action, save_action, save_as_action])
        toolbar.addSeparator()
        self.library_label = core.QLabel(f"比對庫：尚未建立（預設 {DEFAULT_LIBRARY_NAME}）")
        toolbar.addWidget(self.library_label)

    def _settings_snapshot(self):
        return {
            "sync_enabled": self.sync_box.isChecked(),
            "ocr_enabled": self.ocr_box.isChecked(),
            "old_zoom": self.old_pane.zoom,
            "new_zoom": self.new_pane.zoom,
            "old_position": self._pane_position(self.old_pane),
            "new_position": self._pane_position(self.new_pane),
            "anchors": [[old, new] for old, new in self.page_anchors],
            "window_width": self.width(),
            "window_height": self.height(),
        }

    def _document_payload(self, role: str, pane):
        if not pane.path:
            return None
        path = Path(pane.path)
        data = path.read_bytes()
        return {
            "role": role,
            "filename": path.name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "data": data,
        }

    def save_library_to(self, path: str | Path, show_message=True):
        if not self.old_pane.path or not self.new_pane.path:
            if show_message:
                QMessageBox.information(self, "尚未載入", "請先載入舊檔與新檔，再建立比對庫。")
            return False

        target = Path(path)
        if target.suffix.lower() != ".fck":
            target = target.with_suffix(".fck")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        if temporary.exists():
            temporary.unlink()

        old_document = self._document_payload("old", self.old_pane)
        new_document = self._document_payload("new", self.new_pane)
        settings_json = json.dumps(self._settings_snapshot(), ensure_ascii=False)
        result_json = json.dumps(encode_result(self.result), ensure_ascii=False) if self.result else ""

        try:
            connection = sqlite3.connect(temporary)
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE library_info (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        schema_version INTEGER NOT NULL,
                        app_version TEXT NOT NULL,
                        saved_at TEXT NOT NULL,
                        settings_json TEXT NOT NULL,
                        result_json TEXT NOT NULL
                    );
                    CREATE TABLE documents (
                        role TEXT PRIMARY KEY CHECK (role IN ('old', 'new')),
                        filename TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        pdf_data BLOB NOT NULL
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO library_info VALUES (1, ?, ?, ?, ?, ?)",
                    (SCHEMA_VERSION, APP_VERSION, datetime.now().isoformat(timespec="seconds"), settings_json, result_json),
                )
                for document in (old_document, new_document):
                    connection.execute(
                        "INSERT INTO documents(role, filename, sha256, pdf_data) VALUES (?, ?, ?, ?)",
                        (document["role"], document["filename"], document["sha256"], sqlite3.Binary(document["data"])),
                    )
            connection.close()
            os.replace(temporary, target)
            self.library_path = target
            self.library_label.setText(f"比對庫：{target.name}")
            self.status_text.setText(f"比對庫已儲存：{target}")
            if show_message:
                QMessageBox.information(
                    self,
                    "儲存完成",
                    f"已儲存自足式比對庫：\n{target}\n\n左右 PDF、設定、同步頁與分析結果均已寫入。",
                )
            return True
        except Exception as exc:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
            if show_message:
                QMessageBox.critical(self, "儲存比對庫失敗", str(exc))
            return False

    def save_library(self):
        if self.library_path is None:
            return self.save_library_as()
        return self.save_library_to(self.library_path)

    def save_library_as(self):
        initial = str((self.library_path.parent if self.library_path else ROOT) / DEFAULT_LIBRARY_NAME)
        path, _ = QFileDialog.getSaveFileName(
            self, "比對庫另存", initial, "Pcheck 比對庫 (*.fck)"
        )
        if not path:
            return False
        return self.save_library_to(path)

    def choose_open_library(self):
        initial = str(self.library_path.parent if self.library_path else ROOT)
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟比對庫", initial, "Pcheck 比對庫 (*.fck)"
        )
        if path:
            self.open_library(path)

    @staticmethod
    def _read_library(path: Path):
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            info = connection.execute(
                "SELECT schema_version, app_version, saved_at, settings_json, result_json FROM library_info WHERE id=1"
            ).fetchone()
            if not info:
                raise ValueError("找不到比對庫主資料。")
            if int(info[0]) > SCHEMA_VERSION:
                raise ValueError(f"此比對庫版本較新（schema {info[0]}），目前程式無法開啟。")
            documents = connection.execute(
                "SELECT role, filename, sha256, pdf_data FROM documents ORDER BY role"
            ).fetchall()
            if {row[0] for row in documents} != {"old", "new"}:
                raise ValueError("比對庫必須同時包含舊檔與新檔。")
            for role, filename, expected_hash, data in documents:
                if hashlib.sha256(data).hexdigest() != expected_hash:
                    raise ValueError(f"{role} PDF 資料校驗失敗：{filename}")
            return {
                "schema": info[0], "app_version": info[1], "saved_at": info[2],
                "settings": json.loads(info[3]),
                "result": decode_result(json.loads(info[4])) if info[4] else None,
                "documents": documents,
            }
        finally:
            connection.close()

    def open_library(self, path: str | Path, show_message=True):
        source = Path(path)
        try:
            payload = self._read_library(source)
            new_temp = tempfile.TemporaryDirectory(prefix="pcheck_library_")
            extracted = {}
            for role, filename, _sha256, data in payload["documents"]:
                safe_name = Path(filename).name or f"{role}.pdf"
                output = Path(new_temp.name) / f"{role}_{safe_name}"
                output.write_bytes(data)
                extracted[role] = output

            old_temp = self.library_temp
            self._loading_library = True
            try:
                self.open_side("old", str(extracted["old"]))
                self.open_side("new", str(extracted["new"]))
                settings = payload["settings"]
                self.sync_box.setChecked(bool(settings.get("sync_enabled", True)))
                self.ocr_box.setChecked(bool(settings.get("ocr_enabled", True)))
                self.old_pane.set_zoom(float(settings.get("old_zoom", self.old_pane.zoom)))
                self.new_pane.set_zoom(float(settings.get("new_zoom", self.new_pane.zoom)))
                self.page_anchors = [tuple(map(int, pair)) for pair in settings.get("anchors", [])]
                self._refresh_anchor_combo()
                self._set_pane_position(self.old_pane, float(settings.get("old_position", 0.0)))
                self._set_pane_position(self.new_pane, float(settings.get("new_position", 0.0)))
                width = max(900, int(settings.get("window_width", self.width())))
                height = max(600, int(settings.get("window_height", self.height())))
                self.resize(width, height)
                if payload["result"]:
                    super().on_finished(payload["result"])
                else:
                    self.result = None
                    self.old_pane.set_marks({})
                    self.new_pane.set_marks({})
                    self.chapter_table.setRowCount(0)
            finally:
                self._loading_library = False

            self.library_temp = new_temp
            if old_temp:
                old_temp.cleanup()
            self.library_path = source
            self.library_label.setText(f"比對庫：{source.name}")
            result_text = "，已載入分析結果" if payload["result"] else "，尚無分析結果"
            self.status_text.setText(f"已開啟比對庫：{source.name}{result_text}")
            if show_message:
                QMessageBox.information(
                    self,
                    "比對庫已開啟",
                    f"已還原左右 PDF、同步頁、顯示設定{result_text}。",
                )
            return True
        except Exception as exc:
            if show_message:
                QMessageBox.critical(self, "開啟比對庫失敗", str(exc))
            return False

    def on_finished(self, result):
        super().on_finished(result)
        if self.library_path and not self._loading_library:
            self.save_library_to(self.library_path, show_message=False)

    def closeEvent(self, event):
        if self._closing_after_save:
            super().closeEvent(event)
            return
        if self.library_path:
            if not self.save_library_to(self.library_path, show_message=False):
                answer = QMessageBox.question(
                    self, "自動儲存失敗", "比對庫自動儲存失敗，仍要關閉程式嗎？"
                )
                if answer != QMessageBox.Yes:
                    event.ignore()
                    return
        elif self.old_pane.path or self.new_pane.path:
            answer = QMessageBox.question(
                self,
                "儲存比對庫",
                f"是否先將目前工作儲存為 {DEFAULT_LIBRARY_NAME}？",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.Yes and not self.save_library_as():
                event.ignore()
                return
        self._closing_after_save = True
        super().closeEvent(event)
        if self.library_temp:
            self.library_temp.cleanup()
            self.library_temp = None


core.MainWindow = LibraryWindow
implementation.main()

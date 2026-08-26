"""V1.0.1 refinements layered on the V1.0.0 implementation."""
from __future__ import annotations

import re
import sys

import pdf_compare_app as core


core.VERSION = "1.0.1"
core.HEADING_RE = re.compile(r"^\s*第\s*[一二三四五六七八九十百零〇0-9]+\s*[篇章節]")


def detect_sections(paragraphs: list[core.Paragraph], page_count: int) -> list[core.Section]:
    candidates: list[tuple[str, str, int, int]] = []
    for index, para in enumerate(paragraphs):
        title = para.display.strip()
        if not 2 <= len(title) <= 90:
            continue
        match = core.HEADING_RE.match(title)
        if not match:
            continue
        # 目錄行常在標題後接點線和頁碼；去掉行尾頁碼後即可與正文標題去重。
        without_page_number = re.sub(r"[\s.．…·-]*\d+\s*$", "", title)
        key = core.clean_title(without_page_number)
        candidates.append((title, key, para.page, index))

    # 同名項目最後一次出現處通常是正文，而不是前方目錄。
    chosen: dict[str, tuple[str, str, int, int]] = {}
    for item in candidates:
        chosen[item[1]] = item
    ordered = sorted(chosen.values(), key=lambda item: (item[2], item[3]))
    if not ordered:
        return [core.Section("全文", "全文", 0, 0, len(paragraphs))]

    sections: list[core.Section] = []
    if ordered[0][3] > 0:
        sections.append(core.Section("前置頁面", "前置頁面", 0, 0, ordered[0][3]))
    for pos, (title, key, page, para_index) in enumerate(ordered):
        end = ordered[pos + 1][3] if pos + 1 < len(ordered) else len(paragraphs)
        sections.append(core.Section(title, key, page, para_index, end))
    return sections


core.detect_sections = detect_sections


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    core.main()


if __name__ == "__main__":
    main()

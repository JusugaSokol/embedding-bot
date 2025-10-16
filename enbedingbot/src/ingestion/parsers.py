from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from docx import Document


def read_text_file(path: Path, encodings: Iterable[str] = ("utf-8", "utf-8-sig", "cp1251")) -> str:
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="latin-1", errors="ignore")


def extract_docx_text(path: Path) -> str:
    document = Document(str(path))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    return "\n".join(paragraphs)


def extract_csv_text(path: Path) -> str:
    lines: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.reader(csv_file)
        for row in reader:
            if not row:
                continue
            lines.append(" ".join(value.strip() for value in row if value.strip()))
    if lines:
        return "\n".join(lines)
    # Fallback to raw read to preserve content if CSV parsing fails silently.
    return read_text_file(path)


def extract_plain_text(path: Path) -> str:
    return read_text_file(path)


def extract_markdown_text(path: Path) -> str:
    return read_text_file(path)


def extract_text(path: Path) -> str:
    extension = path.suffix.lower()
    if extension == ".docx":
        return extract_docx_text(path)
    if extension == ".csv":
        return extract_csv_text(path)
    if extension in (".txt", ".md"):
        return read_text_file(path)
    raise ValueError(f"Unsupported file extension: {extension}")

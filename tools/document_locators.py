"""Locators shared by document captures and the citation checker."""
import re

SHEET_CELL = r"(?:[\w.]+|'(?:[^'\r\n]|'')+')![A-Z]{1,3}[1-9]\d*"
PARAGRAPH = r"¶\s*\d+"
DOCUMENT = rf"(?:p\.\s*\d+|slide \d+|sheet \d+ row \d+|{SHEET_CELL})"
BLOCK = re.compile(rf"^\*\*\[({DOCUMENT})\]\*\*(?:[ \t]+(.*))?$")


def normalize(label):
    if re.fullmatch(PARAGRAPH, label):
        return "¶" + label[1:].strip()
    if re.fullmatch(r"p\.\s*\d+", label):
        return "p. " + label[2:].strip()
    return label


def cell(sheet, coordinate):
    escaped = sheet.replace("'", "''")
    name = sheet if re.fullmatch(r"[\w.]+", sheet) else f"'{escaped}'"
    return f"{name}!{coordinate}"

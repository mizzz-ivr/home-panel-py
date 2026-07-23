import csv
from collections.abc import Iterable
from io import StringIO

from app.models.time_entry import TimeEntry

UTF8_BOM = "\ufeff"
CSV_HEADERS = ("日付", "カテゴリ", "時間（分）", "メモ", "登録日時")
FORMULA_PREFIXES = ("=", "+", "-", "@")
CONTROL_PREFIXES = ("\t", "\r", "\n")


def sanitize_csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith(CONTROL_PREFIXES) or text.lstrip().startswith(FORMULA_PREFIXES):
        return f"'{text}"
    return text


def build_time_entries_csv(entries: Iterable[TimeEntry]) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(CSV_HEADERS)

    for entry in entries:
        writer.writerow(
            (
                entry.entry_date.isoformat(),
                sanitize_csv_cell(entry.category),
                entry.minutes,
                sanitize_csv_cell(entry.note),
                entry.created_at.isoformat(sep=" ", timespec="seconds"),
            )
        )

    return UTF8_BOM + output.getvalue()

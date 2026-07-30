from __future__ import annotations

import csv
from datetime import date
from io import StringIO
from typing import Any

from fastapi import status
from fastapi.responses import Response

from app.csv_export import UTF8_BOM, sanitize_csv_cell
from app.habit_schedule import WEEKDAY_LABELS

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
CSV_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def safe_csv_value(value: object) -> object:
    if isinstance(value, str):
        return sanitize_csv_cell(value)
    return value


def write_safe_row(writer: Any, values: tuple[object, ...]) -> None:
    writer.writerow(tuple(safe_csv_value(value) for value in values))


def build_habit_report_csv(
    report_type: str,
    period_start: date,
    period_end: date,
    report: dict[str, Any],
) -> str:
    if report_type not in {"週次", "月次"}:
        raise ValueError("レポート種別は週次または月次である必要があります。")

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")

    write_safe_row(writer, ("レポート種別", f"習慣{report_type}レポート"))
    write_safe_row(writer, ("対象期間", period_start.isoformat(), period_end.isoformat()))
    write_safe_row(writer, ("集計終了日", report["effective_end"].isoformat()))
    write_safe_row(writer, ("達成数", report["total_completed"]))
    write_safe_row(writer, ("対象件数", report["total_expected"]))
    write_safe_row(writer, ("達成率（%）", report["achievement_rate"]))
    write_safe_row(writer, ("全習慣達成日", report["perfect_days"]))
    writer.writerow(())

    write_safe_row(writer, ("日別集計",))
    write_safe_row(
        writer,
        ("日付", "曜日", "状態", "達成数", "対象件数", "達成率（%）"),
    )
    for summary in report["daily_summaries"]:
        target_date = summary["date"]
        if summary["is_future"]:
            write_safe_row(
                writer,
                (
                    target_date.isoformat(),
                    WEEKDAY_LABELS[target_date.weekday()],
                    "未到来",
                    "",
                    "",
                    "",
                ),
            )
            continue

        write_safe_row(
            writer,
            (
                target_date.isoformat(),
                WEEKDAY_LABELS[target_date.weekday()],
                "集計済み",
                summary["completed_count"],
                summary["expected_count"],
                summary["achievement_rate"],
            ),
        )

    writer.writerow(())
    write_safe_row(writer, ("習慣別集計",))
    write_safe_row(
        writer,
        (
            "習慣名",
            "集計終了日時点の対象曜日",
            "達成日数",
            "対象日数",
            "達成率（%）",
            "最長連続回数",
            "現在状態",
        ),
    )
    for summary in report["habit_summaries"]:
        write_safe_row(
            writer,
            (
                summary["habit"].name,
                summary["schedule_label"],
                summary["completed_days"],
                summary["expected_days"],
                summary["achievement_rate"],
                summary["longest_streak"],
                "終了済み" if summary["is_archived"] else "利用中",
            ),
        )

    return UTF8_BOM + output.getvalue()


def build_csv_download_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=CSV_MEDIA_TYPE,
        headers={
            **CSV_HEADERS,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def build_csv_error_response(message: str) -> Response:
    return Response(
        content=message,
        status_code=status.HTTP_400_BAD_REQUEST,
        media_type="text/plain; charset=utf-8",
        headers=CSV_HEADERS,
    )

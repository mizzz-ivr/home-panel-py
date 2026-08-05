from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.backup_export import (
    BASE_REQUIRED_TABLES,
    REQUIRED_TABLES,
    write_backup_file,
)
from app.backup_validate import (
    BackupInputError,
    load_backup_file,
    validate_backup_payload,
)
from app.migrations import migrate_habit_schema

DEFAULT_BACKUP_DIRECTORY = Path.home() / "HomePanelBackups"
DEFAULT_KEEP_COUNT = 30
MAX_KEEP_COUNT = 3650
LOCK_FILE_NAME = ".home-panel-backup.lock"
BACKUP_FILENAME_PATTERN = re.compile(
    r"home-panel-backup-(\d{8}T\d{6}Z)(?:-([2-9]\d*))?\.json\Z"
)


class BackupRotationInputError(ValueError):
    """入力値または安全条件を満たさない場合。"""


class BackupRotationRuntimeError(RuntimeError):
    """バックアップ作成・検証処理を完了できない場合。"""


@dataclass(frozen=True)
class ManagedBackup:
    path: Path
    exported_at: datetime
    sequence: int
    sha256: str


@dataclass(frozen=True)
class SkippedBackup:
    path: Path
    reason: str


@dataclass(frozen=True)
class RetentionResult:
    deleted: tuple[Path, ...]
    skipped: tuple[SkippedBackup, ...]
    failed: tuple[SkippedBackup, ...]


@dataclass(frozen=True)
class BackupRotationResult:
    created: ManagedBackup
    retention: RetentionResult


def parse_backup_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00").astimezone(
        timezone.utc
    )


def validate_keep_count(keep_count: int) -> None:
    if not 1 <= keep_count <= MAX_KEEP_COUNT:
        raise BackupRotationInputError(
            f"--keepは1〜{MAX_KEEP_COUNT}の整数で指定してください。"
        )


def prepare_backup_directory(directory: Path) -> Path:
    expanded = directory.expanduser()
    if expanded.is_symlink():
        raise BackupRotationInputError(
            f"バックアップ先にシンボリックリンクは指定できません: {expanded}"
        )
    if expanded.exists() and not expanded.is_dir():
        raise BackupRotationInputError(
            f"バックアップ先はディレクトリである必要があります: {expanded}"
        )

    expanded.mkdir(parents=True, exist_ok=True)
    resolved = expanded.resolve()
    if not resolved.is_dir():
        raise BackupRotationInputError(
            f"バックアップ先を準備できません: {resolved}"
        )
    return resolved


@contextmanager
def backup_directory_lock(
    directory: Path,
    *,
    acquired_at: datetime | None = None,
) -> Iterator[Path]:
    lock_path = directory / LOCK_FILE_NAME
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        raise BackupRotationInputError(
            "別のバックアップ処理が実行中か、前回のロックが残っています: "
            f"{lock_path}\n"
            "実行中の処理がないことを確認してからロックファイルを削除してください。"
        ) from exc

    timestamp = (acquired_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as lock_file:
            lock_file.write(f"pid={os.getpid()}\n")
            lock_file.write(
                "acquired_at="
                + timestamp.isoformat().replace("+00:00", "Z")
                + "\n"
            )
            lock_file.flush()
            os.fsync(lock_file.fileno())
        yield lock_path
    finally:
        lock_path.unlink(missing_ok=True)


def next_backup_path(directory: Path, exported_at: datetime) -> Path:
    timestamp = exported_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_path = directory / f"home-panel-backup-{timestamp}.json"
    if not base_path.exists():
        return base_path

    for sequence in range(2, 10000):
        candidate = directory / f"home-panel-backup-{timestamp}-{sequence}.json"
        if not candidate.exists():
            return candidate
    raise BackupRotationRuntimeError(
        f"同一時刻のバックアップ名を採番できません: {timestamp}"
    )


def create_sqlite_engine(database_path: Path):
    return create_engine(
        URL.create("sqlite", database=str(database_path)),
        connect_args={"check_same_thread": False},
    )


def validate_database_for_backup(engine) -> None:
    table_names = set(inspect(engine).get_table_names())
    missing_base_tables = BASE_REQUIRED_TABLES - table_names
    if missing_base_tables:
        raise BackupRotationInputError(
            "必要なテーブルが不足しています: "
            + ", ".join(sorted(missing_base_tables))
        )

    migrate_habit_schema(engine)
    missing_tables = REQUIRED_TABLES - set(inspect(engine).get_table_names())
    if missing_tables:
        raise BackupRotationInputError(
            "必要なテーブルが不足しています: "
            + ", ".join(sorted(missing_tables))
        )


def filename_metadata(path: Path) -> tuple[datetime, int] | None:
    match = BACKUP_FILENAME_PATTERN.fullmatch(path.name)
    if match is None:
        return None
    filename_time = datetime.strptime(
        match.group(1), "%Y%m%dT%H%M%SZ"
    ).replace(tzinfo=timezone.utc)
    sequence = int(match.group(2)) if match.group(2) is not None else 1
    return filename_time, sequence


def inspect_managed_backup(path: Path) -> tuple[ManagedBackup | None, SkippedBackup | None]:
    metadata = filename_metadata(path)
    if metadata is None:
        return None, None
    if path.is_symlink():
        return None, SkippedBackup(path, "シンボリックリンクのため自動管理しません。")
    if not path.is_file():
        return None, SkippedBackup(path, "通常ファイルではないため自動管理しません。")

    try:
        payload, digest = load_backup_file(path)
        errors = validate_backup_payload(payload)
    except (BackupInputError, OSError) as exc:
        return None, SkippedBackup(path, f"検証できません: {exc}")

    if errors:
        return None, SkippedBackup(
            path,
            f"バックアップ検証エラーが{len(errors)}件あります: {errors[0]}",
        )

    filename_time, sequence = metadata
    exported_at = parse_backup_datetime(payload["exported_at"])
    if exported_at.replace(microsecond=0) != filename_time:
        return None, SkippedBackup(
            path,
            "ファイル名のUTC時刻とJSONのexported_atが一致しません。",
        )

    return (
        ManagedBackup(
            path=path.resolve(),
            exported_at=exported_at,
            sequence=sequence,
            sha256=digest,
        ),
        None,
    )


def create_verified_backup(
    database_path: Path,
    backup_directory: Path,
    *,
    exported_at: datetime | None = None,
) -> ManagedBackup:
    source = database_path.expanduser().resolve()
    if not source.is_file():
        raise BackupRotationInputError(
            f"バックアップ対象のDBが見つかりません: {source}"
        )

    export_time = (exported_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    output_path = next_backup_path(backup_directory, export_time)
    if output_path.resolve() == source:
        raise BackupRotationInputError(
            "バックアップ対象のDB本体を出力先には指定できません。"
        )

    engine = create_sqlite_engine(source)
    try:
        validate_database_for_backup(engine)
        session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
        )
        with session_factory() as db:
            destination = write_backup_file(
                db,
                output_path,
                exported_at=export_time,
            )
    finally:
        engine.dispose()

    managed, skipped = inspect_managed_backup(destination)
    if managed is None:
        cleanup_error: OSError | None = None
        try:
            destination.unlink(missing_ok=True)
        except OSError as exc:
            cleanup_error = exc
        reason = skipped.reason if skipped is not None else "命名規則を確認できません。"
        if cleanup_error is not None:
            reason += f" 検証失敗ファイルの削除にも失敗しました: {cleanup_error}"
        raise BackupRotationRuntimeError(
            f"作成したバックアップの検証に失敗しました: {reason}"
        )
    return managed


def collect_managed_backups(
    directory: Path,
) -> tuple[list[ManagedBackup], list[SkippedBackup]]:
    managed: list[ManagedBackup] = []
    skipped: list[SkippedBackup] = []
    for path in directory.iterdir():
        if filename_metadata(path) is None:
            continue
        inspected, warning = inspect_managed_backup(path)
        if inspected is not None:
            managed.append(inspected)
        elif warning is not None:
            skipped.append(warning)
    managed.sort(
        key=lambda item: (
            item.exported_at,
            item.sequence,
            item.path.name,
        )
    )
    skipped.sort(key=lambda item: item.path.name)
    return managed, skipped


def prune_managed_backups(
    directory: Path,
    *,
    keep_count: int,
    protected_path: Path,
) -> RetentionResult:
    validate_keep_count(keep_count)
    managed, skipped = collect_managed_backups(directory)
    candidates = managed[:-keep_count] if len(managed) > keep_count else []

    deleted: list[Path] = []
    failed: list[SkippedBackup] = []
    protected = protected_path.resolve()
    for candidate in candidates:
        if candidate.path == protected:
            skipped.append(
                SkippedBackup(
                    candidate.path,
                    "今回作成したバックアップのため保持します。",
                )
            )
            continue

        current, warning = inspect_managed_backup(candidate.path)
        if current is None or current.sha256 != candidate.sha256:
            failed.append(
                warning
                or SkippedBackup(
                    candidate.path,
                    "検証後に内容が変更されたため削除しません。",
                )
            )
            continue
        try:
            candidate.path.unlink()
        except OSError as exc:
            failed.append(
                SkippedBackup(candidate.path, f"削除に失敗しました: {exc}")
            )
        else:
            deleted.append(candidate.path)

    return RetentionResult(
        deleted=tuple(deleted),
        skipped=tuple(sorted(skipped, key=lambda item: item.path.name)),
        failed=tuple(failed),
    )


def run_backup_rotation(
    database_path: Path,
    backup_directory: Path,
    *,
    keep_count: int = DEFAULT_KEEP_COUNT,
    exported_at: datetime | None = None,
) -> BackupRotationResult:
    validate_keep_count(keep_count)
    directory = prepare_backup_directory(backup_directory)
    with backup_directory_lock(directory, acquired_at=exported_at):
        created = create_verified_backup(
            database_path,
            directory,
            exported_at=exported_at,
        )
        retention = prune_managed_backups(
            directory,
            keep_count=keep_count,
            protected_path=created.path,
        )
    return BackupRotationResult(created=created, retention=retention)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Home PanelのJSONバックアップを作成・検証し、"
            "検証済みファイルを指定世代数まで整理します。"
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("home_panel.db"),
        help="バックアップ対象のSQLiteファイル（既定: home_panel.db）",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=DEFAULT_BACKUP_DIRECTORY,
        help=(
            "バックアップ保存先ディレクトリ"
            "（既定: ~/HomePanelBackups）"
        ),
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_KEEP_COUNT,
        help=f"保持する検証済みバックアップ数（既定: {DEFAULT_KEEP_COUNT}）",
    )
    return parser


def run_cli(args: Sequence[str] | None = None) -> int:
    options = create_parser().parse_args(args)
    try:
        result = run_backup_rotation(
            options.database,
            options.backup_dir,
            keep_count=options.keep,
        )
    except (BackupRotationInputError, BackupInputError) as exc:
        print(f"バックアップを実行できません: {exc}", file=sys.stderr)
        return 2
    except (BackupRotationRuntimeError, OSError, SQLAlchemyError) as exc:
        print(f"バックアップ処理に失敗しました: {exc}", file=sys.stderr)
        return 1

    print(f"バックアップを作成しました: {result.created.path}")
    print(f"SHA-256: {result.created.sha256}")
    print(f"削除した旧バックアップ: {len(result.retention.deleted)}件")
    for deleted in result.retention.deleted:
        print(f"- 削除: {deleted}")
    for warning in result.retention.skipped:
        print(
            f"警告: 自動管理しないファイル: {warning.path} ({warning.reason})",
            file=sys.stderr,
        )
    for failure in result.retention.failed:
        print(
            f"警告: 世代整理を完了できませんでした: "
            f"{failure.path} ({failure.reason})",
            file=sys.stderr,
        )

    return 1 if result.retention.failed else 0


if __name__ == "__main__":
    raise SystemExit(run_cli())

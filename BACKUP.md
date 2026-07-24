# Home Panel バックアップ手順

## 目的

`home_panel.db`に保存されている以下のデータを、可読性と将来の移行性を考慮したJSON形式で一括保存します。

- ToDo
- 日別メモ
- 時間記録

バックアップは読み取り専用です。実行してもDB内のデータは変更されません。

## 基本的な実行方法

プロジェクトのルートディレクトリで実行します。

```bash
python -m app.backup_export
```

既定では、ユーザーのホームディレクトリに次の形式で作成されます。

```text
HomePanelBackups/home-panel-backup-YYYYMMDDTHHMMSSZ.json
```

日時はUTCです。

## オプション

### 対象DBを指定する

```bash
python -m app.backup_export --database /path/to/home_panel.db
```

DBファイルが存在しない場合や、必要なテーブルが不足している場合はバックアップを作成しません。

### 出力先を指定する

```bash
python -m app.backup_export --output /path/to/backup.json
```

親ディレクトリが存在しない場合は自動作成します。

### 既存ファイルを上書きする

既定では既存ファイルを上書きしません。明示的に上書きする場合だけ`--force`を指定します。

```bash
python -m app.backup_export --output /path/to/backup.json --force
```

バックアップ対象のDB本体と同じパスは、`--force`を指定しても拒否します。

## JSON形式

バックアップには形式の互換性を判断するための`schema_version`を含めます。

```json
{
  "schema_version": 1,
  "application": "home-panel-py",
  "exported_at": "2026-07-24T12:34:56Z",
  "record_counts": {
    "tasks": 1,
    "daily_memos": 1,
    "time_entries": 1
  },
  "data": {
    "tasks": [],
    "daily_memos": [],
    "time_entries": []
  }
}
```

各レコードにはID、日付、本文、状態、登録・更新日時など、現行DBに保存されている復元判断用の情報を含めます。

## 安全性

- 一時ファイルへ書き込んでから置換するため、途中失敗で不完全なJSONが完成ファイルとして残りにくい構成です。
- POSIX環境では、作成後のファイル権限を可能な範囲で所有者のみ読み書き可能にします。
- 出力先が存在する場合は、`--force`がなければ処理を中止します。
- DB本体を出力先へ指定する操作は拒否します。
- バックアップには個人データが含まれるため、Git管理対象や公開フォルダへ置かないでください。

## 内容確認

JSONとして読み取れるか確認できます。

```bash
python -m json.tool ~/HomePanelBackups/home-panel-backup-YYYYMMDDTHHMMSSZ.json > /dev/null
```

Windows PowerShellでは、実際に作成されたファイルパスを指定してください。

## 対象範囲

このバックアップは、DBに存在する全レコードを保存します。集計画面やCSV出力とは異なり、未来日として保存された時間記録も欠落防止のため対象です。

## 未対応

- JSONからDBへの復元
- バックアップ内容の暗号化
- 自動・定期バックアップ
- 世代管理と古いファイルの削除
- バックアップファイルのクラウド転送

復元機能を追加する際は、スキーマ版検証、入力バリデーション、重複時の方針、トランザクション、復元前バックアップを必須要件として設計してください。

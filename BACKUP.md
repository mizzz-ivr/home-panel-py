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

## バックアップの検証

復元や別環境への移行に使用する前に、専用CLIで検証します。

```bash
python -m app.backup_validate /path/to/home-panel-backup.json
```

検証に成功すると、テーブル別件数とファイルのSHA-256が表示されます。

```text
バックアップは有効です。
レコード件数: ToDo=1、メモ=1、時間記録=1
SHA-256: 0123456789abcdef...
```

検証対象は以下です。

- UTF-8として読み取れること
- JSONとして正しいこと
- JSONオブジェクト内に重複キーがないこと
- ファイルサイズが50MiB以下であること
- `schema_version`が対応版であること
- アプリケーション識別子が一致すること
- 必須項目が揃い、未知の項目がないこと
- `record_counts`と実データ件数が一致すること
- 各テーブル内でIDが重複していないこと
- 日付・UTC日時が実在すること
- タイトル、メモ、時間、カテゴリが現行の入力制約を満たすこと
- ToDoの更新日時が作成日時より前になっていないこと

検証に失敗した場合は、問題箇所をJSONパス付きで最大100件まで表示します。

### SHA-256を照合する

バックアップ作成直後に表示・記録したSHA-256や、別途安全な場所へ保存したSHA-256がある場合は、次のように照合できます。

```bash
python -m app.backup_validate /path/to/home-panel-backup.json \
  --expected-sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

SHA-256が一致しない場合、ファイル内容が作成時から変わった可能性があります。

構造検証だけでは、入力制約を満たす内容へ意図的に書き換えられたことまでは判定できません。同一性を確認する必要がある場合は、信頼できる場所に保管したSHA-256との照合を併用してください。

## 簡易的なJSON確認

専用CLIを利用できない環境では、JSONとして読み取れるかだけを確認できます。

```bash
python -m json.tool ~/HomePanelBackups/home-panel-backup-YYYYMMDDTHHMMSSZ.json > /dev/null
```

この方法では、件数不一致・重複ID・入力制約違反・未対応スキーマなどは検出できません。

Windows PowerShellでは、実際に作成されたファイルパスを指定してください。

## 対象範囲

このバックアップは、DBに存在する全レコードを保存します。集計画面やCSV出力とは異なり、未来日として保存された時間記録も欠落防止のため対象です。

## 未対応

- JSONからDBへの復元
- バックアップ内容の暗号化
- 自動・定期バックアップ
- 世代管理と古いファイルの削除
- バックアップファイルのクラウド転送
- SHA-256の自動的な別ファイル保存や署名

復元機能を追加する際は、専用CLIによる検証、スキーマ版確認、入力バリデーション、重複時の方針、トランザクション、復元前バックアップを必須要件として設計してください。

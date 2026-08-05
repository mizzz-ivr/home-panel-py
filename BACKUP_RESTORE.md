# Home Panel JSONバックアップ復元手順

## 目的

`app.backup_export`で作成したJSONバックアップを、Home Panelの現在スキーマを持つSQLiteへ安全に復元します。

復元はDBファイルを置き換える操作です。実行前にHome Panelを停止し、復元先が別プロセスから利用されていないことを確認してください。

## 対応範囲

復元CLIはバックアップスキーマv1〜v5を受け付けます。

| 入力スキーマ | 復元内容 |
|---|---|
| v1 | ToDo・日別メモ・時間記録 |
| v2 | v1 + 習慣・習慣達成。終了日時・有効期間・曜日設定を補完 |
| v3 | v2 + `archived_at`。有効期間・曜日設定を補完 |
| v4 | v3 + 有効期間。曜日設定を補完 |
| v5 | 全データをそのまま現在スキーマへ復元 |

復元後のDBは常に現在のv5相当のテーブル構成になります。

## 復元対象

- ToDo
- 日別メモ
- 時間記録
- 習慣
- 習慣の有効期間
- 習慣の曜日設定期間
- 習慣の日次達成記録

次はJSONバックアップに含まれないため復元しません。

- `app_settings`
- ダッシュボードのカード並び順・表示設定
- 習慣達成Undoの一時情報

## 復元前の確認

1. Home Panelを停止する
2. 復元するJSONの保管元を確認する
3. 可能であれば別の安全な場所に保存したSHA-256を準備する
4. 復元先が未作成または完全に空であることを確認する
5. 十分な空き容量があることを確認する

既存データがあるDBへの上書き・マージはできません。

## 基本的な実行方法

既定の復元先はカレントディレクトリの`home_panel.db`です。

```bash
python -m app.backup_restore /path/to/home-panel-backup.json
```

復元先を指定する場合:

```bash
python -m app.backup_restore /path/to/home-panel-backup.json \
  --database /path/to/restored.db
```

Windows PowerShell:

```powershell
python -m app.backup_restore C:\Backups\home-panel-backup.json `
  --database C:\HomePanel\restored.db
```

## SHA-256を照合する

```bash
python -m app.backup_restore /path/to/home-panel-backup.json \
  --database /path/to/restored.db \
  --expected-sha256 <64桁のSHA-256>
```

`--expected-sha256`は大文字・小文字を区別しません。

SHA-256が一致しない場合、復元先は作成・変更しません。

## 復元できるDB

次のいずれかだけを受け付けます。

- 復元先ファイルが存在しない
- 復元先が0バイトの通常ファイル
- Home Panelの既知テーブルだけを持ち、すべて0件のSQLite

既知テーブル:

- `tasks`
- `daily_memos`
- `time_entries`
- `habits`
- `habit_active_periods`
- `habit_schedule_periods`
- `habit_completions`
- `app_settings`

`app_settings`にダッシュボード設定やUndo情報が1件でもある場合も、既存データありとして拒否します。

## 拒否する復元先

- 1件以上の既存データがあるDB
- 未知のテーブルを持つDB
- 破損したSQLite
- ディレクトリ
- シンボリックリンク
- バックアップJSON自身と同じパス

既存データを削除する`--force`オプションはありません。

## 復元処理

復元先へ直接INSERTしません。

1. JSONを最大50MiBの範囲で読み込む
2. UTF-8・重複JSONキー・スキーマ・入力制約を検証する
3. 必要に応じてv1〜v4を現在のv5構造へ補完する
4. 補完後のv5データを再検証する
5. 復元先が空であることを確認する
6. 復元先と同じディレクトリに一時SQLiteを作成する
7. 現在の全テーブルを作成する
8. 全レコードを1トランザクションで投入する
9. `PRAGMA foreign_key_check`を実行する
10. `PRAGMA integrity_check`を実行する
11. 一時DBをJSONへ再エクスポートする
12. 件数と全データが正規化済み入力と一致することを確認する
13. 一時DBを`fsync`する
14. `os.replace`で復元先へ切り替える
15. 親ディレクトリを可能な範囲で`fsync`する

一時DBの検証が完了するまで、既存の復元先は変更しません。

## 旧スキーマの補完規則

### v1

習慣データが存在しないため、現在の習慣関連テーブルを空で作成します。

### v2

`archived_at`が存在しません。

- アクティブ習慣: `archived_at = null`
- 終了済み習慣: `archived_at = updated_at`

### v2・v3

有効期間が存在しないため、習慣ごとに1区間を生成します。

- 開始日: `created_at`の日付
- アクティブ習慣の終了日: `null`
- 終了済み習慣の終了日: `archived_at`の日付

### v2〜v4

曜日設定期間が存在しないため、習慣ごとに作成日からの毎日設定を生成します。

```text
schedule_type = weekdays
weekdays = [0, 1, 2, 3, 4, 5, 6]
started_on = created_atの日付
ended_on = null
```

補完後に有効期間外・対象曜日外の達成記録などが判明した場合、推測で修正せず復元を拒否します。

## 復元前DBの退避

復元先ファイルが既に存在し、かつ空DBとして利用可能な場合も、置換前に同じディレクトリへコピーします。

```text
home_panel.pre-restore-YYYYMMDDTHHMMSSZ.db
```

同名ファイルが存在する場合:

```text
home_panel.pre-restore-YYYYMMDDTHHMMSSZ-2.db
home_panel.pre-restore-YYYYMMDDTHHMMSSZ-3.db
```

復元先が未作成だった場合、退避ファイルは作りません。

## 成功時の出力

```text
バックアップを復元しました: /path/to/restored.db
入力スキーマ: v5
レコード件数: ToDo=1、メモ=1、時間記録=1、習慣=1、習慣有効期間=1、曜日設定期間=1、習慣達成=1
SHA-256: ...
復元前DBの退避先: ...
```

最後の退避先は、復元先ファイルが実行前から存在した場合だけ表示します。

## 終了コード

| 終了コード | 意味 |
|---:|---|
| 0 | 復元成功 |
| 1 | DB操作・ファイル操作・復元後検証などの実行時エラー |
| 2 | 不正バックアップ・SHA不一致・既存データ・不正な復元先 |

## 失敗時の確認

### 復元先に既存データがある

既存DBを空にせず、別の新しいパスへ復元してください。

```bash
python -m app.backup_restore backup.json \
  --database restored-new.db
```

### SQLiteが別プロセスで開かれている

Home Panel、SQLiteブラウザ、IDEのDB接続などを終了して再実行してください。

### 一時DBの検証に失敗した

復元先は置き換えません。一時ファイルは削除します。入力バックアップの検証結果とエラーメッセージを確認してください。

### 最終置換に失敗した

既存の空DBは維持されます。復元前退避ファイルが作られている場合は、そのファイルも保持します。

## 復元後の確認

1. CLIが終了コード0で終了したことを確認する
2. 出力された件数とSHA-256を記録する
3. Home Panelを起動する
4. ToDo・メモ・時間記録・習慣を確認する
5. 習慣の日別・週次・月次集計を確認する
6. 必要に応じて復元後DBから新しいバックアップを作成・検証する

```bash
python -m app.backup_export \
  --database /path/to/restored.db \
  --output /path/to/post-restore-backup.json

python -m app.backup_validate /path/to/post-restore-backup.json
```

## セキュリティ・運用上の注意

- バックアップには個人データが含まれる
- Git管理対象や公開フォルダへ保存しない
- CLIは認証・暗号化を提供しない
- SHA-256は改変防止署名ではなく、既知ファイルとの同一性確認に利用する
- 復元中はアプリを停止する
- ネットワーク共有上での原子的置換はファイルシステム実装に依存する
- Windowsでは別プロセスがDBを開いていると置換に失敗する場合がある

## 未対応

- 非空DBの上書き
- 既存データとのマージ
- テーブル・期間・レコードを選択した部分復元
- Web画面からの復元
- 暗号化バックアップ
- 署名検証
- `app_settings`のバックアップ・復元

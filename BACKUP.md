# Home Panel バックアップ手順

## 目的

`home_panel.db`に保存されている以下のデータを、可読性と将来の移行性を考慮したJSON形式で一括保存します。

- ToDo
- 日別メモ
- 時間記録
- 習慣
- 習慣の有効期間
- 習慣の曜日設定期間
- 習慣の日次達成記録

ダッシュボード設定を保存する`app_settings`は、現時点ではバックアップ対象外です。

## 基本的な実行方法

```bash
python -m app.backup_export
```

既定の出力先:

```text
~/HomePanelBackups/home-panel-backup-YYYYMMDDTHHMMSSZ.json
```

日時はUTCです。

対象DBや出力先を指定できます。

```bash
python -m app.backup_export --database /path/to/home_panel.db
python -m app.backup_export --output /path/to/backup.json
```

既存ファイルを上書きする場合だけ`--force`を指定します。

```bash
python -m app.backup_export --output /path/to/backup.json --force
```

DB本体と同じパスは、`--force`付きでも拒否します。

## 現在のJSON形式

現在生成する形式はスキーマv5です。

```json
{
  "schema_version": 5,
  "application": "home-panel-py",
  "exported_at": "2026-07-28T12:34:56Z",
  "record_counts": {
    "tasks": 1,
    "daily_memos": 1,
    "time_entries": 1,
    "habits": 1,
    "habit_active_periods": 2,
    "habit_schedule_periods": 2,
    "habit_completions": 1
  },
  "data": {
    "tasks": [],
    "daily_memos": [],
    "time_entries": [],
    "habits": [
      {
        "id": 1,
        "name": "読書",
        "is_active": true,
        "archived_at": null,
        "created_at": "2026-07-01T09:00:00Z",
        "updated_at": "2026-07-20T10:00:00Z"
      }
    ],
    "habit_active_periods": [
      {
        "id": 1,
        "habit_id": 1,
        "started_on": "2026-07-01",
        "ended_on": "2026-07-10",
        "created_at": "2026-07-01T09:00:00Z"
      },
      {
        "id": 2,
        "habit_id": 1,
        "started_on": "2026-07-20",
        "ended_on": null,
        "created_at": "2026-07-20T10:00:00Z"
      }
    ],
    "habit_schedule_periods": [
      {
        "id": 1,
        "habit_id": 1,
        "schedule_type": "weekdays",
        "weekdays": [0, 1, 2, 3, 4, 5, 6],
        "started_on": "2026-07-01",
        "ended_on": "2026-07-19",
        "created_at": "2026-07-01T09:00:00Z"
      },
      {
        "id": 2,
        "habit_id": 1,
        "schedule_type": "weekdays",
        "weekdays": [0, 2, 4],
        "started_on": "2026-07-20",
        "ended_on": null,
        "created_at": "2026-07-20T10:00:00Z"
      }
    ],
    "habit_completions": []
  }
}
```

曜日はDB内部のビットマスクではなく、月曜日`0`〜日曜日`6`の配列として保存します。

## スキーマ互換性

### v1

- ToDo
- 日別メモ
- 時間記録

### v2

v1へ習慣と日次達成記録を追加しました。

### v3

v2の習慣へ`archived_at`を追加しました。

### v4

v3へ`habit_active_periods`を追加しました。

- 習慣ごとの開始日・終了日
- 複数回の終了・再開履歴
- 停止期間を除外した集計の復元根拠

### v5

v4へ`habit_schedule_periods`を追加しました。

- 曜日設定の適用開始日・終了日
- 設定変更前の曜日履歴
- 対象外曜日を除外した集計の復元根拠

現在のバックアップ生成はv5です。検証CLIはv1〜v5を受け付けます。既存ファイルを自動で書き換える処理は行いません。

## 旧SQLiteを直接指定する場合

バックアップCLIは、旧DBを検出すると出力前に習慣関連の互換移行を実行します。

1. `archived_at`列を追加
2. 終了済み習慣は`updated_at`から終了日時を補完
3. `habit_active_periods`を作成
4. 既存習慣ごとに初期有効期間を生成
5. `habit_schedule_periods`を作成
6. 既存習慣ごとに作成日からの「毎日」設定を生成

初期有効期間:

- アクティブ習慣: `created_at`の日付から継続中
- 終了済み習慣: `created_at`の日付から`archived_at`の日付まで

初期曜日設定:

```text
schedule_type = weekdays
weekdays = [0, 1, 2, 3, 4, 5, 6]
started_on = 習慣作成日
ended_on = null
```

移行前に保存されていない過去の停止期間や曜日変更履歴は推測して復元できません。

バックアップCLIは通常読み取り専用ですが、この旧DB互換処理に限りスキーマと補完値を更新します。実行前にDBファイル自体のコピーも保管してください。

## 安全性

- 一時ファイルへ書き込み、`fsync`後に完成ファイルへ置換
- POSIX環境では可能な範囲で権限を`0600`へ設定
- `--force`なしでは既存ファイルを上書きしない
- DB本体への出力を拒否
- 破損DB・必須テーブル不足を検出
- 個人データを含むため、Git管理対象や公開フォルダへ置かない

## バックアップの検証

```bash
python -m app.backup_validate /path/to/home-panel-backup.json
```

共通の検証内容:

- UTF-8・JSON形式・重複キー
- 50MiBのファイルサイズ上限
- v1〜v5のスキーマ
- 必須項目と未知項目
- レコード件数
- ID重複
- 日付・UTC日時
- 各入力制約
- 習慣達成から習慣への参照整合性
- 同じ習慣・日付の達成重複

v3以降:

- アクティブ習慣の`archived_at`はnull
- 終了済み習慣の`archived_at`は必須
- `archived_at >= created_at`
- `updated_at >= archived_at`

v4以降:

- 有効期間が実在する習慣を参照する
- 同じ習慣・開始日の重複がない
- `ended_on >= started_on`
- 同一習慣の有効期間が交差しない
- アクティブ習慣に開放区間が1件ある
- 終了済み習慣に開放区間がない
- 達成記録が有効期間内に存在する

v5:

- 曜日配列が1件以上で、0〜6の整数だけを含む
- 曜日配列に重複がない
- `schedule_type = weekdays`
- 曜日設定期間が実在する習慣を参照する
- 同一習慣の曜日設定期間が重複・交差しない
- 各習慣に開放中の曜日設定期間が1件ある
- 達成記録がその時点の対象曜日に存在する

## SHA-256を照合する

```bash
python -m app.backup_validate /path/to/home-panel-backup.json \
  --expected-sha256 <64桁のSHA-256>
```

構造検証だけでは、入力制約を満たす別内容への改変までは判定できません。同一性確認には、別の信頼できる場所へ保管したSHA-256を利用してください。

## 対象範囲

- アクティブ・終了済み習慣を保存
- `archived_at`を保存
- 習慣の全有効期間を保存
- 習慣の全曜日設定期間を保存
- 過去の習慣達成記録を保存
- 未来日として保存された時間記録も欠落防止のため保存
- `app_settings`は対象外

## 未対応

- JSONからDBへの復元
- 暗号化
- 定期バックアップ
- 世代管理
- クラウド転送
- SHA-256署名
- ダッシュボード設定のバックアップ

復元機能を追加する際は、検証CLI成功、スキーマ版確認、入力バリデーション、外部キー順序、重複方針、全件トランザクション、復元前バックアップを必須要件とします。

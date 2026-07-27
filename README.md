# home-panel-py

ローカルPCで動作する個人用ダッシュボードです。  
ToDo・メモ・作業時間・継続習慣を1画面で管理し、日別・週次・月次の振り返り、CSV出力、JSONバックアップを行えます。

## プロジェクト概要

- 想定利用: 個人利用・ローカル起動
- Web: FastAPI + Jinja2
- データ保存: SQLite
- 方針: 既存機能への影響を抑え、小さな単位で安全に拡張する

## 主な機能

### ToDo

- タスク追加
- 完了・未完了の切り替え
- タスク削除

### 今日のメモ

- 当日分の表示
- 保存・更新
- 空で保存した場合のクリア

### 学習・作業時間

- 分単位で記録
- 学習・作業・個人開発・その他のカテゴリ
- 当日合計・カテゴリ別合計
- 日別・週次・月次集計
- 月単位CSV出力

### 習慣トラッカー

- 習慣追加
- 今日の達成・取り消し
- 今日の達成件数
- 現在の連続達成日数
- 履歴を残したまま終了
- 習慣名編集
- 終了済み一覧
- 終了済み習慣の再開
- 終了・再開ごとの有効期間履歴
- 停止期間を除外した日別・週次・月次レポート
- アクティブ習慣は最大20件

詳細:

- [`HABITS.md`](./HABITS.md)
- [`HABIT_REPORTS.md`](./HABIT_REPORTS.md)

### ダッシュボード設定

- Swapyによるカード並び替え
- カードごとの表示・非表示
- 並び順と表示設定のSQLite保存
- 設定初期化
- 旧localStorage設定の自動移行
- 新カード追加時の既存設定補完

詳細は[`DASHBOARD.md`](./DASHBOARD.md)を参照してください。

### エクスポート・バックアップ

- 月単位の時間記録CSV
- ToDo・メモ・時間記録・習慣・習慣有効期間のJSONバックアップCLI
- バックアップ構造・件数・参照整合性・SHA-256検証CLI
- バックアップスキーマv1〜v4の検証互換

詳細は[`BACKUP.md`](./BACKUP.md)を参照してください。

## 使用技術

- Python 3.12
- FastAPI
- Jinja2
- SQLAlchemy
- SQLite
- Pydantic
- pytest
- Swapy 1.0.5（CDN）
- GitHub Actions

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 起動

```bash
uvicorn app.main:app --reload
```

主なURL:

- ダッシュボード: <http://127.0.0.1:8000>
- 時間記録・メモの日別履歴: <http://127.0.0.1:8000/history>
- 時間記録の週次集計: <http://127.0.0.1:8000/weekly>
- 時間記録の月次集計: <http://127.0.0.1:8000/monthly>
- 習慣管理: <http://127.0.0.1:8000/habits/manage>
- 習慣の日別履歴: <http://127.0.0.1:8000/habits/history>
- 習慣の週次集計: <http://127.0.0.1:8000/habits/weekly>
- 習慣の月次集計: <http://127.0.0.1:8000/habits/monthly>
- 時間記録CSV: <http://127.0.0.1:8000/exports/time-entries.csv>

初回起動時に`home_panel.db`が作成されます。

## データテーブル

- `tasks`
- `daily_memos`
- `time_entries`
- `habits`
- `habit_active_periods`
- `habit_completions`
- `app_settings`

### 習慣のライフサイクル

`habits`は現在状態、`habit_active_periods`は過去を含む有効区間を保持します。

現在状態:

- `is_active=true`, `archived_at=null`: 利用中
- `is_active=false`, `archived_at=<終了日時>`: 終了済み

有効期間:

- `started_on`: 達成対象になった開始日
- `ended_on`: 終了日。継続中は`null`
- 開始日・終了日はどちらも達成対象へ含む
- 停止中の日付はレポートの分母へ含めない

終了操作は物理削除ではありません。習慣本体・有効期間・過去の達成記録を保持します。

名前編集でも習慣IDは変わらないため、過去履歴は同じ習慣へ紐づいたままです。

再開時は以下を検証します。

- アクティブ習慣が20件未満
- 同名アクティブ習慣が存在しない
- 対象が終了済み

再開時は新しい開放区間を追加します。同日に終了・再開した場合は、日単位の停止期間が存在しないため直前区間を再オープンします。

## 既存SQLiteの自動移行

旧DBでは、起動時に軽量マイグレーションを順番に実行します。

1. `habits.archived_at`がなければ追加
2. 終了済み習慣は`updated_at`から終了日時を補完
3. `habit_active_periods`がなければ作成
4. 既存習慣ごとに初期有効期間を1件生成

初期有効期間:

- アクティブ習慣: `created_at`の日付から継続中
- 終了済み習慣: `created_at`の日付から`archived_at`の日付まで

移行処理は冪等です。既存ID、習慣名、達成記録は変更しません。

移行前は複数回の終了・再開履歴を保存していないため、過去の停止区間を推測して復元することはできません。

DB変更が増えた場合は、Alembicなどの本格的なマイグレーション管理へ移行する想定です。

## 履歴・集計

### 時間記録・メモ

- `/history?target_date=YYYY-MM-DD`
- `/weekly?target_date=YYYY-MM-DD`
- `/monthly?target_month=YYYY-MM`

確認できる内容:

- メモ
- 時間記録
- 合計時間・件数・記録日数
- カテゴリ別合計
- 日別推移

### 習慣

- `/habits/history?target_date=YYYY-MM-DD`
- `/habits/weekly?target_date=YYYY-MM-DD`
- `/habits/monthly?target_month=YYYY-MM`

確認できる内容:

- 達成・未達成
- 達成数・対象件数・達成率
- 全対象習慣を達成した日数
- 日別カレンダー
- 習慣別達成日数
- 選択期間内の最長連続日数
- 終了済み習慣の過去実績
- 停止期間を除外した対象日数

レポートは`habit_active_periods`を参照します。

例:

```text
有効: 7月1日〜3日
停止: 7月4日〜5日
有効: 7月6日〜
```

7月4日・5日は対象習慣数と達成率の分母へ含めません。

移行途中などで有効期間履歴が存在しない場合に限り、`created_at`・`archived_at`を使った互換判定へフォールバックします。

## 時間記録CSV

```text
/exports/time-entries.csv?target_month=2026-07
```

- UTF-8 BOM付き
- CSV特殊文字の標準エスケープ
- CSV数式注入対策
- `Cache-Control: no-store`
- `X-Content-Type-Options: nosniff`

## JSONバックアップ

```bash
python -m app.backup_export
```

既定出力先:

```text
~/HomePanelBackups/home-panel-backup-YYYYMMDDTHHMMSSZ.json
```

現在生成する形式はスキーマv4です。

- v1: ToDo・日別メモ・時間記録
- v2: v1 + 習慣・習慣達成
- v3: v2 + 習慣の`archived_at`
- v4: v3 + `habit_active_periods`

旧DBを直接指定した場合、バックアップ前に`archived_at`と有効期間テーブルの互換移行を実行します。

## バックアップ検証

```bash
python -m app.backup_validate /path/to/home-panel-backup.json
```

検証CLIはv1〜v4を受け付けます。

主な検証:

- 必須項目と未知項目
- レコード件数
- ID重複
- 入力制約
- 日付・UTC日時
- 習慣達成から習慣への参照
- 同じ習慣・日付の重複
- `archived_at`と状態・日時の整合性
- 有効期間の参照・日付・重複・交差
- アクティブ状態と開放区間数の整合性
- 達成記録が有効期間内にあること
- SHA-256

## ダッシュボード設定API

- `GET /api/dashboard/preferences`
- `PUT /api/dashboard/preferences`
- `DELETE /api/dashboard/preferences`

保存例:

```json
{
  "order": ["todo", "memo", "time", "habits"],
  "hidden": []
}
```

## 入力バリデーション

- ToDo: 1〜255文字
- メモ: 5000文字以内
- 時間記録: 固定4カテゴリ、1〜1440分、メモ255文字以内
- 習慣: 1〜100文字、空白・同名・21件目を拒否
- 再開: 同名・上限・不正状態を拒否
- 履歴・集計: 日付・月形式を厳密検証し未来期間を拒否
- ダッシュボード設定: 未登録カード、重複、欠落、全非表示を拒否

## ディレクトリ構成

```text
home-panel-py/
├─ app/
│  ├─ main.py
│  ├─ db.py
│  ├─ migrations.py
│  ├─ dashboard_cards.py
│  ├─ habit_report.py
│  ├─ habit_report_routes.py
│  ├─ csv_export.py
│  ├─ backup_export.py
│  ├─ backup_validate.py
│  ├─ models/
│  ├─ schemas/
│  ├─ crud/
│  ├─ templates/
│  │  ├─ cards/
│  │  ├─ habit_manage.html
│  │  ├─ habit_history.html
│  │  ├─ habit_weekly.html
│  │  └─ habit_monthly.html
│  └─ static/
│     ├─ style.css
│     ├─ dashboard.css
│     ├─ monthly.css
│     ├─ habit_manage.css
│     ├─ habit_reports.css
│     └─ app.js
├─ tests/
├─ BACKUP.md
├─ DASHBOARD.md
├─ HABITS.md
├─ HABIT_REPORTS.md
├─ requirements.txt
└─ README.md
```

## テスト

```bash
pytest -q
```

主な確認範囲:

- ToDo・メモ・時間記録
- 習慣追加・達成・取り消し・終了
- 習慣名編集・終了済み一覧・再開
- `archived_at`移行
- 習慣有効期間の作成・終了・再開・同日再開
- 停止期間を除外した日別・週次・月次集計
- 旧SQLiteからの有効期間生成と冪等性
- CSVエクスポート
- JSONバックアップv4生成
- v1〜v4検証
- 有効期間重複・状態不整合・期間外達成の検出
- ダッシュボード設定
- Swapy用HTML構造とJavaScript配信

## GitHub Actions

`.github/workflows/ci.yml`は`main`へのpush・pull request・手動実行で動作します。

品質チェック:

1. Python 3.12
2. 依存関係インストール
3. `pip check`
4. Python構文チェック
5. JavaScript構文チェック
6. FastAPIアプリのimport
7. pytest

## Swapyのライセンスに関する注意

Swapy 1.0.5はGPL-3.0または商用ライセンスで提供されています。

継続利用する前に、プロジェクトをGPL-3.0互換ライセンスで公開するか、商用ライセンスを利用するかを決定してください。方針未確定のまま商用・非公開用途へ展開しないでください。

## 今後の拡張候補

- 習慣の曜日・頻度設定
- 過去日の達成編集
- 有効期間の手動編集
- 習慣レポートCSV・年次集計
- キーボード操作によるカード並び替え
- ダッシュボードの表示密度・テーマ設定
- JSONバックアップからの安全な復元
- 週次・月次集計のカテゴリ積み上げ表示
- 認証・ユーザー分離

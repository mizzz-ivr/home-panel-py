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
- 日別履歴から今日を含む過去日の達成状態を修正
- 日別履歴で対象習慣を一括達成・その日の全達成記録を一括取り消し
- 日別履歴で選択した習慣だけを一括達成・一括取り消し
- 直前の達成操作を10分以内に元へ戻すUndo
- 毎日・平日・土日・任意曜日の設定
- 対象外曜日を除外した今日の達成件数
- 対象日ベースの連続達成表示
- 履歴を残したまま終了
- 習慣名編集
- 終了済み一覧
- 終了済み習慣の再開
- 終了・再開ごとの有効期間履歴
- 変更前を保持する曜日設定履歴
- 停止期間・対象外曜日を除外した日別・週次・月次レポート
- 週次・月次レポートCSV出力
- アクティブ習慣は最大20件

詳細:

- [`HABITS.md`](./HABITS.md)
- [`HABIT_SCHEDULES.md`](./HABIT_SCHEDULES.md)
- [`HABIT_REPORTS.md`](./HABIT_REPORTS.md)
- [`HABIT_BULK_COMPLETION.md`](./HABIT_BULK_COMPLETION.md)
- [`HABIT_COMPLETION_UNDO.md`](./HABIT_COMPLETION_UNDO.md)
- [`HABIT_REPORT_CSV.md`](./HABIT_REPORT_CSV.md)

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
- 習慣の週次・月次レポートCSV
- ToDo・メモ・時間記録・習慣・有効期間・曜日設定期間のJSONバックアップCLI
- バックアップ構造・件数・参照整合性・SHA-256検証CLI
- バックアップスキーマv1〜v5の検証互換

詳細:

- [`HABIT_REPORT_CSV.md`](./HABIT_REPORT_CSV.md)
- [`BACKUP.md`](./BACKUP.md)

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
- 習慣管理・曜日設定: <http://127.0.0.1:8000/habits/manage>
- 習慣の日別履歴・達成編集: <http://127.0.0.1:8000/habits/history>
- 習慣の週次集計: <http://127.0.0.1:8000/habits/weekly>
- 習慣の月次集計: <http://127.0.0.1:8000/habits/monthly>
- 時間記録CSV: <http://127.0.0.1:8000/exports/time-entries.csv>
- 習慣週次CSV: <http://127.0.0.1:8000/habits/weekly.csv>
- 習慣月次CSV: <http://127.0.0.1:8000/habits/monthly.csv>
- 習慣Undo状態API: <http://127.0.0.1:8000/habits/completions/undo?target_date=2026-07-31>

初回起動時に`home_panel.db`が作成されます。

## データテーブル

- `tasks`
- `daily_memos`
- `time_entries`
- `habits`
- `habit_active_periods`
- `habit_schedule_periods`
- `habit_completions`
- `app_settings`

`app_settings`にはダッシュボード設定のほか、期限付きの直前習慣操作Undoを保存します。

## 習慣のライフサイクル

`habits`は現在状態、`habit_active_periods`は過去を含む利用区間を保持します。

現在状態:

- `is_active=true`, `archived_at=null`: 利用中
- `is_active=false`, `archived_at=<終了日時>`: 終了済み

有効期間:

- `started_on`: 利用を開始した日
- `ended_on`: 利用を終了した日。継続中は`null`
- 開始日・終了日はどちらも有効期間へ含む
- 停止中の日付はレポートの分母へ含めない

終了操作は物理削除ではありません。習慣本体・有効期間・曜日設定期間・過去の達成記録を保持します。

再開時は次を検証します。

- アクティブ習慣が20件未満
- 同名アクティブ習慣が存在しない
- 対象が終了済み

再開時は新しい開放区間を追加します。同日に終了・再開した場合は、日単位の停止期間が存在しないため直前区間を再オープンします。

## 習慣の対象曜日

曜日設定は`habit_schedule_periods`へ適用期間として保存します。

```text
7月1日〜9日: 毎日
7月10日〜: 月・水・金
```

- 設定変更は保存日から適用
- 変更前の曜日設定を履歴として保持
- 対象外曜日は達成率の分子・分母へ含めない
- 対象外曜日の新しい達成記録はサーバー側でも拒否
- 終了済み習慣も曜日を変更でき、再開後に利用

DB内部では月曜0〜日曜6を7ビットのマスクで保存します。バックアップJSONでは可読な曜日配列として出力します。

## 既存SQLiteの自動移行

旧DBでは、起動時に軽量マイグレーションを順番に実行します。

1. `habits.archived_at`がなければ追加
2. 終了済み習慣は`updated_at`から終了日時を補完
3. `habit_active_periods`がなければ作成
4. 既存習慣ごとに初期有効期間を生成
5. `habit_schedule_periods`がなければ作成
6. 既存習慣ごとに作成日からの毎日設定を生成

移行処理は冪等です。既存ID、習慣名、達成記録は変更しません。

移行前に保存されていない過去の停止区間や曜日変更履歴は推測して復元できません。

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

確認・操作できる内容:

- 達成・未達成・対象外
- 今日を含む過去日の達成追加・取り消し
- 対象日の対象習慣を一括達成
- 指定日の全達成記録を一括取り消し
- 選択した習慣だけを一括達成・一括取り消し
- 直前の達成操作を元に戻すUndo
- 達成数・対象件数・達成率
- 全対象習慣を達成した日数
- 日別カレンダー
- 習慣別達成日数
- 選択期間内の最長連続値
- 終了済み習慣の過去実績
- 停止期間を除外した対象日数
- その時点の曜日設定を反映した対象日数

レポートは`habit_active_periods`と`habit_schedule_periods`を参照します。

```text
達成対象 = 有効期間内 AND 曜日設定期間内 AND 対象曜日
```

移行途中などで履歴が存在しない場合に限り、既存項目と毎日設定による互換判定へフォールバックします。

## 過去日の習慣達成編集

日別履歴から、選択日の達成状態を修正できます。

```text
POST /habits/{habit_id}/completion
```

フォーム項目:

```text
target_date=YYYY-MM-DD
completed=true|false
```

- 対象日かつ未達成: `達成にする`
- 達成済み: `達成を取り消す`
- 対象曜日外で記録なし: 操作なし
- 対象外の既存記録: 取り消しだけ可能
- 終了済み習慣でも、その日に有効だった場合は編集可能

達成追加時は次をすべて確認します。

```text
対象日 <= 今日
AND 有効期間内
AND 曜日設定期間内
AND 対象曜日
```

過去日編集はトグルではなく、希望する最終状態を明示するため、同じリクエストを再送しても状態が反転しません。

既存の不整合記録を修復できるよう、取り消しは対象曜日外・有効期間外の記録にも利用できます。ただし未来日の編集は拒否します。

成功後は選択日の日別履歴へ303リダイレクトします。リダイレクト先はサーバー側で固定生成します。

### 全件一括操作

```text
POST /habits/completions/bulk
```

フォーム項目:

```text
target_date=YYYY-MM-DD
action=complete_expected|clear_all
```

- `complete_expected`: 指定日に達成対象だった未達成習慣だけを一括追加
- `clear_all`: 指定日の全達成記録を不整合記録も含めて一括削除
- 達成記録本体は1操作につき1回のコミット
- 同じ操作を再送しても最終状態が変わらない
- 一括取り消しは送信前に確認ダイアログを表示

全件一括達成・一括取り消しは、単件更新処理をループせず専用サービスで処理します。

### 選択一括操作

```text
POST /habits/completions/selected
```

フォーム項目:

```text
target_date=YYYY-MM-DD
completed=true|false
habit_ids=<習慣ID>（複数指定）
```

- 選択した項目だけを達成または取り消し
- 達成追加では、全選択項目が指定日の対象習慣であることを検証
- 取り消しでは、選択した既存記録だけを削除
- 選択なし・重複・不正IDを拒否
- 未知IDを含む場合は404
- 1件でも不正な選択があれば部分更新しない
- 達成記録本体の追加・削除は1回のコミット
- JavaScriptなしでも利用可能

詳細:

- [`HABIT_REPORTS.md`](./HABIT_REPORTS.md)
- [`HABIT_BULK_COMPLETION.md`](./HABIT_BULK_COMPLETION.md)

## 習慣達成Undo

ダッシュボードと習慣日別履歴の達成操作後に、直前1操作を10分以内で元へ戻せます。

```text
GET  /habits/completions/undo?target_date=YYYY-MM-DD
POST /habits/completions/undo
```

対象:

- ダッシュボードの当日トグル
- 単件達成・取り消し
- 全件一括達成・取り消し
- 選択一括達成・取り消し

安全条件:

- ランダムトークンが一致する
- 有効期限内
- 現在の対象日達成集合が操作直後集合と完全一致する
- 操作前集合の習慣が存在する

後続変更がある場合は409で拒否し、最新状態を上書きしません。曜日設定変更・習慣終了・再開では保存中のUndoを失効させます。

達成記録本体は従来の1コミットで確定し、Undoメタデータは短命な別Sessionへbest-effort保存します。Undo保存に失敗しても達成操作は維持します。復元時は、達成記録の置換とUndo消費を同じコミットで行います。

Undo通知の表示にはJavaScriptを使用しますが、復元条件はサーバー側で再検証します。

詳細は[`HABIT_COMPLETION_UNDO.md`](./HABIT_COMPLETION_UNDO.md)を参照してください。

## 時間記録CSV

```text
/exports/time-entries.csv?target_month=2026-07
```

- UTF-8 BOM付き
- CSV特殊文字の標準エスケープ
- CSV数式注入対策
- `Cache-Control: no-store`
- `X-Content-Type-Options: nosniff`

## 習慣レポートCSV

```text
/habits/weekly.csv?target_date=2026-07-23
/habits/monthly.csv?target_month=2026-07
```

- 週次・月次画面と同じ集計結果を使用
- 概要・日別集計・習慣別集計の3セクション
- 現在期間の未来日は`未到来`、数値列は空欄
- UTF-8 BOM・CRLF
- CSV数式注入対策
- `Cache-Control: no-store`
- `X-Content-Type-Options: nosniff`

詳細は[`HABIT_REPORT_CSV.md`](./HABIT_REPORT_CSV.md)を参照してください。

## JSONバックアップ

```bash
python -m app.backup_export
```

既定出力先:

```text
~/HomePanelBackups/home-panel-backup-YYYYMMDDTHHMMSSZ.json
```

現在生成する形式はスキーマv5です。

- v1: ToDo・日別メモ・時間記録
- v2: v1 + 習慣・習慣達成
- v3: v2 + 習慣の`archived_at`
- v4: v3 + `habit_active_periods`
- v5: v4 + `habit_schedule_periods`

旧DBを直接指定した場合、バックアップ前に習慣関連テーブルの互換移行を実行します。

`app_settings`内のPending Undoは一時的な操作補助情報のため、バックアップv5へ含めません。

## バックアップ検証

```bash
python -m app.backup_validate /path/to/home-panel-backup.json
```

検証CLIはv1〜v5を受け付けます。

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
- 曜日配列の型・範囲・重複
- 曜日設定期間の参照・重複・交差
- 開放区間数の整合性
- 達成記録が有効期間・曜日設定期間・対象曜日内にあること
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
- 対象曜日: 月曜0〜日曜6から1つ以上、重複・範囲外を拒否
- 曜日変更: 変更日の達成記録と矛盾する変更を拒否
- 過去日の達成追加: 未来日、有効期間外、停止期間、対象曜日外を拒否
- 達成状態: `true` / `false`だけ許可
- 達成全件一括操作: `complete_expected` / `clear_all`だけ許可
- 達成選択一括操作: 1件以上の正の整数ID、重複なし、既知ID、達成追加時は全件対象内
- Undo状態取得: 厳密な日付形式
- Undo復元: 16〜128文字のトークン、保存トークン一致、期限・状態・参照整合性
- 履歴・集計・CSV: 日付・月形式を厳密検証し未来期間を拒否
- ダッシュボード設定: 未登録カード、重複、欠落、全非表示を拒否

## ディレクトリ構成

```text
home-panel-py/
├─ app/
│  ├─ main.py
│  ├─ db.py
│  ├─ migrations.py
│  ├─ dashboard_cards.py
│  ├─ habit_schedule.py
│  ├─ habit_completion.py
│  ├─ habit_selected_completion.py
│  ├─ habit_completion_undo.py
│  ├─ habit_undo_routes.py
│  ├─ habit_report.py
│  ├─ habit_report_routes.py
│  ├─ habit_report_csv.py
│  ├─ csv_export.py
│  ├─ backup_export.py
│  ├─ backup_validate.py
│  ├─ models/
│  ├─ schemas/
│  ├─ crud/
│  ├─ templates/
│  │  ├─ cards/
│  │  ├─ habit_schedule_form.html
│  │  ├─ habit_manage.html
│  │  ├─ habit_history.html
│  │  ├─ habit_weekly.html
│  │  └─ habit_monthly.html
│  └─ static/
│     ├─ habit_undo.js
│     └─ habit_undo.css
├─ tests/
├─ BACKUP.md
├─ DASHBOARD.md
├─ HABITS.md
├─ HABIT_SCHEDULES.md
├─ HABIT_REPORTS.md
├─ HABIT_BULK_COMPLETION.md
├─ HABIT_COMPLETION_UNDO.md
├─ HABIT_REPORT_CSV.md
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
- 過去日の達成追加・取り消し・冪等性
- 対象習慣の全件一括達成・全達成記録の一括取り消し
- 選択した習慣だけの一括達成・一括取り消し
- 未選択習慣を変更しないこと
- 対象外・未知・重複・不正ID混在時に部分更新しないこと
- 全件・選択一括操作の対象曜日・停止期間・終了済み期間判定
- 全件・選択一括操作による不整合記録の修復
- 一括操作の再送・コミット回数・表示条件
- 直前操作のUndo保存・置き換え・復元・消費
- Undoの期限切れ・トークン不一致・後続変更・習慣欠落
- Undoによる不整合記録の操作前状態復元
- 曜日変更・終了・再開によるUndo失効
- Undo状態API・安全な戻り先・no-store・nosniff
- Undo通知用JavaScript・CSS・画面プレースホルダー
- 期間テーブルがない旧形式習慣の単件・一括達成互換
- 終了済み習慣の有効期間内編集
- 終了後・停止期間・対象曜日外の達成追加拒否
- 不整合な達成記録の取り消し
- 習慣名編集・終了済み一覧・再開
- `archived_at`移行
- 習慣有効期間の作成・終了・再開・同日再開
- 曜日マスク変換と表示
- 曜日設定期間の作成・変更・同日再変更
- 対象外曜日の達成拒否と分母除外
- 過去設定を保持した日別・週次・月次集計
- 旧SQLiteからの有効期間・毎日設定生成と冪等性
- 時間記録CSVエクスポート
- 習慣の週次・月次CSVエクスポート
- JSONバックアップv5生成
- v1〜v5検証
- 有効期間・曜日設定期間・達成記録の不整合検出
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

pytest失敗時だけ、短いトレースバックを含む`pytest-failure-log`を3日間のActionsアーティファクトとして保存します。

## Swapyのライセンスに関する注意

Swapy 1.0.5はGPL-3.0または商用ライセンスで提供されています。

継続利用する前に、プロジェクトをGPL-3.0互換ライセンスで公開するか、商用ライセンスを利用するかを決定してください。方針未確定のまま商用・非公開用途へ展開しないでください。

## 今後の拡張候補

- 曜日を固定しない週N回・隔週・月次スケジュール
- 複数日一括編集・月次カレンダーからの直接編集
- 有効期間・曜日設定期間の手動編集
- 日別履歴CSV・年次集計
- 複数段階Undo・Redo
- キーボード操作によるカード並び替え
- ダッシュボードの表示密度・テーマ設定
- JSONバックアップからの安全な復元
- 週次・月次集計のカテゴリ積み上げ表示
- 操作履歴・監査ログ
- 認証・ユーザー分離
- タイムゾーン設定

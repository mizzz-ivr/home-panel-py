# home-panel-py

ローカルPCで動かす、個人用のダッシュボードです。  
今日のToDo・メモ・作業時間・習慣を1画面で管理し、日別・週次・月次の振り返りやデータ出力も行えます。

## プロジェクト概要

- 目的: 日々のタスク・メモ・作業時間・継続習慣をまとめて管理する
- 想定利用: 個人利用・ローカル起動
- データ保存: SQLite
- 方針: 既存機能への影響を抑えながら、小さな単位で拡張する

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
- 当日合計
- カテゴリ別合計

### 習慣トラッカー

- 習慣の追加
- 今日の達成・取り消し
- 今日の達成件数
- 現在の連続達成日数
- 履歴を残したまま習慣を終了
- アクティブ習慣は最大20件

詳細は[`HABITS.md`](./HABITS.md)を参照してください。

### 履歴・集計

- 日付を指定した日別履歴
- 月曜始まりの週次集計
- 月間カレンダー形式の月次集計
- 合計時間・記録件数・記録日数・カテゴリ別合計
- 未来日・不正日付の拒否

現時点の履歴・週次・月次集計はメモと時間記録が対象です。習慣の履歴集計は今後の拡張対象です。

### エクスポート・バックアップ

- 月単位の時間記録CSV
- ToDo・メモ・時間記録・習慣のJSONバックアップCLI
- JSONバックアップの構造・件数・参照整合性・SHA-256検証CLI
- バックアップスキーマv1・v2の検証互換

### ダッシュボード設定

- Swapyによるカード並び替え
- カードごとの表示・非表示
- 並び順と表示設定のSQLite保存
- 設定の初期化
- 旧localStorage配置のサーバー設定への自動移行
- 新カード追加時の既存設定補完
- 設定駆動のカード登録基盤

## 使用技術

- Python
- FastAPI
- Jinja2
- SQLAlchemy
- SQLite
- Pydantic
- pytest
- Swapy 1.0.5（CDN）
- GitHub Actions

## Swapyのライセンスに関する注意

Swapy 1.0.5はGPL-3.0または商用ライセンスで提供されています。  
継続利用する前に、プロジェクト全体をGPL-3.0互換ライセンスで公開するか、Swapyの商用ライセンスを利用するかを決定してください。

ライセンス方針が未確定のまま、商用・非公開用途へ展開しないでください。

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
- 日別履歴: <http://127.0.0.1:8000/history>
- 週次集計: <http://127.0.0.1:8000/weekly>
- 月次集計: <http://127.0.0.1:8000/monthly>
- 時間記録CSV: <http://127.0.0.1:8000/exports/time-entries.csv>

初回起動時に`home_panel.db`が自動作成されます。  
再起動後もToDo・メモ・時間記録・習慣・ダッシュボード設定は保持されます。

## 時間記録カテゴリ

登録時に次の固定カテゴリから選択します。

- 学習
- 作業
- 個人開発
- その他

カテゴリを送信しない既存クライアントは、従来どおり「作業」として保存されます。

## 習慣トラッカー

習慣本体と日次達成記録は別テーブルで管理します。

- 習慣名は1〜100文字
- 空白のみは不可
- 同名のアクティブ習慣は不可
- 同じ習慣・同じ日付の達成記録は1件だけ
- 「終了」は物理削除ではなくアーカイブ
- 今日が未達でも、昨日まで連続していれば継続日数を維持

データテーブル:

- `habits`
- `habit_completions`

詳細な仕様、連続日数の計算、エラー時の挙動は[`HABITS.md`](./HABITS.md)を参照してください。

## 日別履歴

`/history`は当日を表示します。`target_date`で日付を指定できます。

```text
/history?target_date=2026-07-21
```

- `YYYY-MM-DD`形式のみ
- 未来日は400
- メモ、時間記録、合計時間、件数、カテゴリ別合計を表示
- ToDoと習慣は現時点では対象外
- 読み取り専用

## 週次集計

```text
/weekly?target_date=2026-07-23
```

- 指定日を含む月曜日〜日曜日
- 合計時間、件数、記録日数、カテゴリ別・日別合計
- 現在週の未来日は集計対象外
- 日別履歴への導線
- 読み取り専用

## 月次集計

```text
/monthly?target_month=2026-07
```

- `YYYY-MM`形式のみ
- 月初〜月末を対象
- 合計時間、件数、記録日数、記録日平均
- カテゴリ別合計と日別カレンダー
- 現在月の未来日は集計対象外
- 読み取り専用

## 時間記録CSV

```text
/exports/time-entries.csv?target_month=2026-07
```

- 日付・カテゴリ・時間・メモ・登録日時を出力
- UTF-8 BOM付き
- CSV標準の特殊文字エスケープ
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

現在生成するバックアップはスキーマv2です。

- v1: ToDo・日別メモ・時間記録
- v2: v1に習慣・習慣達成記録を追加

`app_settings`に保存するダッシュボード表示設定は運用設定として扱い、現時点ではバックアップ対象外です。

詳細は[`BACKUP.md`](./BACKUP.md)を参照してください。

## バックアップ検証

```bash
python -m app.backup_validate /path/to/home-panel-backup.json
```

検証CLIはスキーマv1とv2を受け付けます。

主な検証:

- 必須項目と未知項目
- レコード件数
- ID重複
- 入力制約
- 日付・UTC日時
- 習慣達成から習慣への参照
- 同じ習慣・同じ日付の重複
- SHA-256

既知のSHA-256と照合する場合:

```bash
python -m app.backup_validate /path/to/home-panel-backup.json \
  --expected-sha256 <64桁のSHA-256>
```

## ダッシュボード設定

設定API:

- `GET /api/dashboard/preferences`
- `PUT /api/dashboard/preferences`
- `DELETE /api/dashboard/preferences`

保存値:

```json
{
  "order": ["todo", "memo", "time", "habits"],
  "hidden": []
}
```

仕様:

- `app_settings`テーブルの`dashboard.preferences.v1`キーへJSON保存
- 並び順には登録済みカードを重複なくすべて指定
- 非表示には登録済みカードだけ指定
- 最低1枚は表示
- 不正なDB保存値は既定設定へフォールバック
- 新カード追加時は既存順序・非表示を維持して不足カードを末尾補完
- API応答は`Cache-Control: no-store`
- Swapy読み込み失敗時も通常の入力機能は利用可能
- 旧`home-panel:dashboard-layout:v1` localStorage値は、不足カードを補完して一度だけ移行

カード追加手順と設計上のルールは[`DASHBOARD.md`](./DASHBOARD.md)を参照してください。

## 入力バリデーション

- ToDo
  - 1〜255文字
  - 空文字・空白のみは不可
  - 存在しないIDは404
- メモ
  - 5000文字以内
- 時間記録
  - カテゴリは固定4種類
  - 時間は1〜1440分
  - メモは255文字以内
- 習慣
  - 1〜100文字
  - 空白・同名・21件目を拒否
  - 存在しない・終了済みIDは404
- 履歴・集計
  - 日付・月形式を厳密検証
  - 未来日・未来月を拒否
- ダッシュボード設定
  - 未登録カード、重複、カード欠落、全非表示を拒否
  - 設定保存失敗時も入力機能を継続

## ディレクトリ構成

```text
home-panel-py/
├─ app/
│  ├─ main.py
│  ├─ db.py
│  ├─ dashboard_cards.py
│  ├─ csv_export.py
│  ├─ backup_export.py
│  ├─ backup_validate.py
│  ├─ models/
│  │  ├─ app_setting.py
│  │  ├─ habit.py
│  │  ├─ task.py
│  │  ├─ memo.py
│  │  └─ time_entry.py
│  ├─ schemas/
│  │  ├─ dashboard.py
│  │  ├─ habit.py
│  │  ├─ task.py
│  │  ├─ memo.py
│  │  └─ time_entry.py
│  ├─ crud/
│  │  ├─ app_setting.py
│  │  ├─ habit.py
│  │  ├─ task.py
│  │  ├─ memo.py
│  │  └─ time_entry.py
│  ├─ templates/
│  │  ├─ cards/
│  │  ├─ dashboard.html
│  │  ├─ history.html
│  │  ├─ weekly.html
│  │  └─ monthly.html
│  └─ static/
│     ├─ style.css
│     ├─ dashboard.css
│     ├─ monthly.css
│     └─ app.js
├─ tests/
├─ BACKUP.md
├─ DASHBOARD.md
├─ HABITS.md
├─ requirements.txt
└─ README.md
```

## テスト

```bash
pytest -q
```

主な確認範囲:

- ToDo・メモ・時間記録
- 習慣追加・達成・取り消し・終了・連続日数・上限
- 日別・週次・月次集計
- CSVエクスポート
- JSONバックアップv2生成とv1・v2検証
- ダッシュボード設定の保存・非表示・順序・初期化・新カード補完
- 不正設定と壊れたDB設定値のフォールバック
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

## 今後の拡張候補

- 習慣名の編集、終了済み習慣の一覧・再開
- 習慣の曜日・頻度設定
- 習慣の日別・週次・月次集計
- キーボード操作によるカード並び替え
- ダッシュボードの表示密度・テーマ設定
- JSONバックアップからの安全な復元
- 週次・月次集計のカテゴリ積み上げ表示
- カード単位の権限・更新頻度・キャッシュ設定

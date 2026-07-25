# home-panel-py

ローカルPCで動かす、個人用のダッシュボードです。  
今日のToDo・メモ・作業時間を1画面で管理し、日別・週次・月次の振り返りやデータ出力も行えます。

## プロジェクト概要

- 目的: 日々のタスク・メモ・作業時間をまとめて管理する
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

### 履歴・集計

- 日付を指定した日別履歴
- 月曜始まりの週次集計
- 月間カレンダー形式の月次集計
- 合計時間・記録件数・記録日数・カテゴリ別合計
- 未来日・不正日付の拒否

### エクスポート・バックアップ

- 月単位の時間記録CSV
- ToDo・メモ・時間記録のJSONバックアップCLI
- JSONバックアップの構造・件数・SHA-256検証CLI

### ダッシュボード設定

- Swapyによるカード並び替え
- カードごとの表示・非表示
- 並び順と表示設定のSQLite保存
- 設定の初期化
- 旧localStorage配置のサーバー設定への自動移行
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
再起動後もToDo・メモ・時間記録・ダッシュボード設定は保持されます。

## 時間記録カテゴリ

登録時に次の固定カテゴリから選択します。

- 学習
- 作業
- 個人開発
- その他

カテゴリを送信しない既存クライアントは、従来どおり「作業」として保存されます。

## 日別履歴

`/history`は当日を表示します。`target_date`で日付を指定できます。

```text
/history?target_date=2026-07-21
```

- `YYYY-MM-DD`形式のみ
- 未来日は400
- メモ、時間記録、合計時間、件数、カテゴリ別合計を表示
- ToDoは日付・完了日を保持していないため対象外
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

バックアップの詳細は[`BACKUP.md`](./BACKUP.md)を参照してください。

現在のバックアップスキーマv1は、ToDo・日別メモ・時間記録を対象とします。  
`app_settings`に保存するダッシュボード表示設定は運用設定として扱い、現時点ではバックアップ対象外です。

## バックアップ検証

```bash
python -m app.backup_validate /path/to/home-panel-backup.json
```

検証成功時にレコード件数とSHA-256を表示します。

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
  "order": ["todo", "memo", "time"],
  "hidden": []
}
```

仕様:

- `app_settings`テーブルの`dashboard.preferences.v1`キーへJSON保存
- 並び順には登録済みカードを重複なくすべて指定
- 非表示には登録済みカードだけ指定
- 最低1枚は表示
- 不正なDB保存値は既定設定へフォールバック
- API応答は`Cache-Control: no-store`
- Swapy読み込み失敗時も通常の入力機能は利用可能
- 旧`home-panel:dashboard-layout:v1` localStorage値は、サーバー設定が未保存の場合に限り一度だけ移行

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
│  │  ├─ task.py
│  │  ├─ memo.py
│  │  └─ time_entry.py
│  ├─ schemas/
│  │  ├─ dashboard.py
│  │  ├─ task.py
│  │  ├─ memo.py
│  │  └─ time_entry.py
│  ├─ crud/
│  │  ├─ app_setting.py
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
├─ requirements.txt
└─ README.md
```

## テスト

```bash
pytest -q
```

主な確認範囲:

- ToDo・メモ・時間記録
- 日別・週次・月次集計
- CSVエクスポート
- JSONバックアップ生成・検証
- ダッシュボード設定の保存・非表示・順序・初期化
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

- キーボード操作によるカード並び替え
- ダッシュボードの表示密度・テーマ設定
- ダッシュボード設定を含むバックアップスキーマv2
- JSONバックアップからの安全な復元
- 週次・月次集計のカテゴリ積み上げ表示
- カード単位の権限・更新頻度・キャッシュ設定

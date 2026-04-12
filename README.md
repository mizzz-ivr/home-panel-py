# home-panel-py

ローカルPCで動かす、個人用のシンプルな1画面ダッシュボードです。  
「今日の行動をまとめて見て、少し記録できる」ことだけに絞ったMVPを実装しています。

## プロジェクト概要

- 目的: 日々のタスク・メモ・作業時間を1画面で管理する
- 想定利用: 個人利用（ローカル起動）
- 初版方針: 小さく完成させる（機能を広げすぎない）

## 主な機能

- 今日の日付表示
- ToDo管理
  - タスク一覧表示
  - タスク追加
  - 完了切り替え
  - 削除
- 今日のメモ
  - 当日分メモの表示
  - 保存/更新
- 学習/作業時間記録
  - 分単位で追加
  - 当日合計分の表示
- SQLite永続化

## 使用技術

- Python
- FastAPI
- Jinja2テンプレート
- SQLAlchemy
- SQLite
- pytest

## セットアップ手順

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 起動方法

```bash
uvicorn app.main:app --reload
```

起動後、ブラウザで以下にアクセスしてください。

- <http://127.0.0.1:8000>

初回起動時に `home_panel.db`（SQLite）が自動作成されます。  
再起動してもデータ（ToDo / メモ / 時間記録）は保持されます。

## 入力バリデーションとエラーハンドリング

- ToDo
  - 空文字や空白のみのタスクは登録不可
  - 存在しないタスクIDの完了切り替え/削除は 404 + 画面内エラーメッセージ
- 今日のメモ
  - 5000文字以内
  - 空で保存すると当日のメモをクリア
- 学習/作業時間
  - `minutes` は 1〜1440 の整数のみ
  - `note` は 255文字以内

## ディレクトリ構成

```text
home-panel-py/
├─ app/
│  ├─ main.py
│  ├─ db.py
│  ├─ models/
│  │  ├─ task.py
│  │  ├─ memo.py
│  │  └─ time_entry.py
│  ├─ schemas/
│  │  ├─ task.py
│  │  ├─ memo.py
│  │  └─ time_entry.py
│  ├─ crud/
│  │  ├─ task.py
│  │  ├─ memo.py
│  │  └─ time_entry.py
│  ├─ templates/
│  │  └─ dashboard.html
│  └─ static/
│     ├─ style.css
│     └─ app.js
├─ tests/
│  └─ test_app.py
├─ requirements.txt
└─ README.md
```

## テスト実行

```bash
pytest -q
```

主な確認内容:

- 正常系: ToDo追加/完了切替/削除、当日メモ保存、時間追加と合計表示
- 異常系: 空ToDo、不正な minutes、長すぎるメモ、存在しないID操作

## 今後の拡張候補

- 日付を指定した履歴表示
- time_entries の category 選択対応
- UI改善（入力補助、視認性向上）
- 簡易バックアップ/エクスポート

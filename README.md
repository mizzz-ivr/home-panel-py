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
- ダッシュボードカードの並び替え
  - Swapyのドラッグ&スワップを利用
  - カードヘッダーの「並び替え」ハンドルから操作
  - 並び順はブラウザのlocalStorageへ保存
  - 「配置を初期化」で既定順へ戻せる
- SQLite永続化

## 使用技術

- Python
- FastAPI
- Jinja2テンプレート
- SQLAlchemy
- SQLite
- pytest
- Swapy 1.0.5（CDN）
- GitHub Actions

## Swapyのライセンスに関する注意

Swapy 1.0.5 は GPL-3.0 または商用ライセンスで提供されています。
このリポジトリで継続利用する前に、プロジェクト全体をGPL-3.0互換ライセンスで公開するか、Swapyの商用ライセンスを利用するかを決定してください。
ライセンス方針が未確定のまま、商用・非公開用途へ展開しないでください。

## セットアップ手順

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShellの場合:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
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

## カード配置の保存仕様

- Swapyは `https://unpkg.com/swapy@1.0.5/dist/swapy.min.js` から読み込みます
- 並び順は `home-panel:dashboard-layout:v1` キーでlocalStorageへ保存します
- 保存対象はToDo・今日のメモ・学習/作業時間の3カードです
- 不正な保存値を検出した場合は既定順へ戻します
- CDNの読み込みに失敗しても、通常の入力・保存機能は引き続き利用できます
- ブラウザや端末をまたいだ同期は行いません

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
- カード並び替え
  - localStorageの読み書き失敗時は画面操作を継続
  - Swapyの読み込み失敗時は並び替えハンドルを非表示

## ディレクトリ構成

```text
home-panel-py/
├─ .github/
│  └─ workflows/
│     └─ ci.yml
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
- UI構造: Swapy用slot/item属性、固定バージョンのCDN読込、JavaScript配信

## GitHub Actions

`.github/workflows/ci.yml` は `main` へのpush・pull request・手動実行で動作します。

品質チェック内容:

1. Python 3.12のセットアップ
2. `requirements.txt` の依存関係インストール
3. `pip check` による依存関係の整合性確認
4. `compileall` によるPython構文チェック
5. `node --check` によるJavaScript構文チェック
6. FastAPIアプリのimport確認
7. pytest実行

このプロジェクトにはフロントエンドのビルド工程がないため、`compileall`・JavaScript構文チェック・アプリimport・pytestをビルドエラー相当の品質ゲートとして扱います。

## 今後の拡張候補

- 日付を指定した履歴表示
- time_entries の category 選択対応
- カード配置のサーバ保存
- キーボード操作によるカード並び替え
- 簡易バックアップ/エクスポート

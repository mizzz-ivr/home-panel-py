# ダッシュボード拡張ガイド

## 目的

ダッシュボードカードの追加・非表示・並び替えを、カードごとの条件分岐を増やさず拡張できるようにするための設計ルールです。

## 構成

### カード定義

`app/dashboard_cards.py`の`DASHBOARD_CARDS`がカード登録の正本です。

```python
DASHBOARD_CARDS = (
    DashboardCardDefinition("todo", "ToDo", "cards/todo.html"),
    DashboardCardDefinition("memo", "今日のメモ", "cards/memo.html"),
    DashboardCardDefinition("time", "学習/作業時間", "cards/time.html"),
)
```

各定義は次を持ちます。

- `card_id`: 永続化に使用する安定した識別子
- `title`: 設定画面とカード見出しに使用する表示名
- `template`: カード本体のJinja2部分テンプレート

### 部分テンプレート

カード本体は`app/templates/cards/`に配置します。

カードのルート要素には、次の属性が必要です。

```html
<section
  class="card dashboard-card"
  data-swapy-item="{{ card.card_id }}"
>
```

並び替えを許可する場合、カード内に`data-swapy-handle`を持つボタンを配置します。

### 設定保存

`app_settings`は、アプリケーション全体の設定をJSON文字列として保存する汎用テーブルです。

ダッシュボード設定は次のキーを使用します。

```text
dashboard.preferences.v1
```

保存形式:

```json
{
  "order": ["todo", "memo", "time"],
  "hidden": []
}
```

設定値を変更する場合は、既存キーの意味を変更せず、新しいバージョンのキーを追加します。

例:

```text
dashboard.preferences.v2
```

## カード追加手順

### 1. 安定したカードIDを決める

カードIDは一度公開した後に変更しないでください。

良い例:

```text
weather
quick-links
system-status
```

避ける例:

```text
card1
new-card
temp
```

カードIDを変更すると、保存済みの並び順・非表示設定との互換性が失われます。

### 2. 部分テンプレートを追加する

例:

```text
app/templates/cards/quick_links.html
```

カード固有の表示・フォームだけを記述し、ページ全体のHTMLや共通スクリプトを含めないでください。

### 3. カード定義へ登録する

```python
DashboardCardDefinition(
    "quick-links",
    "クイックリンク",
    "cards/quick_links.html",
)
```

既存ユーザーの設定に新しいカードが含まれない場合の移行方針を同時に検討してください。

現行v1は登録済みカードの完全な並び順を要求します。そのため、新しいカード追加時には以下のいずれかが必要です。

- 設定キーをv2へ上げる
- v1保存値を読み込み時に新カード付きへ移行する
- DBマイグレーションで保存値を更新する

推奨は、互換変換が単純な場合は読み込み時移行、設定構造自体を変える場合はキーのバージョンアップです。

### 4. 必要なデータを用意する

カードがサーバーデータを必要とする場合は、`render_dashboard()`でテンプレートコンテキストへ追加します。

次の責務を混在させないでください。

- SQL取得: `app/crud/`
- 入力検証: `app/schemas/`
- カード登録情報: `app/dashboard_cards.py`
- 表示: `app/templates/cards/`
- 画面制御: `app/static/app.js`

### 5. テストを追加する

最低限、以下を確認します。

- 既定表示に追加されること
- 並び順保存後も表示されること
- 非表示設定が機能すること
- 不正なカードIDが拒否されること
- 設定初期化後に既定表示へ戻ること
- 既存カードの入力・保存機能に影響がないこと
- スマートフォン幅でレイアウトが崩れないこと

## 設定API

### 取得

```http
GET /api/dashboard/preferences
```

### 更新

```http
PUT /api/dashboard/preferences
Content-Type: application/json
```

```json
{
  "order": ["time", "todo", "memo"],
  "hidden": ["memo"]
}
```

### 初期化

```http
DELETE /api/dashboard/preferences
```

APIは次を検証します。

- 既知カードをすべて含むこと
- 並び順に重複がないこと
- 非表示カードが既知カードであること
- 非表示カードに重複がないこと
- 最低1枚を表示すること

## 旧localStorageからの移行

旧バージョンでは、次のキーへカード配置を保存していました。

```text
home-panel:dashboard-layout:v1
```

サーバー設定が未保存の場合のみ、JavaScriptが旧配置を読み取り、設定APIへ保存します。

移行成功後は旧キーを削除します。

移行失敗時は既定配置で表示し、通常のToDo・メモ・時間記録機能は継続します。

## 障害時の方針

- DB内の設定JSONが壊れている: 既定設定へフォールバック
- 設定APIが失敗する: 現在の画面操作を継続し、再読み込み後は保存前の状態へ戻す
- Swapy CDNが失敗する: 並び替えだけ無効化し、カード内機能は継続
- 表示カードが1枚: Swapyを初期化しない
- 不正なAPI入力: DBへ保存せず400または422

## セキュリティ

現状はローカル個人利用を前提とし、認証・認可はありません。

外部公開する場合は、設定APIを含むすべての更新系ルートに対して次を追加してください。

- 認証
- ユーザーごとの設定分離
- CSRF対策
- 操作ログ
- レート制限
- セッション管理
- HTTPS

## バックアップ

現行バックアップスキーマv1は、ToDo・日別メモ・時間記録だけを対象とします。

`app_settings`は操作環境の設定として扱い、現時点では対象外です。設定も移行したい場合は、既存v1の意味を変更せず、バックアップスキーマv2として追加してください。

## 今後の拡張例

汎用`app_settings`基盤を利用して、次の設定を追加できます。

- テーマ
- 表示密度
- 既定の集計期間
- ナビゲーション表示
- カードごとの更新間隔
- カードごとの折りたたみ状態
- 外部サービス接続設定

秘密情報やAPIキーは、平文JSONとして`app_settings`へ保存しないでください。秘密情報は環境変数、OSの資格情報ストア、専用の暗号化ストレージを使用します。

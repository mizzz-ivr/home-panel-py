# Today Focusカード仕様

## 目的

ToDo・習慣・時間記録に分散している「今日確認したい情報」をダッシュボード上でまとめ、個別カードを順番に確認しなくても当日の優先事項を把握できるようにします。

Today Focusは既存機能の状態を集約する読み取り専用カードです。状態更新の正本は従来のToDo・習慣・時間記録画面に残します。

## カードID

```text
focus
```

登録先:

```text
app/dashboard_cards.py
```

テンプレート:

```text
app/templates/cards/focus.html
```

スタイル:

```text
app/static/focus.css
```

## 表示内容

### 期限切れToDo

次をすべて満たすToDoを数えます。

- 未完了
- 期限あり
- 期限が今日より前

リンク先:

```text
/?todo_view=overdue&show_card=todo#todo-card
```

`show_card=todo`を付けるため、ToDoカードが非表示設定でも遷移先の画面だけ一時表示できます。

### 本日期限ToDo

次をすべて満たすToDoを数えます。

- 未完了
- 期限が今日

リンク先:

```text
/?todo_view=today&show_card=todo#todo-card
```

### 今日未達成の習慣

既存の`habit_crud.get_dashboard_summary()`が返す項目のうち、次を満たす習慣だけを対象にします。

```text
scheduled_today = true
completed_today = false
```

対象外曜日の習慣はToday Focusへ含めません。

リンク先:

```text
/habits/manage
```

個別プレビューは次へ遷移します。

```text
/habits/manage#habit-<ID>
```

### 今日の記録時間

既存ダッシュボードが取得している`total_minutes`と`entries`を再利用します。

- 60分未満: `35分`
- 60分以上: `1時間35分`
- 0分: `0分`

1日の時間目標が設定されている場合は、`daily_time_goal_status`も利用します。

未達成例:

```text
1時間35分
79%・残り25分
```

達成例:

```text
2時間30分
125%・目標達成
```

目標未設定時は従来どおり記録件数を表示します。

リンク先:

```text
/?show_card=time#time-card
```

`show_card=time`を付けるため、時間記録カードが非表示設定でも遷移先の画面だけ一時表示できます。

時間目標の詳細は[`DAILY_TIME_GOAL.md`](./DAILY_TIME_GOAL.md)を参照してください。

## 今日確認したい件数

次の合計を表示します。

```text
期限切れToDo
+ 本日期限ToDo
+ 今日未達成の対象習慣
```

未来期限ToDo、期限なしToDo、完了済みToDo、対象外曜日の習慣は含めません。

合計0件の場合は「今日の必須アクションは片付いています」と表示します。

時間記録は活動量の情報であり、「未完了アクション」ではないためこの件数へ含めません。時間目標が未達成でも件数へは加算しません。

## プレビュー

### 優先ToDo

期限切れ・本日期限ToDoを最大5件表示します。

表示順はダッシュボードが既に取得している`task_crud.list_tasks()`の順序をそのまま利用します。

そのためToday Focus独自の並び順は追加しません。

5件を超える場合は残件数だけを表示します。

### 未達成習慣

今日対象かつ未達成の習慣を最大5件表示します。

5件を超える場合は残件数だけを表示します。

## 更新操作を置かない理由

Today Focusには次のフォームを置きません。

- ToDo完了・削除
- 習慣達成・取り消し
- 時間記録追加
- 時間目標設定・解除

理由:

- ToDoクイックビューの表示状態維持を重複実装しない
- 習慣Undoの更新経路を増やさない
- 同じデータを複数カードから更新してエラー表示・競合処理を複雑化しない
- Today Focusを集約・ナビゲーション責務に限定する

時間目標は時間記録カードで設定します。

## DBアクセス

Today Focus独自のToDo・習慣・時間実績クエリは追加しません。

既存`render_dashboard()`がテンプレートへ渡している次を再利用します。

- `tasks`
- `habit_items`
- `habit_completed_today`
- `habit_total`
- `total_minutes`
- `entries`
- `today`
- `daily_time_goal_status`

時間目標機能では、`app_settings`から`daily_time_goal_minutes`を読むための設定取得が1回追加されます。その取得結果は時間記録カードとToday Focusで共有し、同じ設定をカードごとに再取得しません。

## ダッシュボード設定との互換性

新規環境の既定順:

```text
focus
todo
memo
time
habits
```

既存ユーザーが4カード時代の設定を保存している場合、既存順序と非表示状態を維持し、`focus`だけを末尾へ補完します。

例:

```json
{
  "order": ["time", "habits", "todo", "memo"],
  "hidden": ["memo"]
}
```

読み込み後:

```json
{
  "order": ["time", "habits", "todo", "memo", "focus"],
  "hidden": ["memo"]
}
```

保存済み配置を勝手に先頭へ移動しません。必要であればユーザーがSwapyで移動できます。

`show_card`による一時表示は、現在の`hidden`に含まれる既知カードIDだけを対象にします。未知の値ではカードを追加表示しません。

## レスポンシブ表示

- 通常幅: 指標4列、詳細2列
- 900px以下: 指標2列
- 640px以下: 指標・詳細とも1列

## セキュリティ・安全性

- Today Focus自体は読み取り専用
- Today Focus専用POSTルートなし
- 任意URLを受け取らない
- 保存データはJinja2の自動エスケープを維持
- ToDo遷移先のフィルタ値は固定値のみ
- `show_card`は既知の非表示カードIDとの一致時だけ利用
- DBスキーマ変更なし
- JSONバックアップ形式変更なし

## テスト観点

- 新規環境でToday Focusが先頭表示される
- 既存4カード設定へ末尾補完される
- 既存の順序・非表示状態を維持する
- Today Focus自体を非表示にできる
- 期限切れToDoの集計
- 本日期限ToDoの集計
- 未来・完了済みToDoを優先プレビューから除外
- 今日対象の未達成習慣だけを集計
- 達成済み習慣をプレビューから除外
- 当日時間を時間・分表記する
- 時間目標未設定時は記録件数を表示する
- 時間目標設定時は達成率・残り時間または達成状態を表示する
- 非表示の時間カードを`show_card=time`で一時表示できる
- 未知の`show_card`で追加カードを表示しない
- 0件時の完了メッセージ
- ToDoプレビュー最大5件
- Today Focus内に更新フォームが存在しない
- 既存ダッシュボード機能の回帰

## 対象外

- Today Focusから直接状態を更新する操作
- 習慣・ToDoへ重みを付けたスコア
- AIによる優先順位提案
- 通知・リマインダー
- 日次サマリーの永続保存
- ユーザーごとの集約

# Home Panel 定期バックアップ・世代管理

## 目的

`app.backup_rotate`は、OSのスケジューラから1回ずつ呼び出すためのバックアップサイクルCLIです。

1回の実行で次を行います。

1. SQLiteからJSONバックアップを作成
2. 作成したJSONを再読込
3. スキーマ・件数・参照整合性を検証
4. SHA-256を算出
5. 検証済みバックアップを指定世代数まで整理

スケジュール登録自体は、Windowsタスクスケジューラやcronなど、利用環境の機能を使用します。

## 基本コマンド

```bash
python -m app.backup_rotate
```

既定値:

```text
DB          = ./home_panel.db
保存先      = ~/HomePanelBackups
保持数      = 30
```

対象DB、保存先、保持数を指定する場合:

```bash
python -m app.backup_rotate \
  --database /path/to/home_panel.db \
  --backup-dir /path/to/HomePanelBackups \
  --keep 30
```

保持数は1〜3650の範囲です。

## 実行結果

成功時は次を標準出力へ表示します。

```text
バックアップを作成しました: /path/to/home-panel-backup-20260805T030000Z.json
SHA-256: <64桁のSHA-256>
削除した旧バックアップ: 1件
- 削除: /path/to/home-panel-backup-20260706T030000Z.json
```

自動管理しないファイルや、削除できなかったファイルは標準エラーへ警告を出します。

## 終了コード

| コード | 意味 |
|---:|---|
| 0 | バックアップ作成・検証・世代整理が完了 |
| 1 | DB、ファイル操作、作成後検証、旧ファイル削除の実行時エラー |
| 2 | 不正入力、既存ロック、不正な保存先、必須テーブル不足 |

スケジューラでは終了コードが0以外の場合にログを確認してください。

## バックアップ名

通常:

```text
home-panel-backup-YYYYMMDDTHHMMSSZ.json
```

同じ秒に再実行した場合:

```text
home-panel-backup-YYYYMMDDTHHMMSSZ-2.json
home-panel-backup-YYYYMMDDTHHMMSSZ-3.json
```

日時はUTCです。既存ファイルは上書きしません。

## 自動削除の条件

ファイル名が似ているだけでは削除しません。

削除対象になるには、次をすべて満たす必要があります。

- 名前が管理対象形式と完全一致する
- 通常ファイルである
- シンボリックリンクではない
- UTF-8 JSONとして読み込める
- Home Panelバックアップとして検証に成功する
- ファイル名のUTC日時とJSONの`exported_at`が秒単位で一致する
- 削除直前のSHA-256が、候補選定時と一致する

次のファイルは自動削除しません。

- JSONとして破損している
- バックアップ検証に失敗する
- ファイル名だけ変更され、`exported_at`と一致しない
- シンボリックリンク
- ディレクトリ
- `README.txt`など命名規則外のファイル

自動削除しなかった理由は警告へ出力します。内容を確認し、不要と判断できた場合だけ手動で削除してください。

## 保持数の考え方

`--keep 30`は、検証済みかつ管理対象と判定できたバックアップを新しい順に30件保持します。

破損ファイルや時刻不一致ファイルは保持数へ含めません。そのため、保存先の総ファイル数が30件を超える場合があります。

今回作成したバックアップが時刻の巻き戻りなどで削除候補に入った場合は、そのファイルを保護して保持します。この場合も一時的に保持数を超える可能性があります。

## 排他ロック

同時実行による重複作成や競合削除を防ぐため、保存先へ次を作成します。

```text
.home-panel-backup.lock
```

内容:

```text
pid=<プロセスID>
acquired_at=<UTC日時>
```

ロックが存在する場合、新しい処理は開始しません。

正常終了と例外終了では`finally`で削除します。ただし、OS強制終了、電源断、プロセス強制停止では残る場合があります。

### ロックが残った場合

1. 同じバックアップ処理が実行中でないことを確認
2. ロック内のPIDと取得日時を確認
3. 実行中プロセスが存在しない場合だけロックを削除
4. CLIを手動実行して正常完了を確認

確認せずにロックを削除すると、複数処理が同じ保存先を操作する可能性があります。

## Windowsタスクスケジューラ例

### 前提例

```text
プロジェクト  C:\apps\home-panel-py
Python        C:\apps\home-panel-py\.venv\Scripts\python.exe
DB            C:\apps\home-panel-py\home_panel.db
保存先        D:\HomePanelBackups
```

### 操作

1. タスクスケジューラを開く
2. 「基本タスクの作成」を選択
3. 毎日などの実行間隔を設定
4. 操作は「プログラムの開始」を選択
5. 次を設定

プログラム:

```text
C:\apps\home-panel-py\.venv\Scripts\python.exe
```

引数:

```text
-m app.backup_rotate --database C:\apps\home-panel-py\home_panel.db --backup-dir D:\HomePanelBackups --keep 30
```

開始場所:

```text
C:\apps\home-panel-py
```

### 確認

登録後は手動実行し、次を確認してください。

- 終了コードが0
- JSONファイルが作成された
- SHA-256がログへ出力された
- `.home-panel-backup.lock`が残っていない
- `python -m app.backup_validate <作成ファイル>`が成功する

## cron例

毎日3時に実行する例です。

```cron
0 3 * * * cd /opt/home-panel-py && .venv/bin/python -m app.backup_rotate --database /opt/home-panel-py/home_panel.db --backup-dir /srv/home-panel-backups --keep 30 >> /var/log/home-panel-backup.log 2>&1
```

cronの環境変数は対話シェルと異なることがあります。PythonとDB、保存先は絶対パスで指定することを推奨します。

## 初回運用確認

定期実行を開始する前に、手動で次を確認します。

```bash
python -m app.backup_rotate \
  --database /path/to/home_panel.db \
  --backup-dir /path/to/HomePanelBackups \
  --keep 30
```

作成されたファイルを検証します。

```bash
python -m app.backup_validate \
  /path/to/HomePanelBackups/home-panel-backup-YYYYMMDDTHHMMSSZ.json
```

別の空DBへ復元確認する場合:

```bash
python -m app.backup_restore \
  /path/to/HomePanelBackups/home-panel-backup-YYYYMMDDTHHMMSSZ.json \
  --database /path/to/restore-check.db
```

復元確認用DBには、存在しないパスまたは完全に空のDBだけを指定してください。

## 旧SQLiteを指定する場合

バックアップ作成前に、既存の習慣互換移行を実行します。

- `habits.archived_at`の追加
- 習慣有効期間テーブルの追加・補完
- 曜日設定期間テーブルの追加・補完

旧DBを初めて対象にする場合は、先にSQLiteファイル自体をコピーしてください。

## 保存先の推奨

- Git管理対象外のディレクトリ
- 公開Webディレクトリではない場所
- 利用ユーザーだけが読み書きできる場所
- DB本体とは異なるストレージ
- 可能であれば別ドライブまたは別端末へ追加コピー

同一PC・同一ドライブだけのバックアップでは、端末故障やストレージ故障には対応できません。

## バックアップ対象外

現在のJSONバックアップv5には次を含みません。

- `app_settings`
- ダッシュボードのカード順序・表示設定
- Pending Undo

## 未対応

- OSスケジューラへの自動登録
- S3などへのクラウド転送
- 暗号化
- 電子署名
- 保存容量を基準にした削除
- 日次・週次・月次を組み合わせるGFS方式
- メール・チャット通知
- 実行履歴DB

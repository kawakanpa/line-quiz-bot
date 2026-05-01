# コーディングスタイル

- Python 標準スタイル（PEP8）に従う
- 関数名・変数名はスネークケース（`send_quiz`, `user_id`）
- 定数は大文字スネークケース（`TODAY_FILE`, `CHANNEL_SECRET`）
- コメントは日本語で書く
- ログは `logger.info()` / `logger.error()` を使う（`print()` は使わない）
- 環境変数は `os.environ.get()` で取得し、コードに直接書かない

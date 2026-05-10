# LINE クイズボット — プロジェクトルール

## プロジェクト概要
中学生向け LINE 自動クイズ配信ボット。
Flask + LINE Messaging API v3 + Claude API 構成。
Heroku/Railway にデプロイ。

## 技術スタック
- Python / Flask
- LINE Messaging API v3 (`linebot.v3`)
- Claude API（問題生成）
- Heroku / Railway（デプロイ）

## コーディングルール
- 日本語コメント・ログメッセージを使う
- 環境変数は `.env` で管理、コードにハードコードしない
- `settings.json` はユーザー設定の永続化に使う（コミット対象外）
- `today_questions.json` は当日問題のキャッシュ（コミット対象外）

## 応答スタイル
- 日本語で回答する
- 説明は簡潔に、コードは最小限の変更で

## 削除禁止コード
以下は過去のバグ修正のため意図的に入れてあるコード。リファクタリング時も削除しないこと。

### `quiz.py` — LaTeX "rac" バグ対策
LLM が `\frac` を JSON 未エスケープで出力すると `\f` が改頁文字として解釈され、LINE に `rac` と表示される。

- `_call_groq` 内の `re.sub(r'(?<!\\)\\([fFtTbBrR][a-zA-Z]+)`, ...)`
  → JSONパース前に `\frac` 等を安全にエスケープする
- `_clean_latex` 先頭の `re.sub(r'\x0c([a-zA-Z]+)', ...)`
  → すり抜けた改頁文字の救済処理

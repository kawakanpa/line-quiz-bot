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

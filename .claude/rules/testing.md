# テスト方針

## 手動テスト
- `/send_quiz` エンドポイント：cron ジョブ経由で動作確認
- LINE Webhook：LINE Developers の検証ツールで確認
- 採点ロジック：`quiz.py` の `grade_and_format` に直接サンプル入力して確認

## 注意事項
- 本番の LINE ユーザー ID を使ったテストは最小限に
- Claude API 呼び出しはコストがかかるため、テスト時はモック or 問題数を減らす
- `today_questions.json` を手動で作成してテストすることも可能

# /project:deploy

デプロイ前チェックリストを確認してください：

1. `.env` に必要な環境変数が揃っているか確認
   - LINE_CHANNEL_SECRET
   - LINE_CHANNEL_ACCESS_TOKEN
   - ANTHROPIC_API_KEY
   - CRON_SECRET
   - SON_USER_ID
   - PARENT_USER_ID

2. `requirements.txt` が最新か確認

3. `Procfile` の起動コマンドを確認

4. デプロイコマンド例：
   ```
   git push heroku main
   # または
   railway up
   ```

5. デプロイ後に `/send_quiz` エンドポイントを手動テストして動作確認

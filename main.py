import os
import json
import logging
import re
from datetime import datetime
from flask import Flask, request, abort, jsonify
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
from dotenv import load_dotenv
from config import load_settings, save_settings
from quiz import (generate_daily_questions, format_question_message, grade_and_format,
                  generate_retry_questions, format_retry_message, grade_retry)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
CRON_SECRET = os.environ.get('CRON_SECRET')

handler = WebhookHandler(CHANNEL_SECRET)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

TODAY_FILE = 'today_questions.json'
WEEKDAY_MAP = {0: '月', 1: '火', 2: '水', 3: '木', 4: '金', 5: '土', 6: '日'}


# ── 今日の問題ファイル操作 ────────────────────────────

def get_today_data():
    if not os.path.exists(TODAY_FILE):
        return None
    with open(TODAY_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if data.get('date') != datetime.now().strftime('%Y-%m-%d'):
        return None
    return data


def save_today_data(questions):
    data = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'questions': questions,
        'answered': False,
        'retry_questions': None,
        'retry_round': 0,
        'mission_complete': False
    }
    with open(TODAY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_today_data(data):
    with open(TODAY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _push_to_parents(api, settings, text):
    """登録済みの全親アカウントにpush送信する"""
    for key in ('parent_user_id', 'parent2_user_id'):
        uid = settings.get(key)
        if uid:
            api.push_message(PushMessageRequest(
                to=uid, messages=[TextMessage(text=text)]))


# ── エンドポイント ────────────────────────────────────

@app.route('/')
def health():
    return 'Quiz Bot is running!'


@app.route('/cron')
def cron():
    """外部cronサービス（cron-job.org）から毎日12時に呼ばれる"""
    if request.args.get('token') != CRON_SECRET:
        abort(403)

    settings = load_settings()
    son_user_id = settings.get('son_user_id')
    if not son_user_id:
        logger.warning('息子のuser_idが未設定')
        return jsonify({'status': 'error', 'message': 'son_user_id not set'}), 400

    weekday = WEEKDAY_MAP[datetime.now().weekday()]
    subjects_today = settings['schedule'].get(weekday, {})
    if not subjects_today:
        return jsonify({'status': 'skipped', 'message': f'{weekday}曜日は問題なし'})

    logger.info(f'{weekday}曜日の問題生成: {subjects_today}')
    questions = generate_daily_questions(subjects_today, settings)
    if not questions:
        return jsonify({'status': 'error', 'message': '問題生成失敗'}), 500

    save_today_data(questions)
    message = format_question_message(questions, weekday)

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        api.push_message(PushMessageRequest(
            to=son_user_id,
            messages=[TextMessage(text=message)]
        ))
        _push_to_parents(api, settings, f'【本日の問題を送信しました】\n\n{message}')

    logger.info(f'問題送信完了: {len(questions)}問')
    return jsonify({'status': 'ok', 'questions': len(questions)})


@app.route('/reset')
def reset():
    if request.args.get('token') != CRON_SECRET:
        abort(403)
    import glob
    for f in ['today_questions.json', 'settings.json']:
        if os.path.exists(f):
            os.remove(f)
    return jsonify({'status': 'ok', 'message': 'リセット完了'})


@app.route('/webhook', methods=['POST'])
def webhook():
    body = request.get_data(as_text=True)
    signature = request.headers.get('X-Line-Signature', '')
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning('署名検証失敗')
        abort(400)
    return 'OK'


# ── メッセージ処理 ────────────────────────────────────

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    settings = load_settings()
    user_id = event.source.user_id
    text = event.message.text.strip()
    parent_id = settings.get('parent_user_id')
    parent2_id = settings.get('parent2_user_id')
    son_id = settings.get('son_user_id')
    is_parent = user_id in (parent_id, parent2_id) and user_id != ''
    logger.info(f'受信: user_id={user_id}, parent_id={parent_id}, parent2_id={parent2_id}, son_id={son_id}, text={text}')

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)

        # 息子の初回登録
        if not son_id and not is_parent:
            settings['son_user_id'] = user_id
            save_settings(settings)
            _reply(api, event.reply_token, '登録完了！毎日12時に問題を送るよ。頑張ってね！')
            return

        if is_parent:
            logger.info('親として処理')
            _handle_parent(text, settings, api, event.reply_token)
        elif user_id == son_id:
            logger.info('息子として処理')
            _handle_son(text, settings, api, event.reply_token)
        else:
            logger.warning(f'未登録ユーザー: {user_id}')


def _handle_parent(text, settings, api, reply_token):
    text = text.replace('：', ':')

    if text == '設定':
        _reply(api, reply_token, _format_settings(settings))
        return

    if text == 'ヘルプ':
        _reply(api, reply_token, HELP_MSG)
        return

    if ':' in text:
        key, _, value = text.partition(':')
        key, value = key.strip(), value.strip()
        if key == '学年' and value:
            settings['grade'] = value
            save_settings(settings)
            _reply(api, reply_token, f'学年を「{value}」に変更しました')
        elif key == '難易度' and value:
            settings['difficulty'] = value
            save_settings(settings)
            _reply(api, reply_token, f'難易度を「{value}」に変更しました')
        elif key == '時刻' and value:
            settings['send_time'] = value
            save_settings(settings)
            _reply(api, reply_token, f'送信時刻を「{value}」に変更しました\n※cron-job.orgの時刻設定も変更してください')
        else:
            _reply(api, reply_token, '「ヘルプ」と送ると使い方を確認できます')
        return

    _reply(api, reply_token, '「設定」または「ヘルプ」と送ってください')


def _handle_son(text, settings, api, reply_token):
    today_data = get_today_data()

    if not today_data:
        _reply(api, reply_token, '今日の問題はまだ来てないよ！12時になったら届くから待ってね。')
        return

    retry_questions = today_data.get('retry_questions')

    # ── 再挑戦モード ──────────────────────────────────
    if retry_questions is not None:
        answers = _parse_answers(text)
        if len(answers) != len(retry_questions):
            _reply(api, reply_token,
                   f'再挑戦問題は{len(retry_questions)}問だよ。{len(retry_questions)}個の答えをカンマ区切りで送ってね。\n例：a,b,c,d,e')
            return

        round_num = today_data.get('retry_round', 1)
        result_msg, explanation_msg, parent_msg, wrong_questions = grade_retry(retry_questions, answers)

        _reply(api, reply_token, result_msg)
        api.push_message(PushMessageRequest(
            to=settings['son_user_id'], messages=[TextMessage(text=explanation_msg)]))
        _push_to_parents(api, settings, parent_msg)

        if wrong_questions:
            new_retry = generate_retry_questions(wrong_questions, settings)
            today_data['retry_questions'] = new_retry
            today_data['retry_round'] = round_num + 1
            update_today_data(today_data)
            api.push_message(PushMessageRequest(
                to=settings['son_user_id'],
                messages=[TextMessage(text=format_retry_message(new_retry, round_num + 1))]))
        else:
            today_data['retry_questions'] = None
            today_data['mission_complete'] = True
            update_today_data(today_data)
            api.push_message(PushMessageRequest(
                to=settings['son_user_id'],
                messages=[TextMessage(text='Mission Complete！\n全問正解おめでとう！')]))
        return

    # ── 初回回答モード ────────────────────────────────
    if today_data.get('answered'):
        _reply(api, reply_token, '今日はもう答えたよ！また明日ね。')
        return

    questions = today_data['questions']
    answers = _parse_answers(text)

    if len(answers) != len(questions):
        _reply(api, reply_token,
               f'問題数は{len(questions)}問だよ。{len(questions)}個の答えをカンマ区切りで送ってね。\n例：a,b,c,d,e,a,b...')
        return

    result_msg, explanation_msg, parent_msg, wrong_questions = grade_and_format(questions, answers)
    today_data['answered'] = True

    if wrong_questions:
        new_retry = generate_retry_questions(wrong_questions, settings)
        today_data['retry_questions'] = new_retry
        today_data['retry_round'] = 1
        today_data['mission_complete'] = False
    else:
        today_data['retry_questions'] = None
        today_data['mission_complete'] = True

    update_today_data(today_data)

    _reply(api, reply_token, result_msg)
    api.push_message(PushMessageRequest(
        to=settings['son_user_id'], messages=[TextMessage(text=explanation_msg)]))

    if wrong_questions:
        api.push_message(PushMessageRequest(
            to=settings['son_user_id'],
            messages=[TextMessage(text=format_retry_message(today_data['retry_questions'], 1))]))
    else:
        api.push_message(PushMessageRequest(
            to=settings['son_user_id'],
            messages=[TextMessage(text='Mission Complete！\n全問正解おめでとう！')]))

    _push_to_parents(api, settings, parent_msg)


def _parse_answers(text):
    """1a 2b 3c / 1.a,2.b / a,b,c 形式（全角・半角混在）に対応"""
    # 全角→半角変換
    text = text.translate(str.maketrans(
        '０１２３４５６７８９ａｂｃｄｅＡＢＣＤＥ，．：　',
        '0123456789abcdeABCDE,.: '
    ))
    text = text.replace('、', ',').replace('，', ',')
    # スペース区切りをカンマに統一
    text = re.sub(r'[\s,]+', ',', text.strip())
    parts = [p.strip() for p in text.split(',') if p.strip()]
    answers = []
    for p in parts:
        m = re.match(r'^\d+[.)）\s]*([a-eA-E○✗×])', p) or re.match(r'^\d+([a-eA-E])', p)
        if m:
            answers.append(m.group(1))
        else:
            answers.append(p)
    return answers


def _reply(api, reply_token, text):
    api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text=text)]
    ))


def _format_settings(settings):
    lines = [
        '【現在の設定】',
        f'学年：{settings["grade"]}',
        f'難易度：{settings["difficulty"]}',
        f'送信時刻：{settings["send_time"]}',
        '',
        '【曜日別スケジュール】',
    ]
    for day, subjects in settings['schedule'].items():
        s = '・'.join([f'{sub}({n}問)' for sub, n in subjects.items()])
        lines.append(f'{day}：{s}')
    return '\n'.join(lines)


HELP_MSG = """【設定コマンド一覧】
設定 → 現在の設定を表示

学年:中学2年 → 学年を変更
  （中学1年／中学2年／中学3年）

難易度:応用 → 難易度を変更
  （基礎／標準／応用／難問）

時刻:18:00 → 送信時刻を変更"""


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

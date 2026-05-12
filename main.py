import os
import json
import logging
import re
import threading
import urllib.request
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
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
                  generate_retry_questions, format_retry_message, grade_retry,
                  generate_question_from_page)

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

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
GIST_ID = os.environ.get('GIST_ID')
GIST_FILENAME = 'today_questions.json'


def _gist_get():
    """GistからJSONを読み込む"""
    if not GITHUB_TOKEN or not GIST_ID:
        return None
    try:
        req = urllib.request.Request(
            f'https://api.github.com/gists/{GIST_ID}',
            headers={'Authorization': f'token {GITHUB_TOKEN}', 'Accept': 'application/json'}
        )
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read())
        content = data['files'][GIST_FILENAME]['content']
        return json.loads(content)
    except Exception as e:
        logger.error(f'Gist読み込みエラー: {e}')
        return None


def _gist_save(data):
    """GistにJSONを書き込む"""
    if not GITHUB_TOKEN or not GIST_ID:
        return
    try:
        payload = json.dumps({
            'files': {GIST_FILENAME: {'content': json.dumps(data, ensure_ascii=False, indent=2)}}
        }).encode()
        req = urllib.request.Request(
            f'https://api.github.com/gists/{GIST_ID}',
            data=payload,
            method='PATCH',
            headers={'Authorization': f'token {GITHUB_TOKEN}', 'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req)
    except Exception as e:
        logger.error(f'Gist書き込みエラー: {e}')


# ── 今日の問題ファイル操作 ────────────────────────────

def get_today_data():
    # まずGistから読む、失敗したらローカルファイル
    data = _gist_get()
    if data is None and os.path.exists(TODAY_FILE):
        with open(TODAY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    if not data:
        return None
    if data.get('date') != datetime.now(JST).strftime('%Y-%m-%d'):
        return None
    return data


def save_today_data(questions):
    data = {
        'date': datetime.now(JST).strftime('%Y-%m-%d'),
        'questions': questions,
        'answered': False,
        'retry_questions': None,
        'retry_round': 0,
        'mission_complete': False
    }
    _gist_save(data)
    with open(TODAY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_today_data(data):
    _gist_save(data)
    with open(TODAY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _push_text(api, to, text, limit=4900):
    """5000文字制限を超える場合は複数に分割して送信"""
    if len(text) <= limit:
        api.push_message(PushMessageRequest(to=to, messages=[TextMessage(text=text)]))
        return
    lines = text.split('\n')
    chunk = ''
    for line in lines:
        if len(chunk) + len(line) + 1 > limit:
            if chunk:
                api.push_message(PushMessageRequest(to=to, messages=[TextMessage(text=chunk.rstrip())]))
            chunk = line + '\n'
        else:
            chunk += line + '\n'
    if chunk.strip():
        api.push_message(PushMessageRequest(to=to, messages=[TextMessage(text=chunk.rstrip())]))


def _push_to_parents(api, settings, text):
    """登録済みの全親アカウントにpush送信する"""
    for key in ('parent_user_id', 'parent2_user_id'):
        uid = settings.get(key)
        if uid:
            _push_text(api, uid, text)


def _regenerate_in_background(subjects_today, settings, weekday):
    """バックグラウンドで問題を再生成し、完成したらpush送信"""
    try:
        questions = generate_daily_questions(subjects_today, settings)
    except Exception as e:
        logger.error(f'問題再生成エラー: {e}')
        questions = None

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        try:
            if not questions:
                api.push_message(PushMessageRequest(
                    to=settings['parent_user_id'],
                    messages=[TextMessage(text='問題の再生成に失敗しました')]))
                return
            save_today_data(questions)
            message = format_question_message(questions, weekday)
            _push_text(api, settings['son_user_id'], message)
            _push_to_parents(api, settings, f'【問題を再送信しました】\n\n{message}')
        except Exception as e:
            logger.error(f'再生成push送信エラー: {e}')


def _generate_retry_in_background(wrong_questions, settings):
    """バックグラウンドで再挑戦問題を生成し、完成したらpush送信"""
    try:
        new_retry = generate_retry_questions(wrong_questions, settings)
    except Exception as e:
        logger.error(f'再挑戦生成エラー: {e}')
        new_retry = []

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        try:
            if new_retry:
                today_data = get_today_data()
                if today_data:
                    today_data['retry_questions'] = new_retry
                    today_data['retry_round'] = 1
                    today_data['mission_complete'] = False
                    update_today_data(today_data)
                api.push_message(PushMessageRequest(
                    to=settings['son_user_id'],
                    messages=[TextMessage(text=format_retry_message(new_retry, 1))]))
            else:
                api.push_message(PushMessageRequest(
                    to=settings['son_user_id'],
                    messages=[TextMessage(text='再挑戦問題の生成に失敗しました。今日はおしまい！')]))
        except Exception as e:
            logger.error(f'再挑戦push送信エラー: {e}')


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

    now = datetime.now(JST)
    today_str = now.strftime('%Y-%m-%d')
    current_hour = now.hour
    weekday = WEEKDAY_MAP[now.weekday()]

    # 今日の配信が既に済んでいればスキップ
    if get_today_data():
        return jsonify({'status': 'skipped', 'message': '本日分は配信済み'})

    # 明日だけ設定の確認
    override = settings.get('tomorrow_override')
    if override and override.get('date') == today_str:
        scheduled_hour = override.get('hour', 12)
        if current_hour != scheduled_hour:
            return jsonify({'status': 'skipped', 'message': f'配信予定時刻は{scheduled_hour}時'})
        subjects_today = override['subjects']
        del settings['tomorrow_override']
        save_settings(settings)
        logger.info(f'明日だけ設定を適用: {subjects_today}')
    else:
        # 通常スケジュール：正午のみ配信
        if current_hour != 12:
            return jsonify({'status': 'skipped', 'message': '配信時刻外'})
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
        _push_text(api, son_user_id, message)
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


@app.route('/reset_saturday')
def reset_saturday():
    if request.args.get('token') != CRON_SECRET:
        abort(403)
    settings = load_settings()
    settings['schedule']['土'] = {'数学': 10, '英語': 20, '国語': 20}
    save_settings(settings)
    logger.info('土曜スケジュールを元に戻しました')
    return jsonify({'status': 'ok', 'schedule': settings['schedule']['土']})


@app.route('/migrate_grade2')
def migrate_grade2():
    """中学2年・数学20問・特別ページ20件に一括移行する一回限りエンドポイント"""
    if request.args.get('token') != CRON_SECRET:
        abort(403)
    settings = load_settings()
    settings['grade'] = '中学2年'
    for day in settings['schedule']:
        if '数学' in settings['schedule'][day]:
            settings['schedule'][day]['数学'] = 20
    settings['math_special_pages']['中学2年'] = [
        '98', '103', '110', '197', '203',
        '4', '6', '8', '10', '12', '14', '16', '18', '20',
        '22', '24', '26', '28', '30', '32'
    ]
    save_settings(settings)
    logger.info('中学2年移行完了')
    return jsonify({
        'status': 'ok',
        'grade': settings['grade'],
        'math_special_pages_count': len(settings['math_special_pages']['中学2年'])
    })


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


def _parse_tomorrow_override(text):
    """「明日だけ 10時 数学5問 英語3問」から時刻と{科目: 問題数}を抽出する"""
    SUBJECTS = ['数学', '国語', '社会', '理科', '英語']
    subjects = {}
    for subject in SUBJECTS:
        m = re.search(subject + r'\D{0,3}?(\d+)', text)
        if m:
            subjects[subject] = int(m.group(1))
    # 時刻抽出：「10時」「10:00」「午前10時」など
    hour = None
    m = re.search(r'(\d{1,2})\s*時', text)
    if m:
        hour = int(m.group(1))
    return subjects, hour


def _handle_parent(text, settings, api, reply_token):
    text = text.replace('：', ':')

    if text == '設定':
        _reply(api, reply_token, _format_settings(settings))
        return

    if text == 'ヘルプ':
        _reply(api, reply_token, HELP_MSG)
        return

    if text == '親確認':
        today_data = get_today_data()
        if not today_data:
            _reply(api, reply_token, '今日の問題データがありません')
            return
        questions = today_data['questions']
        weekday = WEEKDAY_MAP[datetime.now(JST).weekday()]
        message = format_question_message(questions, weekday)
        _push_to_parents(api, settings, f'【本日の問題（親確認用）】\n\n{message}')
        _reply(api, reply_token, '親アカウントに送信しました')
        return

    if text.replace('　', ' ').startswith('明日だけ'):
        from datetime import timedelta
        text = text.replace('　', ' ')  # 全角スペースを半角に統一
        subjects, hour = _parse_tomorrow_override(text)
        if not subjects:
            _reply(api, reply_token, '科目と問題数が読み取れませんでした。\n例：明日だけ 10時 数学5問 英語3問')
            return
        tomorrow = (datetime.now(JST) + timedelta(days=1)).strftime('%Y-%m-%d')
        delivery_hour = hour if hour is not None else 12
        settings['tomorrow_override'] = {
            'date': tomorrow,
            'subjects': subjects,
            'hour': delivery_hour
        }
        save_settings(settings)
        # 親への確認通知
        lines = [f'明日は{delivery_hour}時に、']
        lines.append('、'.join([f'{s}{n}問' for s, n in subjects.items()]))
        lines.append('が配信されます。')
        lines.append('（基本スケジュールは変更していません）')
        notify = '\n'.join(lines)
        _push_to_parents(api, settings, notify)
        _reply(api, reply_token, '設定しました！\n' + notify)
        return

    if text == '再送信':
        today_data = get_today_data()
        if not today_data:
            # 問題データなし → バックグラウンドで再生成
            weekday = WEEKDAY_MAP[datetime.now(JST).weekday()]
            subjects_today = settings['schedule'].get(weekday, {})
            if not subjects_today:
                _reply(api, reply_token, '今日は問題なし設定です')
                return
            _reply(api, reply_token, '問題を再生成中です。最大10分ほどお待ちください...')
            threading.Thread(
                target=_regenerate_in_background,
                args=(subjects_today, settings, weekday),
                daemon=False
            ).start()
            return
        else:
            # 問題データあり → 回答状態をリセットして再送信
            today_data['answered'] = False
            today_data['retry_questions'] = None
            today_data['retry_round'] = 0
            today_data['mission_complete'] = False
            update_today_data(today_data)
        questions = today_data['questions']
        weekday = WEEKDAY_MAP[datetime.now(JST).weekday()]
        message = format_question_message(questions, weekday)
        _push_text(api, settings['son_user_id'], message)
        _push_to_parents(api, settings, f'【問題を再送信しました】\n\n{message}')
        return

    if text.startswith('プレビュー:'):
        page = text.split(':', 1)[1].strip()
        _reply(api, reply_token, '問題を生成中です。少々お待ちください...')
        msg, err = generate_question_from_page(page)
        if err:
            api.push_message(PushMessageRequest(
                to=settings['parent_user_id'], messages=[TextMessage(text=f'エラー：{err}')]))
        else:
            api.push_message(PushMessageRequest(
                to=settings['parent_user_id'], messages=[TextMessage(text=msg)]))
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
    update_today_data(today_data)

    # 採点結果を即座に返信（reply_tokenの有効期限切れ防止）
    _reply(api, reply_token, result_msg)
    api.push_message(PushMessageRequest(
        to=settings['son_user_id'], messages=[TextMessage(text=explanation_msg)]))
    _push_to_parents(api, settings, parent_msg)

    # 再挑戦問題の生成は時間がかかるのでバックグラウンドで実行
    if wrong_questions:
        api.push_message(PushMessageRequest(
            to=settings['son_user_id'],
            messages=[TextMessage(text='再挑戦問題を生成中...最大2分ほどお待ちください')]))
        threading.Thread(
            target=_generate_retry_in_background,
            args=(wrong_questions, settings),
            daemon=False
        ).start()
    else:
        today_data['retry_questions'] = None
        today_data['mission_complete'] = True
        update_today_data(today_data)
        api.push_message(PushMessageRequest(
            to=settings['son_user_id'],
            messages=[TextMessage(text='Mission Complete！\n全問正解おめでとう！')]))


def _parse_answers(text):
    """1a 2b 3c / 1.a,2.b / a,b,c 形式（全角・半角混在）に対応"""
    # 全角→半角変換
    text = text.translate(str.maketrans(
        '０１２３４５６７８９ａｂｃｄｅＡＢＣＤＥ，．：　',
        '0123456789abcdeABCDE,.: '
    ))
    text = text.replace('、', ',').replace('，', ',')

    # 番号付き形式が含まれていれば、番号に紐づいたa-eだけを抽出（余分な文字は無視）
    numbered = re.findall(r'\d+\s*[.)）]?\s*([a-eA-E])', text)
    if numbered:
        return numbered

    # 番号なし形式：a,b,c,d,e
    text = re.sub(r'[\s,]+', ',', text.strip())
    parts = [p.strip() for p in text.split(',') if p.strip()]
    return parts


def _reply(api, reply_token, text):
    api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text=text)]
    ))


def _format_settings(settings):
    lines = [
        '【現在の設定】',
        f'学年：{settings["grade"]}',
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
再送信 → 今日の問題をゆうに再送信

学年:中学2年 → 学年を変更
  （中学1年／中学2年／中学3年）

難易度:応用 → 難易度を変更
  （基礎／標準／応用／難問）

時刻:18:00 → 送信時刻を変更"""


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

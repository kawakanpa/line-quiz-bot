import json
import re
import logging
import urllib.request
import os

logger = logging.getLogger(__name__)


def _parse_choices(question_text):
    """問題文から(本文, 選択肢リスト)を返す"""
    sep = re.search(r'(\n\s*a\.|\s{2,}a\.)', question_text)
    if not sep:
        return question_text.strip(), []

    main_q = question_text[:sep.start()].strip()
    choice_text = question_text[sep.start():].strip()

    choices = []
    for m in re.finditer(r'\b([a-e])\.\s+(.+?)(?=\s+[a-e]\.\s|$)', choice_text):
        choices.append(m.group(2).strip())

    return main_q, choices


def create_quiz_form(questions, title):
    """Google Apps Script経由でGoogle Formを作成してURLを返す。失敗時はNone。"""
    url = os.environ.get('APPS_SCRIPT_URL')
    if not url:
        return None

    secret = os.environ.get('APPS_SCRIPT_SECRET', '')

    form_questions = []
    for q in questions:
        main_q, choices = _parse_choices(q.get('question', ''))
        answer_label = q.get('answer', 'a').strip().lower()[:1]
        answer_index = 'abcde'.index(answer_label) if answer_label in 'abcde' else 0
        form_questions.append({
            'subject': q.get('subject', ''),
            'field': q.get('field', ''),
            'question': main_q,
            'choices': choices,
            'answer_index': answer_index,
            'explanation': q.get('explanation', '')
        })

    payload = json.dumps({
        'secret': secret,
        'title': title,
        'questions': form_questions
    }, ensure_ascii=False).encode('utf-8')

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            method='POST',
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=60) as res:
            result = json.loads(res.read().decode('utf-8'))
        form_url = result.get('url')
        if form_url:
            logger.info(f'Google Form作成完了: {form_url}')
        return form_url
    except Exception as e:
        logger.error(f'Google Form作成エラー: {e}')
        return None

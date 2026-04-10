import os
import json
import random
import logging
from datetime import datetime
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

client = Groq(api_key=os.environ.get('GROQ_API_KEY'))
MODEL = 'llama-3.3-70b-versatile'

CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
SUBJECT_ORDER = ['数学', '国語', '社会', '理科', '英語']


def generate_daily_questions(subjects_today, settings):
    grade = settings['grade']
    difficulty = settings['difficulty']
    math_fields = settings['math_fields'].get(grade, settings['math_fields']['中学1年'])

    all_questions = []
    for subject in SUBJECT_ORDER:
        if subject not in subjects_today:
            continue
        count = subjects_today[subject]
        try:
            if subject == '数学':
                questions = _generate_math(count, grade, difficulty, math_fields)
            else:
                questions = _generate_subject(subject, count, grade, difficulty)
            for q in questions:
                q.setdefault('subject', subject)
            all_questions.extend(questions)
            logger.info(f'{subject}: {len(questions)}問生成')
        except Exception as e:
            logger.error(f'{subject}問題生成エラー: {e}')

    return all_questions


def _generate_math(count, grade, difficulty, math_fields):
    n_fields = 5
    q_per_field = count // n_fields  # 1 or 2
    selected = random.sample(math_fields, min(n_fields, len(math_fields)))
    fields_str = '\n'.join([f'- {f}: {q_per_field}問' for f in selected])

    prompt = f"""あなたは中学数学の教師です。{grade}の数学問題を作成してください。

各分野から指定数の問題を作成：
{fields_str}

以下のJSON形式のみで返してください（他の文章不要）：
{{
  "questions": [
    {{
      "subject": "数学",
      "field": "分野名",
      "question": "問題文",
      "type": "numeric",
      "answer": "数値または文字式（スペースなし、例：3、-5、4a+3b）",
      "explanation": "解き方（2文程度、計算過程を含む）"
    }}
  ]
}}

難易度：{difficulty}
全{count}問を必ず含めること。"""

    return _call_groq(prompt)


def _generate_subject(subject, count, grade, difficulty):
    guidance = {
        '国語': 'ことわざ・慣用句、文法、漢字、文学作品など',
        '英語': '単語・熟語、文法、短文読解など',
        '社会': '歴史・地理・公民（中学範囲）',
        '理科': '物理・化学・生物・地学（中学範囲）',
    }

    prompt = f"""あなたは中学{subject}の教師です。{grade}の{subject}問題を{count}問作成してください。
分野の参考：{guidance.get(subject, '')}

問題タイプ：○✗問題（type: "ox"）と4択問題（type: "multiple_choice"）を適切に混ぜてください。

以下のJSON形式のみで返してください（他の文章不要）：
{{
  "questions": [
    {{
      "subject": "{subject}",
      "field": "分野名",
      "question": "問題文（4択の場合：A. xxx  B. xxx  C. xxx  D. xxxを問題文に含める）",
      "type": "ox" or "multiple_choice",
      "answer": "○ か ✗ か A/B/C/D",
      "explanation": "解説（なぜその答えか、2-3文）"
    }}
  ]
}}

難易度：{difficulty}、学年：{grade}
全{count}問を必ず含めること。"""

    return _call_groq(prompt)


def _call_groq(prompt):
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        response_format={'type': 'json_object'},
        temperature=0.7,
        max_tokens=3000
    )
    data = json.loads(response.choices[0].message.content)
    return data.get('questions', [])


def format_question_message(questions, weekday):
    today = datetime.now()
    date_str = f'{today.year}年{today.month}月{today.day}日({weekday})'

    grouped = {}
    for q in questions:
        s = q['subject']
        grouped.setdefault(s, []).append(q)

    lines = [f'【今日の問題】{date_str}', '']
    n = 0
    for subject in SUBJECT_ORDER:
        if subject not in grouped:
            continue
        lines.append(f'━━━ {subject} ━━━')
        for q in grouped[subject]:
            lines.append(f'{CIRCLED[n]}[{q["field"]}] {q["question"]}')
            n += 1
        lines.append('')

    lines.append('答えを番号順にカンマ区切りで送ってね')
    lines.append(f'例（{len(questions)}個）：3, ✗, A, -5, ○, B...')
    lines.append('※スペースなしで入力してね')

    return '\n'.join(lines)


def _normalize(answer_str, question_type):
    a = answer_str.strip()
    if question_type == 'numeric':
        return a.replace(' ', '').replace('　', '')
    elif question_type == 'ox':
        if a in ['○', 'o', 'O', 'まる', '丸', '⭕', '◯']:
            return '○'
        if a in ['✗', '×', 'x', 'X', 'ばつ', 'バツ', '✕', '✘']:
            return '✗'
        return a
    elif question_type == 'multiple_choice':
        return a.upper()
    return a


def _is_correct(submitted, expected, question_type):
    sub = _normalize(submitted, question_type)
    exp = _normalize(expected, question_type)
    if question_type == 'numeric':
        try:
            return abs(float(sub) - float(exp)) < 0.01
        except ValueError:
            return sub == exp
    return sub == exp


def grade_and_format(questions, answers):
    results = []
    correct = 0

    for i, (q, a) in enumerate(zip(questions, answers)):
        ok = _is_correct(a, q['answer'], q['type'])
        if ok:
            correct += 1
        results.append({'num': i + 1, 'q': q, 'submitted': a, 'ok': ok})

    total = len(questions)
    pct = int(correct / total * 100)

    # Son: 採点結果
    lines = [f'【採点結果】{correct}/{total}問正解（{pct}%）', '']
    for r in results:
        c = CIRCLED[r['num'] - 1]
        mark = '✓' if r['ok'] else '✗'
        if r['ok']:
            lines.append(f'{c} {mark} {r["q"]["subject"]}（{r["q"]["field"]}）')
        else:
            lines.append(f'{c} {mark} {r["q"]["subject"]}（{r["q"]["field"]}）→ 正解：{r["q"]["answer"]}')
    result_msg = '\n'.join(lines)

    # Son: 解説
    lines = ['【解説】', '']
    for r in results:
        c = CIRCLED[r['num'] - 1]
        lines.append(f'{c} {r["q"]["subject"]}（{r["q"]["field"]}）')
        lines.append(r['q']['explanation'])
        lines.append('')
    explanation_msg = '\n'.join(lines)

    # Parent: レポート
    today = datetime.now()
    lines = [
        f'【息子の回答】{today.month}月{today.day}日',
        f'正解率：{correct}/{total}（{pct}%）',
        ''
    ]
    for r in results:
        c = CIRCLED[r['num'] - 1]
        mark = '✓' if r['ok'] else '✗'
        q_text = r['q']['question'][:25] + '...' if len(r['q']['question']) > 25 else r['q']['question']
        lines.append(f'{c}{mark} {r["q"]["subject"]}[{r["q"]["field"]}]')
        lines.append(f'   問: {q_text}')
        lines.append(f'   息子: {r["submitted"]}　正解: {r["q"]["answer"]}')
        lines.append('')
    parent_msg = '\n'.join(lines)

    return result_msg, explanation_msg, parent_msg

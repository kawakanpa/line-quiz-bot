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

SUBJECT_ORDER = ['数学', '国語', '社会', '理科', '英語']

THREE_CHOICE_INSTRUCTION = """
問題形式：全問3択問題（A/B/Cの3択）
- 図・グラフ・絵が必要な問題は絶対に作らないこと
- 文章だけで完結する問題にすること
- 選択肢はa. ～  b. ～  c. ～ の形式で問題文に含めること
"""


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
                q['type'] = 'multiple_choice'
            all_questions.extend(questions)
            logger.info(f'{subject}: {len(questions)}問生成')
        except Exception as e:
            logger.error(f'{subject}問題生成エラー: {e}')

    return all_questions


def _generate_math(count, grade, difficulty, math_fields):
    n_fields = 5
    q_per_field = count // n_fields
    selected = random.sample(math_fields, min(n_fields, len(math_fields)))
    fields_str = '\n'.join([f'- {f}: {q_per_field}問' for f in selected])

    prompt = f"""あなたは中学数学の教師です。{grade}の数学問題を作成してください。

各分野から指定数の問題を作成：
{fields_str}

{THREE_CHOICE_INSTRUCTION}

以下のJSON形式のみで返してください（他の文章不要）：
{{
  "questions": [
    {{
      "subject": "数学",
      "field": "分野名",
      "question": "問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3",
      "type": "multiple_choice",
      "answer": "a か b か c",
      "explanation": "解き方（2文程度、計算過程を含む）"
    }}
  ]
}}

難易度：{difficulty}
問題文は「〜はいくらか」「〜を求めよ」「〜はどれか」のように簡潔に終わること。「どうなるでしょうか」などの冗長な表現は使わないこと。
全{count}問を必ず含めること。"""

    return _call_groq(prompt)


def _generate_subject(subject, count, grade, difficulty):
    guidance = {
        '国語': 'ことわざ・慣用句、文法、漢字、文学作品など',
        '英語': '英検4級レベル（単語・熟語、基本文法、短文穴埋めなど）',
        '社会': '歴史・地理・公民（中学範囲）',
        '理科': '物理・化学・生物・地学（中学範囲、実験の図は使わない）',
    }

    prompt = f"""あなたは中学{subject}の教師です。{grade}の{subject}問題を{count}問作成してください。
分野の参考：{guidance.get(subject, '')}

{THREE_CHOICE_INSTRUCTION}

以下のJSON形式のみで返してください（他の文章不要）：
{{
  "questions": [
    {{
      "subject": "{subject}",
      "field": "分野名",
      "question": "問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3",
      "type": "multiple_choice",
      "answer": "a か b か c",
      "explanation": "解説（なぜその答えか、2-3文）"
    }}
  ]
}}

{'難易度：英検4級レベル' if subject == '英語' else f'難易度：{difficulty}、学年：{grade}'}
問題文は簡潔に終わること。「どうなるでしょうか」「何と言いますか」などの冗長な表現は使わず、「〜はどれか」「〜を選べ」「〜はいつか」のように短くまとめること。
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
        lines.append('')
        for q in grouped[subject]:
            n += 1
            lines.append(f'{n}. [{q["field"]}] {q["question"]}')
            lines.append('')

    lines.append('答えをa/b/cで番号順にカンマ区切りで送ってね')
    lines.append(f'例：a,b,c,a,b...')

    return '\n'.join(lines)


def _normalize(answer_str, question_type):
    return answer_str.strip().upper()


def _is_correct(submitted, expected, question_type):
    return _normalize(submitted, question_type) == _normalize(expected, question_type)


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
        mark = '✓' if r['ok'] else '✗'
        if r['ok']:
            lines.append(f'{r["num"]}. {mark} {r["q"]["subject"]}（{r["q"]["field"]}）')
        else:
            lines.append(f'{r["num"]}. {mark} {r["q"]["subject"]}（{r["q"]["field"]}）→ 正解：{r["q"]["answer"]}')
    result_msg = '\n'.join(lines)

    # Son: 解説
    lines = ['【解説】', '']
    for r in results:
        lines.append(f'{r["num"]}. {r["q"]["subject"]}（{r["q"]["field"]}）')
        lines.append(r['q']['explanation'])
        lines.append('')
    explanation_msg = '\n'.join(lines)

    # Parent: レポート
    today = datetime.now()
    lines = [
        f'【ゆうの回答】{today.month}月{today.day}日',
        f'正解率：{correct}/{total}（{pct}%）',
        ''
    ]
    for r in results:
        mark = '✓' if r['ok'] else '✗'
        q_text = r['q']['question'][:25] + '...' if len(r['q']['question']) > 25 else r['q']['question']
        lines.append(f'{r["num"]}. {mark} {r["q"]["subject"]}[{r["q"]["field"]}]')
        lines.append(f'   問: {q_text}')
        lines.append(f'   ゆう: {r["submitted"]}　正解: {r["q"]["answer"]}')
        lines.append('')
    parent_msg = '\n'.join(lines)

    return result_msg, explanation_msg, parent_msg

import os
import json
import re
import random
import logging
import time
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
from groq import Groq
from dotenv import load_dotenv
from config import DIFFICULTY_MAP, save_settings

load_dotenv()

logger = logging.getLogger(__name__)

client = Groq(api_key=os.environ.get('GROQ_API_KEY'))
MODEL = 'llama-3.3-70b-versatile'

SUBJECT_ORDER = ['数学', '国語', '社会', '理科', '英語']
MATH_BANK_FILE = 'math_problems.json'
MATH_PAGE_BANK_FILE = 'math_page_bank.json'
SCIENCE_BANK_FILE = 'science_problems.json'
SOCIAL_BANK_FILE = 'social_problems.json'
KOKUGO_BANK_FILE = 'kokugo_problems.json'

KOKUGO_READING_FIELDS = {'論説・評論文', '小説・戯曲', '随筆', '古典物語・随筆', '漢文・漢詩'}

FIVE_CHOICE_INSTRUCTION = """
問題形式：全問5択問題（a/b/c/d/eの5択）
- 図・グラフ・絵が必要な問題は絶対に作らないこと
- 文章だけで完結する問題にすること
- 選択肢はa. ～  b. ～  c. ～  d. ～  e. ～ の形式で問題文に含めること
- 数式に「$」「$$」「\(」「\)」などのLaTeX記号を絶対に使わないこと
- 分数はスラッシュで表記すること（例：（2x－3）／3）
- 累乗は「x²」「x³」のように表記すること
"""


def _load_math_bank():
    if not os.path.exists(MATH_BANK_FILE):
        return []
    with open(MATH_BANK_FILE, 'r', encoding='utf-8') as f:
        return json.load(f).get('problems', [])


def get_page_text(grade, page_num):
    if not os.path.exists(MATH_PAGE_BANK_FILE):
        return None
    with open(MATH_PAGE_BANK_FILE, 'r', encoding='utf-8') as f:
        bank = json.load(f)
    grade_bank = bank.get(grade, {})
    for field, pages in grade_bank.items():
        if page_num in pages:
            return pages[page_num]
    return None


def get_section_end_text(grade, page_num):
    text = get_page_text(grade, page_num)
    if not text:
        return None
    idx = text.find('節末問題')
    if idx == -1:
        return text  # 「節末問題」がなければ全体を使う
    return text[idx:]


def _has_choices(question_text):
    return 'a. ' in question_text or '\na.' in question_text


def _sample_from_bank(grade, math_fields, count=10):
    """各章から1問ずつ抽出し、足りない分をランダム補充して合計count問にする"""
    bank = _load_math_bank()
    if not bank:
        return []
    grade_filtered = [q for q in bank if q.get('grade') == grade] or bank
    valid = [
        q for q in grade_filtered
        if _has_choices(q.get('question', ''))
        and q.get('answer', '').strip().lower() in ['a', 'b', 'c', 'd', 'e']
    ]
    selected = []
    used_ids = set()
    for field in math_fields:
        candidates = [q for q in valid if field in q.get('field', '') and q.get('id') not in used_ids]
        if candidates:
            picked = random.choice(candidates)
            selected.append(picked)
            used_ids.add(picked['id'])
    remaining = [q for q in valid if q.get('id') not in used_ids]
    while len(selected) < count and remaining:
        picked = random.choice(remaining)
        selected.append(picked)
        used_ids.add(picked['id'])
        remaining = [q for q in remaining if q.get('id') not in used_ids]
    return _clean_questions(selected)


def _generate_math_from_page_bank(grade, math_fields, difficulty):
    """ページバンクから各章1問ずつGroqで生成"""
    if not os.path.exists(MATH_PAGE_BANK_FILE):
        return []
    with open(MATH_PAGE_BANK_FILE, 'r', encoding='utf-8') as f:
        bank = json.load(f)
    grade_bank = bank.get(grade, {})
    if not grade_bank:
        return []

    questions = []
    for field in math_fields:
        field_pages = grade_bank.get(field, {})
        if not field_pages:
            continue
        page_num, page_text = random.choice(list(field_pages.items()))
        prompt = f"""以下は中学数学の問題集（{grade}・{field}）のp.{page_num}のテキストです。
このページから「類題」または練習問題を1問選び、5択問題に変換してください。

テキスト：
{page_text[:2000]}

ルール：
- 具体的な場面・状況を設定した文章問題にする（式だけの問題は文章に変換する）
- 正解1つ＋数学的に紛らわしい誤答4つを生成する
- 難易度：{difficulty}
- 「$」「$$」「\(」「\)」などのLaTeX記号は絶対に使わないこと
- 分数はスラッシュで表記（例：（2x－3）／3）、累乗は「x²」「x³」で表記

JSON形式のみで返してください：
{{
  "questions": [
    {{
      "subject": "数学",
      "grade": "{grade}",
      "field": "{field}",
      "question": "問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3  d. 選択肢4  e. 選択肢5",
      "type": "multiple_choice",
      "answer": "a か b か c か d か e",
      "explanation": "解き方（2-3文、計算過程を含む）"
    }}
  ]
}}"""
        try:
            result = _call_groq(prompt)
            if result:
                result[0].setdefault('subject', '数学')
                result[0]['type'] = 'multiple_choice'
                questions.append(result[0])
                logger.info(f'{field}: ページバンクから1問生成')
        except Exception as e:
            logger.error(f'{field}のページバンク生成エラー: {e}')
        time.sleep(4)  # レート制限対策
    return questions


def _generate_math_from_special_pages(grade, page_numbers, difficulty, count):
    """指定ページの節末問題から1問ずつGroqで生成"""
    if not os.path.exists(MATH_PAGE_BANK_FILE):
        return []

    questions = []
    for page_num in page_numbers[:count]:
        page_text = get_section_end_text(grade, page_num)
        if not page_text:
            continue
        prompt = f"""以下は中学数学の問題集（{grade}・p.{page_num}）の節末問題のテキストです。
この節末問題のテキストから1問の5択問題をつくってください。

テキスト：
{page_text[:2000]}

ルール：
- 具体的な場面・状況を設定した文章問題にする（式だけの問題は文章に変換する）
- 正解1つ＋数学的に紛らわしい誤答4つを生成する
- 難易度：{difficulty}
- 「$」「$$」「\(」「\)」などのLaTeX記号は絶対に使わないこと
- 分数はスラッシュで表記（例：（2x－3）／3）、累乗は「x²」「x³」で表記

JSON形式のみで返してください：
{{
  "questions": [
    {{
      "subject": "数学",
      "grade": "{grade}",
      "field": "p.{page_num}",
      "question": "問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3  d. 選択肢4  e. 選択肢5",
      "type": "multiple_choice",
      "answer": "a か b か c か d か e",
      "explanation": "解き方（2-3文、計算過程を含む）"
    }}
  ]
}}"""
        try:
            result = _call_groq(prompt)
            if result:
                result[0].setdefault('subject', '数学')
                result[0]['type'] = 'multiple_choice'
                questions.append(result[0])
                logger.info(f'p.{page_num}: 特別ページから1問生成')
        except Exception as e:
            logger.error(f'p.{page_num}の特別ページ生成エラー: {e}')
        time.sleep(4)
    return questions


def generate_question_from_page(page_num_str):
    """指定ページからGroqで問題を1問生成して返す（親プレビュー用）"""
    if not os.path.exists(MATH_PAGE_BANK_FILE):
        return None, 'ページバンクファイルが見つかりません'
    with open(MATH_PAGE_BANK_FILE, 'r', encoding='utf-8') as f:
        bank = json.load(f)

    # 全学年・全分野からページ番号を検索
    found_text = None
    found_field = None
    found_grade = None
    for grade, fields in bank.items():
        for field, pages in fields.items():
            if page_num_str in pages:
                found_text = get_section_end_text(grade, page_num_str)
                found_field = field
                found_grade = grade
                break
        if found_text:
            break

    if not found_text:
        return None, f'p.{page_num_str} はページバンクに登録されていません'

    prompt = f"""以下は中学数学の問題集（{found_grade}・{found_field}）のp.{page_num_str}のテキストです。
このページから「類題」または練習問題を1問選び、5択問題に変換してください。

テキスト：
{found_text[:2000]}

ルール：
- 具体的な場面・状況を設定した文章問題にする（式だけの問題は文章に変換する）
- 正解1つ＋数学的に紛らわしい誤答4つを生成する
- 「$」「$$」「\(」「\)」などのLaTeX記号は絶対に使わないこと
- 分数はスラッシュで表記（例：（2x－3）／3）、累乗は「x²」「x³」で表記

JSON形式のみで返してください：
{{
  "questions": [
    {{
      "subject": "数学",
      "grade": "{found_grade}",
      "field": "{found_field}",
      "question": "問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3  d. 選択肢4  e. 選択肢5",
      "type": "multiple_choice",
      "answer": "a か b か c か d か e",
      "explanation": "解き方（2-3文、計算過程を含む）"
    }}
  ]
}}"""

    result = _call_groq(prompt)
    if not result:
        return None, '問題生成に失敗しました'
    q = result[0]
    msg = f'【プレビュー p.{page_num_str}・{found_field}】\n\n{q["question"]}\n\n正解：{q["answer"]}\n解説：{q["explanation"]}'
    return msg, None


def _load_science_bank():
    if not os.path.exists(SCIENCE_BANK_FILE):
        return []
    with open(SCIENCE_BANK_FILE, 'r', encoding='utf-8') as f:
        return json.load(f).get('problems', [])


def _sample_from_science_bank(grade, science_fields, count=5):
    """各章から1問ずつcount問をランダムに選ぶ"""
    bank = _load_science_bank()
    if not bank:
        return []
    grade_filtered = [q for q in bank if q.get('grade') == grade] or bank
    valid = [
        q for q in grade_filtered
        if _has_choices(q.get('question', ''))
        and q.get('answer', '').strip().lower() in ['a', 'b', 'c', 'd', 'e']
    ]
    # 各章から1問ずつ抽出
    selected = []
    used_ids = set()
    for field in science_fields:
        candidates = [q for q in valid if field in q.get('field', '') and q.get('id') not in used_ids]
        if candidates:
            picked = random.choice(candidates)
            selected.append(picked)
            used_ids.add(picked['id'])
    # 足りない分をランダム補充
    remaining = [q for q in valid if q.get('id') not in used_ids]
    while len(selected) < count and remaining:
        picked = random.choice(remaining)
        selected.append(picked)
        used_ids.add(picked['id'])
        remaining = [q for q in remaining if q.get('id') not in used_ids]
    return _clean_questions(selected)


def _load_social_bank():
    if not os.path.exists(SOCIAL_BANK_FILE):
        return []
    with open(SOCIAL_BANK_FILE, 'r', encoding='utf-8') as f:
        return json.load(f).get('problems', [])


def _get_social_schedule(grade, today):
    """学年・月から社会の出題grade_range・問題数・チェックポイント数を返す"""
    month = today.month
    if grade == "中学1年":
        return ["1年"], 30, 5
    elif grade == "中学2年":
        if 4 <= month <= 5:
            return ["2年1学期前半"], 30, 5
        elif 6 <= month <= 8:
            return ["2年1学期後半"], 30, 5
        elif 9 <= month <= 12:
            return ["2年2学期"], 30, 5
        else:
            return ["2年3学期"], 30, 5
    elif grade == "中学3年":
        if 4 <= month <= 8:
            return ["3年1学期"], 50, 5
        elif 9 <= month <= 12:
            return ["3年2学期", "3年2学期後半"], 50, 10
        else:
            return ["3年3学期"], 50, 5
    return ["1年"], 30, 5


def _sample_from_social_bank(grade_ranges, count, checkpoint_count):
    """社会バンクからgrade_rangeでフィルターしてcount問サンプリング"""
    bank = _load_social_bank()
    if not bank:
        return []
    filtered = [q for q in bank if q.get('grade_range') in grade_ranges]
    if not filtered:
        filtered = bank
    valid = [
        q for q in filtered
        if _has_choices(q.get('question', ''))
        and q.get('answer', '').strip().lower() in ['a', 'b', 'c', 'd', 'e']
    ]
    if not valid:
        return []
    checkpoint_q = [q for q in valid if q.get('is_checkpoint')]
    regular_q = [q for q in valid if not q.get('is_checkpoint')]
    selected = []
    if checkpoint_q:
        n_cp = min(checkpoint_count, len(checkpoint_q))
        selected.extend(random.sample(checkpoint_q, n_cp))
    remaining = count - len(selected)
    used_ids = {q.get('id') for q in selected}
    avail = [q for q in regular_q if q.get('id') not in used_ids]
    if len(avail) >= remaining:
        selected.extend(random.sample(avail, remaining))
    else:
        selected.extend(avail)
        still = count - len(selected)
        extra = [q for q in checkpoint_q if q.get('id') not in {s.get('id') for s in selected}]
        if extra and still > 0:
            selected.extend(random.sample(extra, min(still, len(extra))))
    random.shuffle(selected)
    return _clean_questions(selected)


def _load_kokugo_bank():
    if not os.path.exists(KOKUGO_BANK_FILE):
        return []
    with open(KOKUGO_BANK_FILE, 'r', encoding='utf-8') as f:
        return json.load(f).get('problems', [])


def _sample_from_kokugo_bank(use_reading):
    """非読解系10問をバンクから抽出（読解系は除外）"""
    bank = _load_kokugo_bank()
    if not bank:
        return []
    valid = [
        q for q in bank
        if _has_choices(q.get('question', ''))
        and q.get('answer', '').strip().lower() in ['a', 'b', 'c', 'd', 'e']
    ]
    non_reading = [q for q in valid if q.get('field') not in KOKUGO_READING_FIELDS]

    if non_reading:
        return _clean_questions(random.sample(non_reading, min(10, len(non_reading))))
    return []


def generate_daily_questions(subjects_today, settings):
    grade = settings['grade']
    difficulty = DIFFICULTY_MAP.get(settings['difficulty'], settings['difficulty'])
    math_fields = settings['math_fields'].get(grade, settings['math_fields']['中学1年'])
    special_pages = settings.get('math_special_pages', {}).get(grade, [])
    science_fields = settings.get('science_fields', {}).get(grade, [])

    all_questions = []
    for subject in SUBJECT_ORDER:
        if subject not in subjects_today:
            continue
        count = subjects_today[subject]
        try:
            if subject == '数学':
                if special_pages:
                    special_count = min(len(special_pages), count)
                    questions = _generate_math_from_special_pages(grade, special_pages, difficulty, special_count)
                    remaining = count - len(questions)
                    if remaining > 0:
                        questions += _sample_from_bank(grade, math_fields, remaining)
                        if len(questions) < count:
                            questions += _generate_math(count - len(questions), grade, difficulty, math_fields)
                else:
                    questions = _sample_from_bank(grade, math_fields, count)
                    if not questions:
                        questions = _generate_math_from_page_bank(grade, math_fields, difficulty)
                    if not questions:
                        logger.info('バンク空のためLLM生成にフォールバック')
                        questions = _generate_math(count, grade, difficulty, math_fields)
            elif subject == '理科' and science_fields:
                questions = _sample_from_science_bank(grade, science_fields, count)
                if not questions:
                    questions = _generate_subject(subject, count, grade, difficulty)
            elif subject == '社会':
                grade_ranges, social_count, cp_count = _get_social_schedule(grade, datetime.now(JST))
                questions = _sample_from_social_bank(grade_ranges, social_count, cp_count)
                if not questions:
                    questions = _generate_subject(subject, count, grade, difficulty)
            elif subject == '国語':
                questions = _sample_from_kokugo_bank(use_reading=False)
                if not questions:
                    questions = _generate_subject(subject, count, grade, difficulty)
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

{FIVE_CHOICE_INSTRUCTION}

以下のJSON形式のみで返してください（他の文章不要）：
{{
  "questions": [
    {{
      "subject": "数学",
      "field": "分野名",
      "question": "問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3  d. 選択肢4  e. 選択肢5",
      "type": "multiple_choice",
      "answer": "a か b か c か d か e",
      "explanation": "解き方（2文程度、計算過程を含む）"
    }}
  ]
}}

難易度：{difficulty}
全問、具体的な場面や状況を設定した文章問題にすること。単純な計算問題（「3x+5=11のxを求めよ」のような式だけの問題）は作らないこと。
問題文は「〜はいくらか」「〜を求めよ」「〜はどれか」のように簡潔に終わること。「どうなるでしょうか」などの冗長な表現は使わないこと。
全{count}問を必ず含めること。"""

    return _call_groq(prompt)


def _generate_subject(subject, count, grade, difficulty):
    guidance = {
        '国語': 'ことわざ・慣用句、文法、漢字、文学作品など',
        '英語': '英検4級レベル（単語・熟語、基本文法、短文穴埋めなど）',
        '社会': '歴史・地理・公民（中学範囲）',
        '理科': '計算問題を中心に出題（オームの法則・速さ・密度・圧力・化学計算など）。図や実験装置が必要な問題は除外。',
    }

    prompt = f"""あなたは中学{subject}の教師です。{grade}の{subject}問題を{count}問作成してください。
分野の参考：{guidance.get(subject, '')}

{FIVE_CHOICE_INSTRUCTION}

以下のJSON形式のみで返してください（他の文章不要）：
{{
  "questions": [
    {{
      "subject": "{subject}",
      "field": "分野名",
      "question": "問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3  d. 選択肢4  e. 選択肢5",
      "type": "multiple_choice",
      "answer": "a か b か c か d か e",
      "explanation": "解説（なぜその答えか、2-3文）"
    }}
  ]
}}

{'難易度：英検4級レベル' if subject == '英語' else f'難易度：{difficulty}、学年：{grade}'}
問題文は簡潔に終わること。「どうなるでしょうか」「何と言いますか」などの冗長な表現は使わず、「〜はどれか」「〜を選べ」「〜はいつか」のように短くまとめること。
全{count}問を必ず含めること。"""

    return _call_groq(prompt)


MAX_RETRY_QUESTIONS = 30


def generate_retry_questions(wrong_questions, settings):
    """間違えた問題を教科別に再出題（最大MAX_RETRY_QUESTIONS問）"""
    grade = settings['grade']
    difficulty = DIFFICULTY_MAP.get(settings['difficulty'], settings['difficulty'])
    # 多すぎる場合は先頭MAX_RETRY_QUESTIONS問に制限（レート制限・タイムアウト対策）
    targets = wrong_questions[:MAX_RETRY_QUESTIONS]
    retry_questions = []
    for i, q in enumerate(targets):
        subject = q.get('subject', '数学')
        # 国語の長文問題はそのまま同じ問題を再出題（生成しない）
        if subject == '国語' and q.get('field') in KOKUGO_READING_FIELDS:
            retry_q = dict(q)
            retry_q['type'] = 'multiple_choice'
            retry_questions.append(retry_q)
            continue
        try:
            if subject == '数学':
                prompt = _make_math_retry_prompt(q, grade, difficulty)
            else:
                prompt = _make_subject_retry_prompt(q, subject, grade, difficulty)
            questions = _call_groq(prompt)
            if questions:
                questions[0].setdefault('subject', subject)
                questions[0]['type'] = 'multiple_choice'
                retry_questions.append(questions[0])
        except Exception as e:
            logger.error(f'再出題生成エラー ({subject}): {e}')
        # Groqレート制限対策（30 RPM = 2秒間隔）
        if i < len(targets) - 1:
            time.sleep(2.5)
    logger.info(f'再挑戦問題: {len(retry_questions)}/{len(targets)}問生成成功')
    return retry_questions


def _make_math_retry_prompt(q, grade, difficulty):
    return f"""あなたは中学数学の教師です。
以下の問題と全く同じ解き方・同じ分野の問題を、数字だけ変えて1問作成してください。

元の問題: {q['question']}
分野: {q['field']}
難易度: {difficulty}、学年: {grade}

問題形式：3択（a/b/c）
選択肢はa. ～  b. ～  c. ～ の形式で問題文に含めること
図・グラフ不要の文章問題のみ（具体的な場面・状況を設定すること。式だけの計算問題は不可）
問題文は簡潔に（「〜はどれか」など）
「$」「$$」「\(」「\)」などのLaTeX記号は絶対に使わないこと
分数はスラッシュで表記（例：（2x－3）／3）、累乗は「x²」「x³」で表記

以下のJSON形式のみで返してください：
{{
  "questions": [
    {{
      "subject": "数学",
      "field": "{q['field']}",
      "question": "問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3  d. 選択肢4  e. 選択肢5",
      "type": "multiple_choice",
      "answer": "a か b か c か d か e",
      "explanation": "解き方（2文程度、計算過程を含む）"
    }}
  ]
}}"""


def _make_subject_retry_prompt(q, subject, grade, difficulty):
    guidance = {
        '国語': 'ことわざ・慣用句、文法、漢字、文学作品など',
        '英語': '英検4級レベル（単語・熟語、基本文法、短文穴埋めなど）',
        '社会': '歴史・地理・公民（中学範囲）',
        '理科': '計算問題を中心に出題（オームの法則・速さ・密度・圧力・化学計算など）',
    }
    diff_str = '難易度：英検4級レベル' if subject == '英語' else f'難易度：{difficulty}、学年：{grade}'
    return f"""あなたは中学{subject}の教師です。
以下の問題と同じ分野・同じ形式で、内容を変えた問題を1問作成してください。

元の問題: {q['question']}
分野: {q['field']}
{diff_str}
参考：{guidance.get(subject, '')}

問題形式：3択（a/b/c）
選択肢はa. ～  b. ～  c. ～ の形式で問題文に含めること
図・グラフ不要の文章問題のみ
問題文は簡潔に（「〜はどれか」「〜を選べ」など）
「$」「$$」「\(」「\)」などのLaTeX記号は絶対に使わないこと
分数はスラッシュで表記（例：（2x－3）／3）、累乗は「x²」「x³」で表記

以下のJSON形式のみで返してください：
{{
  "questions": [
    {{
      "subject": "{subject}",
      "field": "{q['field']}",
      "question": "問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3  d. 選択肢4  e. 選択肢5",
      "type": "multiple_choice",
      "answer": "a か b か c か d か e",
      "explanation": "解説（2-3文）"
    }}
  ]
}}"""


def format_retry_message(questions, round_num):
    """再挑戦問題のメッセージ"""
    lines = [f'【再挑戦 第{round_num}回】', '']
    for i, q in enumerate(questions, 1):
        lines.append(f'{i}. [{q["subject"]}・{q["field"]}] {_clean_latex(q["question"])}')
        lines.append('')
    lines.append('答えを番号付きカンマ区切りで送ってね')
    lines.append(f'例：1.a,2.b,3.c,4.d...')
    return '\n'.join(lines)


def grade_retry(questions, answers):
    """再挑戦問題の採点"""
    results = []
    correct = 0
    wrong_questions = []

    for i, (q, a) in enumerate(zip(questions, answers)):
        ok = _is_correct(a, q['answer'], q['type'])
        if ok:
            correct += 1
        else:
            wrong_questions.append(q)
        results.append({'num': i + 1, 'q': q, 'submitted': a, 'ok': ok})

    total = len(questions)

    # Son: 採点結果
    lines = [f'【再挑戦 採点結果】{correct}/{total}問正解', '']
    for r in results:
        mark = '✓' if r['ok'] else '✗'
        if r['ok']:
            lines.append(f'{r["num"]}. {mark} {r["q"]["field"]}')
        else:
            lines.append(f'{r["num"]}. {mark} {r["q"]["field"]} → 正解：{r["q"]["answer"]}')
    result_msg = '\n'.join(lines)

    # Son: 解説
    lines = ['【解説】', '']
    for r in results:
        lines.append(f'{r["num"]}. {r["q"]["field"]}')
        lines.append(r['q']['explanation'])
        lines.append('')
    explanation_msg = '\n'.join(lines)

    # Parent: レポート
    today = datetime.now(JST)
    lines = [
        f'【ゆうの再挑戦】{today.month}月{today.day}日',
        f'正解率：{correct}/{total}',
        ''
    ]
    for r in results:
        mark = '✓' if r['ok'] else '✗'
        q_text = r['q']['question'][:25] + '...' if len(r['q']['question']) > 25 else r['q']['question']
        lines.append(f'{r["num"]}. {mark} [{r["q"]["field"]}]')
        lines.append(f'   問: {q_text}')
        lines.append(f'   ゆう: {r["submitted"]}　正解: {r["q"]["answer"]}')
        lines.append('')
    parent_msg = '\n'.join(lines)

    return result_msg, explanation_msg, parent_msg, wrong_questions


def _clean_latex(text):
    """LaTeXコマンドや$記号をLINEで読める形に変換する"""
    if not isinstance(text, str):
        return text
    # JSONパース時に \frac の \f が改頁文字（\x0c）に化けた残骸を復元 ※削除禁止
    text = re.sub(r'\x0c([a-zA-Z]+)', r'\\f\1', text)
    # \frac{a}{b} → (a/b)（1段ネストまで対応）
    brace = r'\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}'
    text = re.sub(r'\\[dt]?frac\s*' + brace + r'\s*' + brace, r'(\1/\2)', text)
    # マッチしなかった \frac を除去
    text = re.sub(r'\\[dt]?frac\b', '', text)
    # \sqrt{x} → √x
    text = re.sub(r'\\sqrt\{([^}]*)\}', r'√\1', text)
    # \mathrm{x}, \text{x}, \mathbf{x}, \mathit{x} など → 中身だけ残す
    text = re.sub(r'\\(?:mathrm|text|mathbf|mathit|mathnormal|mathsf|mathtt|mathcal|mathbb)\{([^}]*)\}', r'\1', text)
    # ^{2} → ², ^{3} → ³ など上付き文字
    sup_map = {'0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
               '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹', 'n': 'ⁿ'}
    def replace_sup(m):
        inner = m.group(1)
        return ''.join(sup_map.get(c, c) for c in inner)
    text = re.sub(r'\^\{([^}]*)\}', replace_sup, text)
    text = re.sub(r'\^(\d)', lambda m: sup_map.get(m.group(1), m.group(1)), text)
    # _{n} → そのまま削除（下付き文字はLINEで表示不可）
    text = re.sub(r'_\{([^}]*)\}', r'\1', text)
    # 残ったLaTeXコマンド (\times など) を読める記号に
    latex_symbols = {
        r'\times': '×', r'\div': '÷', r'\cdot': '·',
        r'\leq': '≦', r'\geq': '≧', r'\neq': '≠',
        r'\pm': '±', r'\infty': '∞', r'\pi': 'π',
        r'\alpha': 'α', r'\beta': 'β', r'\theta': 'θ',
        r'\rightarrow': '→', r'\leftarrow': '←',
    }
    for cmd, sym in latex_symbols.items():
        text = text.replace(cmd, sym)
    # $...$ や $$...$$ のデリミタを除去
    text = re.sub(r'\$\$(.+?)\$\$', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\$(.+?)\$', r'\1', text)
    # 残った単体の $ を除去（スペースとして使われているケースも含む）
    text = text.replace('$', '')
    # \( \) \[ \] の除去
    text = re.sub(r'\\\(|\\\)|\\\[|\\\]', '', text)
    # \, \; \: \! \quad \qquad などスペース系コマンドを除去
    text = re.sub(r'\\[,;:!]', '', text)
    text = re.sub(r'\\q?quad\b', ' ', text)
    # 残った \英字+ 形式のコマンドを除去（引数なし）
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
    # 残った単体の \ を除去
    text = text.replace('\\', '')
    return text


def _clean_questions(questions):
    """問題リストの全テキストフィールドからLaTeXを除去する"""
    for q in questions:
        for field in ('question', 'explanation'):
            if field in q:
                q[field] = _clean_latex(q[field])
    return questions


def _call_groq(prompt):
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        response_format={'type': 'json_object'},
        temperature=0.7,
        max_tokens=3000
    )
    content = response.choices[0].message.content
    # \frac 等が JSON の \f（改頁）として誤解釈され LINE に "rac" と表示されるのを防ぐ ※削除禁止
    content = re.sub(r'(?<!\\)\\([fFtTbBrR][a-zA-Z]+)', r'\\\\\1', content)
    data = json.loads(content)
    return _clean_questions(data.get('questions', []))


def format_question_message(questions, weekday):
    today = datetime.now(JST)
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
            lines.append(f'{n}. [{q["field"]}] {_clean_latex(q["question"])}')
            lines.append('')

    lines.append('答えを番号付きカンマ区切りで送ってね')
    lines.append(f'例：1.a,2.b,3.c,4.a...')

    return '\n'.join(lines)


def _normalize(answer_str, question_type):
    return answer_str.strip().upper()


def _is_correct(submitted, expected, question_type):
    return _normalize(submitted, question_type) == _normalize(expected, question_type)


def grade_and_format(questions, answers):
    results = []
    correct = 0
    wrong_questions = []

    for i, (q, a) in enumerate(zip(questions, answers)):
        ok = _is_correct(a, q['answer'], q['type'])
        if ok:
            correct += 1
        else:
            wrong_questions.append(q)
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
    today = datetime.now(JST)
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

    return result_msg, explanation_msg, parent_msg, wrong_questions

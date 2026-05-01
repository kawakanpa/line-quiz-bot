"""
選択肢のない問題に5択の選択肢を追加する後処理スクリプト。
使い方: python fix_choices.py
"""
import json
import time
import logging
import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

client = Groq(api_key=os.environ.get('GROQ_API_KEY'))
MODEL = 'llama-3.3-70b-versatile'
INPUT_FILE = 'math_problems.json'


def has_choices(question_text):
    return '\na.' in question_text or '\na ' in question_text or 'a. ' in question_text


def add_choices(q):
    prompt = f"""以下の数学の問題（{q['grade']}・{q['field']}）に5択の選択肢を追加してください。

問題: {q['question']}

ルール:
- 問題を解いて正しい答えを求めること
- 正解1つ＋数学的に紛らわしい誤答4つを作成する
- 選択肢をa〜eに割り当て、正解をランダムなアルファベットに配置する
- 問題文の末尾に改行して選択肢を追加する
- 図・グラフが必要な場合は「この問題は削除してください」とだけ返す

JSON形式のみで返してください:
{{
  "question": "元の問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3  d. 選択肢4  e. 選択肢5",
  "answer": "正解のアルファベット（a/b/c/d/e）",
  "explanation": "解き方（2-3文、計算過程を含む）",
  "skip": false
}}

図・グラフが必要な場合のみ: {{"skip": true}}"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            response_format={'type': 'json_object'},
            temperature=0.5,
            max_tokens=800
        )
        data = json.loads(response.choices[0].message.content)
        return data
    except Exception as e:
        logger.error(f'id={q["id"]} エラー: {e}')
        return None


def main():
    d = json.load(open(INPUT_FILE, 'r', encoding='utf-8'))
    problems = d['problems']

    need_fix = [q for q in problems if not has_choices(q['question'])]
    logger.info(f'補完対象: {len(need_fix)}問 / 合計{len(problems)}問')

    fixed = 0
    skipped = 0
    for i, q in enumerate(need_fix):
        logger.info(f'[{i+1}/{len(need_fix)}] id={q["id"]} [{q["field"]}]')
        result = add_choices(q)

        if result is None:
            continue
        if result.get('skip'):
            logger.info(f'  → 図が必要なためスキップ（削除対象）')
            q['_delete'] = True
            skipped += 1
        else:
            q['question'] = result.get('question', q['question'])
            q['answer'] = result.get('answer', q['answer'])
            q['explanation'] = result.get('explanation', q.get('explanation', ''))
            fixed += 1
            logger.info(f'  → 補完完了 answer={q["answer"]}')

        time.sleep(2)

    # 削除フラグがついた問題を除外
    problems = [q for q in problems if not q.get('_delete')]

    # id再採番
    for i, q in enumerate(problems, 1):
        q['id'] = i

    d['problems'] = problems
    d['total'] = len(problems)
    with open(INPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

    logger.info(f'完了: {fixed}問補完, {skipped}問削除 → 残{len(problems)}問')


if __name__ == '__main__':
    main()

"""
社会PDFページを画像化してGroq視覚モデルで問題を抽出し、social_problems.jsonに保存する。
各章が終わるたびに自動保存。ページ重複チェック付き（再実行しても安全）。
使い方:
  python extract_social_problems.py                            # 全章処理
  python extract_social_problems.py --append                   # 既存データに追記
  python extract_social_problems.py --grade_range 1年          # 特定学年範囲のみ
  python extract_social_problems.py --grade_range 1年 --append # 追記＋再開
"""
import os
import json
import time
import base64
import logging
import argparse
import fitz
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

client = Groq(api_key=os.environ.get('GROQ_API_KEY'))
VISION_MODEL = 'meta-llama/llama-4-scout-17b-16e-instruct'

PDF_PATH = r'D:\ゆうちゃん自由自在\社会（自由自在）.pdf'
OUTPUT_FILE = 'social_problems.json'
DPI = 150

# (grade_range, field, start_page, end_page, checkpoint_pages)
CHAPTER_MAP = [
    ("1年", "世界のすがたと人々の生活・環境", 18, 33, [31]),
    ("1年", "世界の諸地域", 34, 109, [69, 107]),
    ("1年", "歴史の流れと地域の歴史", 222, 231, []),
    ("1年", "古代までの日本", 232, 274, [274]),
    ("2年1学期前半", "日本のすがたと世界から見た日本", 110, 157, [155]),
    ("2年1学期後半", "日本の諸地域と身近な地域の調査", 158, 221, [191, 220]),
    ("2年2学期", "中世の日本", 275, 299, [297]),
    ("2年3学期", "近世の日本", 300, 339, [339]),
    ("3年1学期", "近代日本のあゆみと国際関係", 340, 385, [384]),
    ("3年2学期", "2つの世界大戦と日本", 386, 409, [407]),
    ("3年2学期", "現代の日本と世界", 410, 431, [430]),
    ("3年2学期", "現代社会とわたしたちの生活", 432, 457, [457]),
    ("3年2学期", "わたしたちの生活と民主政治", 458, 510, [510]),
    ("3年2学期後半", "わたしたちの生活と経済", 511, 551, [551]),
    ("3年3学期", "国際社会とわたしたち", 552, 580, [579]),
]


def page_to_base64(pdf, page_num):
    page = pdf[page_num - 1]
    pixmap = page.get_pixmap(dpi=DPI)
    return base64.b64encode(pixmap.tobytes('png')).decode()


def extract_question_from_image(img_b64, grade_range, field, page_num, is_checkpoint):
    checkpoint_note = "（重点チェックページ：まとめ・確認問題が中心）" if is_checkpoint else ""
    prompt = f"""この中学社会の問題集ページ（{field}・p.{page_num}）{checkpoint_note}から問題を1問選んで5択問題に変換してください。

ルール：
- 地図・図・写真・グラフが必要な問題は絶対に作らないこと
- 文章だけで完結する問題にすること
- 正解1つ＋紛らわしい誤答4つを生成する
- 自分で解いて正解を必ず確認すること
- 問題が全くない場合は questions を空リストにする

JSON形式のみで返してください：
{{"questions":[{{"subject":"社会","grade_range":"{grade_range}","field":"{field}","page":{page_num},"is_checkpoint":{str(is_checkpoint).lower()},"checkpoint_page":{page_num if is_checkpoint else "null"},"question":"問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3  d. 選択肢4  e. 選択肢5","type":"multiple_choice","answer":"a か b か c か d か e","explanation":"解説（2-3文）"}}]}}"""

    try:
        response = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{img_b64}'}},
                    {'type': 'text', 'text': prompt}
                ]
            }],
            response_format={'type': 'json_object'},
            max_tokens=1000
        )
        data = json.loads(response.choices[0].message.content)
        return data.get('questions', [])
    except Exception as e:
        logger.error(f'問題抽出エラー: {e}')
        return []


def load_existing(output_file):
    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            return json.load(f).get('problems', [])
    return []


def save(problems, output_file):
    for i, q in enumerate(problems, 1):
        q['id'] = i
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({'problems': problems, 'total': len(problems)}, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--grade_range', action='append', help='処理する学年範囲（複数指定可）')
    parser.add_argument('--append', action='store_true', help='既存データに追記')
    args = parser.parse_args()

    all_questions = load_existing(OUTPUT_FILE) if args.append else []
    # 処理済みページを記録（再実行時のスキップ用）
    done_pages = {(q.get('field'), q.get('page')) for q in all_questions}
    logger.info(f'開始時点のストック: {len(all_questions)}問（処理済みページ: {len(done_pages)}）')

    with fitz.open(PDF_PATH) as pdf:
        total_pages = len(pdf)
        logger.info(f'社会PDF読み込み完了: {total_pages}ページ')

        for grade_range, field, start, end, checkpoint_pages in CHAPTER_MAP:
            if args.grade_range and grade_range not in args.grade_range:
                continue

            page_nums = list(range(start, min(end + 1, total_pages + 1)))
            # 処理済みページをスキップ
            todo_pages = [p for p in page_nums if (field, p) not in done_pages]
            if not todo_pages:
                logger.info(f'{grade_range} {field}: 全ページ処理済みスキップ')
                continue
            logger.info(f'{grade_range} {field}: {len(todo_pages)}ページ処理開始（残り）')

            field_count = 0
            for page_num in todo_pages:
                is_checkpoint = page_num in checkpoint_pages
                logger.info(f'  p.{page_num}{"【重点チェック】" if is_checkpoint else ""} 処理中...')
                img_b64 = page_to_base64(pdf, page_num)
                questions = extract_question_from_image(img_b64, grade_range, field, page_num, is_checkpoint)

                if questions:
                    all_questions.extend(questions)
                    done_pages.add((field, page_num))
                    field_count += len(questions)
                    logger.info(f'  → {len(questions)}問抽出（{field}累計{field_count}問）')
                else:
                    logger.info(f'  → 問題なし（スキップ）')

                time.sleep(3)

            save(all_questions, OUTPUT_FILE)
            logger.info(f'{grade_range} {field} 完了・保存: {field_count}問（合計{len(all_questions)}問）')

    logger.info(f'全処理完了: 合計{len(all_questions)}問 → {OUTPUT_FILE}')


if __name__ == '__main__':
    main()

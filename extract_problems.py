"""
PDFページを画像化してGroq視覚モデルで問題を抽出し、math_problems.jsonに保存する。
使い方:
  python extract_problems.py                        # 全章処理
  python extract_problems.py --field 正の数・負の数  # 特定章のみ
  python extract_problems.py --append               # 既存データに追記
"""
import os
import json
import time
import base64
import random
import logging
import argparse
import fitz  # PyMuPDF
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

client = Groq(api_key=os.environ.get('GROQ_API_KEY'))
VISION_MODEL = 'meta-llama/llama-4-scout-17b-16e-instruct'

PDF_PATH = r'C:\Users\kawak\OneDrive\Desktop\claude作業用\ゆうちゃん自由自在\数学（自由自在）.pdf'
OUTPUT_FILE = 'math_problems.json'
DPI = 150
PAGES_PER_FIELD = 15  # 各章から何ページサンプリングするか

CHAPTER_MAP = {
    "中学1年": {
        "正の数・負の数": (20, 45),
        "文字と式":       (66, 87),
        "式の計算":       (88, 111),
        "方程式":         (150, 181),
        "比例と反比例":   (230, 253),
        "平面図形":       (305, 339),
        "空間図形":       (340, 369),
        "データの活用":   (478, 499),
    }
}


def page_to_base64(pdf, page_num):
    page = pdf[page_num - 1]
    pixmap = page.get_pixmap(dpi=DPI)
    return base64.b64encode(pixmap.tobytes('png')).decode()


def extract_question_from_image(img_b64, grade, field):
    prompt = f"""この数学の問題集ページ（{grade}・{field}）から「類題」を1問選んで5択問題に変換してください。

ルール：
- 具体的な場面設定のある文章問題にする
- グラフ・図が必要な問題は数値・条件を文章に置き換える
- 正解1つ＋数学的に紛らわしい誤答4つを生成する
- 自分で解いて正解を必ず確認すること
- 「類題」が見つからない場合は練習問題でも可
- 問題が全くない場合は questions を空リストにする

JSON形式のみで返してください：
{{"questions":[{{"subject":"数学","grade":"{grade}","field":"{field}","question":"問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3  d. 選択肢4  e. 選択肢5","type":"multiple_choice","answer":"a か b か c か d か e","explanation":"解き方（2-3文、計算過程を含む）"}}]}}"""

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
    parser.add_argument('--field', help='特定の章のみ処理（例: 正の数・負の数）')
    parser.add_argument('--append', action='store_true', help='既存データに追記')
    args = parser.parse_args()

    all_questions = load_existing(OUTPUT_FILE) if args.append else []

    with fitz.open(PDF_PATH) as pdf:
        total_pages = len(pdf)
        logger.info(f'PDF読み込み完了: {total_pages}ページ')

        for grade, fields in CHAPTER_MAP.items():
            for field, (start, end) in fields.items():
                if args.field and args.field != field:
                    continue

                page_nums = list(range(start, min(end + 1, total_pages + 1)))
                sampled = sorted(random.sample(page_nums, min(PAGES_PER_FIELD, len(page_nums))))
                logger.info(f'{grade} {field}: {len(sampled)}ページ処理開始')

                field_count = 0
                for page_num in sampled:
                    logger.info(f'  p.{page_num} 処理中...')
                    img_b64 = page_to_base64(pdf, page_num)
                    questions = extract_question_from_image(img_b64, grade, field)

                    if questions:
                        all_questions.extend(questions)
                        field_count += len(questions)
                        logger.info(f'  → {len(questions)}問抽出（{field}累計{field_count}問）')
                    else:
                        logger.info(f'  → 問題なし（スキップ）')

                    time.sleep(3)  # レート制限対策

                logger.info(f'{field} 完了: {field_count}問')

    save(all_questions, OUTPUT_FILE)
    logger.info(f'保存完了: 合計{len(all_questions)}問 → {OUTPUT_FILE}')


if __name__ == '__main__':
    main()

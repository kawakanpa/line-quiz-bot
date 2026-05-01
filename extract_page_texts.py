"""
PDFから各章のページテキストをサンプリングしてmath_page_bank.jsonに保存する。
LLM不要。ローカルで一度だけ実行する。
使い方: python extract_page_texts.py
"""
import json
import random
import pdfplumber

PDF_PATH = r'C:\Users\kawak\OneDrive\Desktop\claude作業用\ゆうちゃん自由自在\数学（自由自在）.pdf'
OUTPUT_FILE = 'math_page_bank.json'
PAGES_PER_FIELD = 15  # 各章から何ページサンプリングするか

CHAPTER_MAP = {
    "中学1年": {
        "正の数・負の数": (20, 45),
        "文字と式":       (66, 87),
        "方程式":         (150, 181),
        "比例と反比例":   (230, 253),
        "平面図形":       (305, 339),
        "空間図形":       (340, 369),
        "データの活用":   (478, 499),
    }
}


def main():
    bank = {}
    with pdfplumber.open(PDF_PATH) as pdf:
        total = len(pdf.pages)
        for grade, fields in CHAPTER_MAP.items():
            bank[grade] = {}
            for field, (start, end) in fields.items():
                page_nums = list(range(start, min(end + 1, total + 1)))
                sampled = sorted(random.sample(page_nums, min(PAGES_PER_FIELD, len(page_nums))))
                pages = {}
                for p in sampled:
                    text = pdf.pages[p - 1].extract_text()
                    if text and len(text.strip()) > 50:
                        pages[str(p)] = text.strip()
                bank[grade][field] = pages
                print(f'{grade} {field}: {len(pages)}ページ抽出')

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)
    print(f'\n保存完了: {OUTPUT_FILE}')


if __name__ == '__main__':
    main()

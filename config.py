import json
import os

SETTINGS_FILE = 'settings.json'

# 難易度ラベル → LLMへ渡す具体的な指示文
DIFFICULTY_MAP = {
    "基礎": "基礎レベル：定義・基本公式をそのまま使う問題。計算ミスなく解ける生徒が半分以上いる難易度",
    "標準": "標準レベル：教科書の練習問題レベル。1〜2ステップの計算が必要",
    "応用": "応用レベル：複数ステップの計算が必要な問題。公立高校入試の標準問題相当",
    "難問": "発展レベル：思考力・多段階推論が必要。公立入試の難問〜私立入試レベル",
}

DEFAULT_SETTINGS = {
    "son_user_id": "",
    "parent_user_id": "",
    "parent2_user_id": "",
    "send_time": "12:00",
    "grade": "中学1年",
    "difficulty": "応用",
    "schedule": {
        "月": {"数学": 10, "英語": 20, "社会": 20},
        "火": {"数学": 10, "英語": 20, "理科": 20},
        "水": {"数学": 10, "英語": 20, "国語": 20},
        "木": {"数学": 10, "英語": 20, "社会": 20},
        "金": {"数学": 10, "英語": 20, "理科": 20},
        "土": {"数学": 10, "英語": 20, "国語": 20},
        "日": {"数学": 10, "英語": 20, "理科": 20}
    },
    "math_fields": {
        "中学1年": ["正の数・負の数", "文字と式", "式の計算", "方程式", "比例と反比例", "平面図形", "空間図形", "データの活用"],
        "中学2年": ["式の計算", "連立方程式", "一次関数", "図形の調べ方", "図形の性質と証明", "確率", "データの分布"],
        "中学3年": ["多項式", "平方根", "二次方程式", "関数y=ax²", "相似な図形", "円", "三平方の定理", "標本調査"]
    },
    "math_special_pages": {
        "中学1年": [],
        "中学2年": [],
        "中学3年": []
    },
    "science_fields": {
        "中学1年": ["光と音", "力と圧力", "物質のすがた", "気体と水溶液", "植物の生活と種類", "大地の変化"],
        "中学2年": [],
        "中学3年": []
    }
}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        for key, value in DEFAULT_SETTINGS.items():
            if key not in settings:
                settings[key] = value
    else:
        settings = DEFAULT_SETTINGS.copy()

    # env vars take priority for user IDs
    if os.environ.get('SON_USER_ID'):
        settings['son_user_id'] = os.environ['SON_USER_ID']
    if os.environ.get('PARENT_USER_ID'):
        settings['parent_user_id'] = os.environ['PARENT_USER_ID']
    if os.environ.get('PARENT2_USER_ID'):
        settings['parent2_user_id'] = os.environ['PARENT2_USER_ID']

    return settings


def save_settings(settings):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

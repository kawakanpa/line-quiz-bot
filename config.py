import json
import os

SETTINGS_FILE = 'settings.json'

DEFAULT_SETTINGS = {
    "son_user_id": "",
    "parent_user_id": "",
    "send_time": "12:00",
    "grade": "中学1年",
    "difficulty": "やや難しめ",
    "schedule": {
        "月": {"数学": 5, "国語": 3, "英語": 3},
        "火": {"数学": 5, "理科": 3},
        "水": {"数学": 5, "社会": 3, "英語": 3},
        "木": {"数学": 5, "国語": 3},
        "金": {"数学": 5, "理科": 3, "英語": 3},
        "土": {"数学": 5, "国語": 3, "社会": 3, "理科": 3},
        "日": {"数学": 10, "英語": 3}
    },
    "math_fields": {
        "中学1年": ["正の数・負の数", "文字と式", "方程式", "比例と反比例", "平面図形", "空間図形", "データの活用"],
        "中学2年": ["式の計算", "連立方程式", "一次関数", "図形の調べ方", "図形の性質と証明", "確率", "データの分布"],
        "中学3年": ["多項式", "平方根", "二次方程式", "関数y=ax²", "相似な図形", "円", "三平方の定理", "標本調査"]
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

    return settings


def save_settings(settings):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

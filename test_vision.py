import base64
import json
from groq import Groq
from dotenv import load_dotenv
import os

load_dotenv()

with open('test_page.png', 'rb') as f:
    img_b64 = base64.b64encode(f.read()).decode()

client = Groq(api_key=os.environ.get('GROQ_API_KEY'))

prompt = """このページから「類題」を1問選び、5択問題に変換してください。

ルール：
- 具体的な場面設定のある文章問題にする
- グラフ・図が必要な問題は数値を文章に置き換える
- 正解1つ＋数学的に紛らわしい誤答4つを生成する
- 自分で解いて正解を確認すること

JSON形式のみで返してください：
{"questions":[{"subject":"数学","grade":"中学1年","field":"正の数と負の数","question":"問題文\\na. 選択肢1  b. 選択肢2  c. 選択肢3  d. 選択肢4  e. 選択肢5","type":"multiple_choice","answer":"a か b か c か d か e","explanation":"解き方（2-3文）"}]}"""

response = client.chat.completions.create(
    model='meta-llama/llama-4-scout-17b-16e-instruct',
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
for q in data.get('questions', []):
    print(f"分野: {q['field']}")
    print(f"問題: {q['question']}")
    print(f"正解: {q['answer']}")
    print(f"解説: {q['explanation']}")

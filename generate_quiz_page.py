#!/usr/bin/env python3
"""毎日のクイズHTMLページを生成してdocs/に保存しGmailで通知する"""
import sys
import os
import json
import re
import smtplib
import logging
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
WEEKDAY_MAP = {0: '月', 1: '火', 2: '水', 3: '木', 4: '金', 5: '土', 6: '日'}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_settings
from quiz import generate_daily_questions, generate_retry_questions


def _parse_choices(question_text):
    """問題文から(本文, 選択肢リスト)を返す"""
    if not question_text:
        return '', []
    sep = re.search(r'(\n\s*a\.|\s+a\.(?=\s))', question_text)
    if not sep:
        return question_text.strip(), []
    main_q = question_text[:sep.start()].strip()
    choice_text = question_text[sep.start():].strip()
    choices = []
    for m in re.finditer(r'\b([a-e])\.\s+(.+?)(?=\s+[a-e]\.\s|\s+[a-e]\.$|$)', choice_text):
        choices.append(m.group(2).strip())
    return main_q, choices


def _get_answer_index(q):
    label = (q.get('answer') or 'a').strip().lower()[:1]
    return 'abcde'.index(label) if label in 'abcde' else 0


def _prepare_item(q, retry_q=None):
    """問題データをHTML埋め込み用に整形する"""
    main_q, choices = _parse_choices(q.get('question') or '')
    if not choices:
        choices = [str(c) for c in q.get('choices', []) if c]
    ans_idx = _get_answer_index(q)

    if retry_q:
        retry_main, retry_choices = _parse_choices(retry_q.get('question') or '')
        if not retry_choices:
            retry_choices = [str(c) for c in retry_q.get('choices', []) if c]
        retry = {
            'question': retry_main,
            'choices': retry_choices,
            'answer_index': _get_answer_index(retry_q),
            'explanation': retry_q.get('explanation', '')
        }
    else:
        # 数学以外は同じ問題をそのまま再出題
        retry = {
            'question': main_q,
            'choices': choices,
            'answer_index': ans_idx,
            'explanation': q.get('explanation', '')
        }

    return {
        'subject': q.get('subject', ''),
        'field': q.get('field', ''),
        'question': main_q,
        'choices': choices,
        'answer_index': ans_idx,
        'explanation': q.get('explanation', ''),
        'retry': retry
    }


def _send_email(to_addr, subject, html_body):
    """Gmail SMTPでHTML形式メールを送信する"""
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_password = os.environ.get('GMAIL_APP_PASSWORD')
    if not gmail_user or not gmail_password:
        logger.warning('GMAIL_USER / GMAIL_APP_PASSWORD が未設定のためメール未送信')
        return False
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = gmail_user
    msg['To'] = to_addr
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(gmail_user, gmail_password)
            smtp.send_message(msg)
        logger.info(f'メール送信完了: {to_addr}')
        return True
    except Exception as e:
        logger.error(f'メール送信エラー: {e}')
        return False


def _build_html(questions_data, date_str, subjects_str):
    """クイズHTMLページを生成する"""
    count = len(questions_data)
    data_json = json.dumps(questions_data, ensure_ascii=False)

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>クイズ {date_str}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;background:#f0f4f8;color:#333;padding:12px;font-size:15px}}
.hdr{{background:linear-gradient(135deg,#2e7d32,#43a047);color:#fff;padding:18px 16px;border-radius:14px;margin-bottom:16px;text-align:center;box-shadow:0 4px 12px rgba(46,125,50,.3)}}
.hdr h1{{font-size:1.3em;margin-bottom:6px}}
.hdr p{{font-size:.85em;opacity:.9}}
.score-card{{display:none;background:#fff;border-radius:14px;padding:20px;margin-bottom:16px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
.score-num{{font-size:3em;font-weight:700;color:#2e7d32;line-height:1}}
.score-sub{{color:#666;margin-top:6px;font-size:.9em}}
.qcard{{background:#fff;border-radius:14px;padding:16px;margin-bottom:14px;box-shadow:0 2px 6px rgba(0,0,0,.08)}}
.qcard.ok{{border-left:5px solid #43a047}}
.qcard.ng{{border-left:5px solid #e53935}}
.qhead{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}}
.qnum{{font-weight:700;color:#2e7d32;font-size:1.05em}}
.tag{{background:#e8f5e9;color:#1b5e20;padding:3px 10px;border-radius:20px;font-size:.78em}}
.qtext{{line-height:1.7;margin-bottom:12px;white-space:pre-wrap}}
.clabel{{display:flex;align-items:flex-start;padding:10px 12px;border:2px solid #e0e0e0;border-radius:10px;margin-bottom:7px;cursor:pointer;transition:border-color .15s;line-height:1.5}}
.clabel:hover{{border-color:#43a047}}
.clabel input{{margin-top:2px;margin-right:10px;flex-shrink:0}}
.hl-ok{{background:#e8f5e9!important;border-color:#43a047!important}}
.hl-ng{{background:#ffebee!important;border-color:#e53935!important}}
.resarea{{display:none;margin-top:12px}}
.badge-ok{{display:inline-block;background:#43a047;color:#fff;padding:5px 14px;border-radius:20px;font-size:.88em;font-weight:700;margin-bottom:8px}}
.badge-ng{{display:inline-block;background:#e53935;color:#fff;padding:5px 14px;border-radius:20px;font-size:.88em;font-weight:700;margin-bottom:8px}}
.expl{{background:#f9f9f9;border-left:4px solid #43a047;padding:10px 12px;border-radius:6px;font-size:.88em;line-height:1.7;margin-bottom:12px;white-space:pre-wrap}}
.rbtns{{display:flex;gap:8px}}
.btn{{padding:10px 0;border:none;border-radius:10px;font-size:.9em;font-weight:700;cursor:pointer;flex:1;text-align:center}}
.btn-ok{{background:#43a047;color:#fff}}
.btn-retry{{background:#f4511e;color:#fff}}
.retrybox{{display:none;background:#fff8e1;border:2px solid #ffb300;border-radius:12px;padding:14px;margin-top:12px}}
.retrybox h4{{color:#e65100;margin-bottom:10px;font-size:.95em}}
.btn-confirm{{display:block;width:100%;padding:11px;background:#1976d2;color:#fff;border:none;border-radius:10px;font-size:.95em;font-weight:700;cursor:pointer;margin-top:10px}}
.rresult{{display:none;margin-top:10px}}
.subwrap{{text-align:center;padding:10px 0 24px}}
.btn-submit{{background:#1976d2;color:#fff;padding:15px 48px;font-size:1.1em;font-weight:700;border:none;border-radius:14px;cursor:pointer;box-shadow:0 4px 12px rgba(25,118,210,.35)}}
.ok-msg{{color:#43a047;font-weight:700;font-size:.9em}}
</style>
</head>
<body>
<div class="hdr">
  <h1>📚 今日のクイズ</h1>
  <p>{date_str} ／ {subjects_str} ／ 全{count}問</p>
</div>
<div id="scorecard" class="score-card"></div>
<div id="qlist"></div>
<div class="subwrap" id="subwrap">
  <button class="btn-submit" onclick="submitAll()">答えを提出する</button>
</div>
<script>
const QS={data_json};
const LC=['a','b','c','d','e'];
function esc(s){{return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}}
function init(){{
  let h='';
  QS.forEach((q,i)=>{{
    const ch=q.choices.map((c,ci)=>`<label class="clabel" id="lbl-${{i}}-${{ci}}"><input type="radio" name="q${{i}}" value="${{ci}}"><span>${{LC[ci]}}. ${{esc(c)}}</span></label>`).join('');
    const rq=q.retry;
    const rch=rq.choices.map((c,ci)=>`<label class="clabel" id="rlbl-${{i}}-${{ci}}"><input type="radio" name="rq${{i}}" value="${{ci}}"><span>${{LC[ci]}}. ${{esc(c)}}</span></label>`).join('');
    h+=`<div class="qcard" id="card-${{i}}">
<div class="qhead"><span class="qnum">問${{i+1}}</span><span class="tag">${{esc(q.subject)}} / ${{esc(q.field)}}</span></div>
<div class="qtext">${{esc(q.question)}}</div>
<div id="ch-${{i}}">${{ch}}</div>
<div class="resarea" id="res-${{i}}">
  <div id="bdg-${{i}}"></div>
  <div class="expl">${{esc(q.explanation)}}</div>
  <div class="rbtns" id="rbtns-${{i}}">
    <button class="btn btn-retry" onclick="showRetry(${{i}})">わかった！練習問題を解く 🔄</button>
  </div>
</div>
<div class="retrybox" id="retry-${{i}}">
  <h4>🔄 もう一度チャレンジ！</h4>
  <div class="qtext">${{esc(rq.question)}}</div>
  <div id="rch-${{i}}">${{rch}}</div>
  <button class="btn-confirm" id="rcbtn-${{i}}" onclick="submitRetry(${{i}})">確認する</button>
  <div class="rresult" id="rres-${{i}}">
    <div id="rbdg-${{i}}"></div>
    <div class="expl">${{esc(rq.explanation)}}</div>
  </div>
</div>
</div>`;
  }});
  document.getElementById('qlist').innerHTML=h;
}}
function submitAll(){{
  const missing=QS.reduce((a,_,i)=>{{if(!document.querySelector(`input[name="q${{i}}"]:checked`))a.push(i+1);return a;}},[]);
  if(missing.length){{alert(`問${{missing.join('、')}}がまだ答えていません！`);return;}}
  let cor=0;
  QS.forEach((q,i)=>{{
    const sv=parseInt(document.querySelector(`input[name="q${{i}}"]:checked`).value);
    const ok=sv===q.answer_index;
    if(ok)cor++;
    document.querySelectorAll(`#ch-${{i}} .clabel`).forEach((l,li)=>{{
      if(li===q.answer_index)l.classList.add('hl-ok');
      else if(li===sv&&!ok)l.classList.add('hl-ng');
    }});
    document.querySelectorAll(`input[name="q${{i}}"]`).forEach(r=>r.disabled=true);
    document.getElementById(`bdg-${{i}}`).innerHTML=ok?
      '<span class="badge-ok">✓ 正解！</span>':
      `<span class="badge-ng">✗ 不正解（正解: ${{LC[q.answer_index]}}）</span>`;
    document.getElementById(`res-${{i}}`).style.display='block';
    document.getElementById(`card-${{i}}`).classList.add(ok?'ok':'ng');
    if(ok){{const rb=document.getElementById(`rbtns-${{i}}`);if(rb)rb.style.display='none';}}
  }});
  const sc=document.getElementById('scorecard');
  sc.innerHTML=`<div class="score-num">${{cor}}<span style="font-size:.5em;color:#666"> / ${{QS.length}}</span></div><div class="score-sub">正解率 ${{Math.round(cor/QS.length*100)}}%</div><p style="margin-top:10px;color:#555;font-size:.88em">各問題の解説を確認してね！</p>`;
  sc.style.display='block';
  document.getElementById('subwrap').style.display='none';
  sc.scrollIntoView({{behavior:'smooth'}});
}}
function markOk(i){{document.getElementById(`rbtns-${{i}}`).innerHTML='<span class="ok-msg">✓ 理解しました！</span>';}}
function showRetry(i){{
  document.getElementById(`retry-${{i}}`).style.display='block';
  document.getElementById(`rbtns-${{i}}`).style.display='none';
  document.getElementById(`retry-${{i}}`).scrollIntoView({{behavior:'smooth'}});
}}
function submitRetry(i){{
  const rq=QS[i].retry;
  const sel=document.querySelector(`input[name="rq${{i}}"]:checked`);
  if(!sel){{alert('答えを選んでください！');return;}}
  const sv=parseInt(sel.value);
  const ok=sv===rq.answer_index;
  document.querySelectorAll(`#rch-${{i}} .clabel`).forEach((l,li)=>{{
    if(li===rq.answer_index)l.classList.add('hl-ok');
    else if(li===sv&&!ok)l.classList.add('hl-ng');
  }});
  document.querySelectorAll(`input[name="rq${{i}}"]`).forEach(r=>r.disabled=true);
  document.getElementById(`rbdg-${{i}}`).innerHTML=ok?
    '<span class="badge-ok">✓ 正解！よくできました！</span>':
    `<span class="badge-ng">✗ 不正解（正解: ${{LC[rq.answer_index]}}）</span>`;
  document.getElementById(`rres-${{i}}`).style.display='block';
  document.getElementById(`rcbtn-${{i}}`).style.display='none';
}}
init();
</script>
</body>
</html>'''


def main():
    now = datetime.now(JST)
    weekday = WEEKDAY_MAP[now.weekday()]
    date_str = f'{now.year}年{now.month}月{now.day}日({weekday})'
    date_key = now.strftime('%Y-%m-%d')

    settings = load_settings()
    subjects_today = settings['schedule'].get(weekday, {})
    if not subjects_today:
        logger.info(f'{weekday}曜日は問題なし')
        return

    logger.info(f'問題生成開始: {subjects_today}')
    questions = generate_daily_questions(subjects_today, settings)
    if not questions:
        logger.error('問題生成失敗')
        sys.exit(1)
    logger.info(f'問題生成完了: {len(questions)}問')

    # 数学のみ再挑戦問題を生成（数字違いの問題）。他の科目は同じ問題を再出題。
    retry_map = {}
    math_qs = [(i, q) for i, q in enumerate(questions) if q.get('subject') == '数学']
    logger.info(f'数学の再挑戦問題を生成: {len(math_qs)}問')
    for idx, q in math_qs:
        try:
            result = generate_retry_questions([q], settings)
            if result:
                retry_map[idx] = result[0]
                logger.info(f'  数学再挑戦 問{idx + 1}: 生成完了')
        except Exception as e:
            logger.error(f'  数学再挑戦 問{idx + 1}: エラー {e}')

    questions_data = [_prepare_item(q, retry_map.get(i)) for i, q in enumerate(questions)]

    subjects_str = '・'.join(dict.fromkeys(q.get('subject', '') for q in questions))
    html = _build_html(questions_data, date_str, subjects_str)

    os.makedirs('docs', exist_ok=True)
    filepath = f'docs/quiz-{date_key}.html'
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html)
    logger.info(f'HTML保存完了: {filepath}')

    pages_base = os.environ.get('PAGES_BASE_URL', '').rstrip('/')
    quiz_url = f'{pages_base}/quiz-{date_key}.html' if pages_base else filepath

    recipient = os.environ.get('RECIPIENT_EMAIL')
    if recipient:
        body = f'''<div style="font-family:sans-serif;max-width:500px;margin:0 auto">
<h2 style="color:#2e7d32">📚 今日のクイズができました！</h2>
<p style="margin:12px 0">{date_str}<br>{subjects_str}（{len(questions)}問）</p>
<p style="margin:16px 0">
  <a href="{quiz_url}" style="display:inline-block;background:#2e7d32;color:white;padding:14px 28px;border-radius:10px;text-decoration:none;font-weight:bold;font-size:1.1em">クイズを開く</a>
</p>
<p style="color:#666;font-size:.9em">リンクをゆうに送ってください。</p>
</div>'''
        _send_email(recipient, f'今日のクイズ {date_str}', body)
    else:
        logger.info(f'RECIPIENT_EMAIL 未設定。URL: {quiz_url}')


if __name__ == '__main__':
    main()

#!/bin/bash
# GPTHub: inject custom CSS + JS vars into OpenWebUI index.html on every container start
# CSS injection is optional — failures here must never prevent OpenWebUI from starting
set +e

# ── Seed database on first boot ───────────────────────────────────────────────
# On a fresh install the webui_data volume is empty. Copy the pre-configured
# seed DB (models + filter + config, no user data) so OpenWebUI starts with
# the correct model names, auto-search filter, and UI settings immediately.
SEED="/app/webui-seed.db"
DB="/app/backend/data/webui.db"
if [ -f "$SEED" ]; then
  if [ ! -f "$DB" ]; then
    echo "[GPTHub] Fresh install detected — seeding webui.db from webui-seed.db"
    cp "$SEED" "$DB"
  else
    # DB exists but check if models table is empty (someone wiped it)
    MODEL_COUNT=$(python3 -c "import sqlite3; c=sqlite3.connect('$DB'); print(c.execute('SELECT COUNT(*) FROM model').fetchone()[0])" 2>/dev/null || echo "0")
    if [ "$MODEL_COUNT" = "0" ]; then
      echo "[GPTHub] Models table empty — re-seeding model and function tables"
      python3 -c "
import sqlite3, shutil
src = '$SEED'
dst = '$DB'
seed = sqlite3.connect(src)
live = sqlite3.connect(dst)
# Copy model rows
live.execute('DELETE FROM model')
for row in seed.execute('SELECT * FROM model').fetchall():
    live.execute('INSERT OR REPLACE INTO model VALUES (' + ','.join(['?']*len(row)) + ')', row)
# Copy function rows
live.execute('DELETE FROM function')
for row in seed.execute('SELECT * FROM function').fetchall():
    live.execute('INSERT OR REPLACE INTO function VALUES (' + ','.join(['?']*len(row)) + ')', row)
live.commit()
print('re-seeded models and functions')
" 2>/dev/null
    fi
  fi
fi

CSS_FILE="/app/custom-theme.css"
INDEX="/app/build/index.html"

if [ -f "$CSS_FILE" ] && [ -f "$INDEX" ]; then
  python3 -c "
import sys, re

css_path, idx_path = sys.argv[1], sys.argv[2]
with open(css_path, 'r') as f:
    css = f.read()
with open(idx_path, 'r') as f:
    html = f.read()

# Remove previous injections
html = re.sub(r'<style id=\"gpthub-theme\">.*?</style>\n?', '', html, flags=re.DOTALL)
html = re.sub(r'<script id=\"gpthub-vars\">.*?</script>\n?', '', html, flags=re.DOTALL)

# JS snippet: set CSS vars as inline styles on <html> — highest cascade priority,
# beats any dynamically-injected Tailwind stylesheet.
js = '''<script id=\"gpthub-vars\">(function(){
  var vars = {
    '--color-gray-50':  '#f5f5f5',
    '--color-gray-100': '#e0e0e0',
    '--color-gray-200': '#b0b0b0',
    '--color-gray-300': '#8a8a8a',
    '--color-gray-400': '#666666',
    '--color-gray-500': '#4a4a4a',
    '--color-gray-600': '#333333',
    '--color-gray-700': '#252528',
    '--color-gray-800': '#1c1c1f',
    '--color-gray-850': '#161618',
    '--color-gray-900': '#111113',
    '--color-gray-950': '#0a0a0b'
  };
  function apply() {
    var r = document.documentElement.style;
    for (var k in vars) r.setProperty(k, vars[k]);
  }
  apply();
  document.addEventListener('DOMContentLoaded', apply);
  [100, 500, 1500].forEach(function(t){ setTimeout(apply, t); });

  // Hide Code Interpreter button (non-functional in GPTHub)
  function hideCI(){
    document.querySelectorAll(String.fromCharCode(98,117,116,116,111,110)).forEach(function(b){
      var t=b.textContent||b.innerText;
      if(t.indexOf(String.fromCharCode(1085,1090,1077,1088,1087,1088,1077,1090,1072,1090,1086,1088))>-1)b.style.cssText=String.fromCharCode(100,105,115,112,108,97,121,58,110,111,110,101,33,105,109,112,111,114,116,97,110,116);
    });
  }
  new MutationObserver(hideCI).observe(document.documentElement,{childList:true,subtree:true});
})();</script>
'''

# CSS tag
css_tag = '<style id=\"gpthub-theme\">\n' + css + '\n</style>\n'

# Inject JS first, then CSS, before </head>
inject = js + css_tag
html = html.replace('</head>', inject + '</head>', 1)

with open(idx_path, 'w') as f:
    f.write(html)
print('[GPTHub] Injected CSS (' + str(len(css)) + ' bytes) + JS vars')
" "$CSS_FILE" "$INDEX"
else
  echo "[GPTHub] No custom CSS or index.html found, skipping"
fi

# Register auto-search filter in background (waits for OpenWebUI to be ready)
(
  FILTER_CODE='"""
title: Auto Web Search
description: Automatically enables OpenWebUI native web search when the query needs current information
"""
from typing import Optional


class Filter:
    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        messages = body.get("messages", [])
        if not messages:
            return body
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            content = part.get("text", "")
                            break
                last_user_msg = str(content)
                break
        if len(last_user_msg.strip()) < 15:
            return body
        if body.get("features", {}).get("web_search"):
            return body
        SEARCH_KEYWORDS = [
            "найди", "поищи", "поиск", "найти",
            "актуальный", "актуально", "актуальн",
            "последние новости", "новости о ", "свежие",
            "погода", "курс валют", "курс доллара", "цена на ",
            "сколько стоит", "где купить",
            "что сейчас", "что происходит", "когда выйдет", "когда выходит",
            "рейтинг", "в интернете", "в сети",
            "search for", "find online", "latest news", "current price",
        ]
        text = last_user_msg.lower()
        if any(kw in text for kw in SEARCH_KEYWORDS):
            if "features" not in body:
                body["features"] = {}
            body["features"]["web_search"] = True
        return body
'
  for i in $(seq 1 40); do
    sleep 5
    python3 -c "
import json, urllib.request, sys, os

code = os.environ.get('FILTER_CODE', '')

# On fresh installs WEBUI_AUTH=false may not have created admin yet — try signup first
try:
    req_signup = urllib.request.Request(
        'http://localhost:8080/api/v1/auths/signup',
        data=json.dumps({'name':'Admin','email':'admin@localhost','password':'admin','profile_image_url':''}).encode(),
        headers={'Content-Type':'application/json'}
    )
    urllib.request.urlopen(req_signup, timeout=3)
except Exception:
    pass  # Already exists — that is fine

try:
    req = urllib.request.Request(
        'http://localhost:8080/api/v1/auths/signin',
        data=json.dumps({'email':'admin@localhost','password':'admin'}).encode(),
        headers={'Content-Type':'application/json'}
    )
    resp = urllib.request.urlopen(req, timeout=3)
    token = json.loads(resp.read())['token']
except Exception:
    sys.exit(1)

headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

# Check if filter exists and is correct
try:
    req2 = urllib.request.Request('http://localhost:8080/api/v1/functions/id/auto_web_search', headers=headers)
    resp2 = urllib.request.urlopen(req2, timeout=3)
    fdata = json.loads(resp2.read())
    if fdata.get('is_active') and fdata.get('is_global'):
        print('OK')
        sys.exit(0)
except:
    pass

# Create or update filter
payload = json.dumps({'id':'auto_web_search','name':'Auto Web Search','content':code,'meta':{'description':'Auto web search filter','manifest':{}},'is_active':True,'is_global':True}).encode()
try:
    req3 = urllib.request.Request('http://localhost:8080/api/v1/functions/create', data=payload, headers=headers, method='POST')
    urllib.request.urlopen(req3, timeout=5)
except:
    req3b = urllib.request.Request('http://localhost:8080/api/v1/functions/id/auto_web_search/update', data=payload, headers=headers, method='POST')
    try: urllib.request.urlopen(req3b, timeout=5)
    except: pass

# Toggle active if needed
try:
    req4 = urllib.request.Request('http://localhost:8080/api/v1/functions/id/auto_web_search', headers=headers)
    fdata2 = json.loads(urllib.request.urlopen(req4, timeout=3).read())
    if not fdata2.get('is_active'):
        req5 = urllib.request.Request('http://localhost:8080/api/v1/functions/id/auto_web_search/toggle', data=b'{}', headers=headers, method='POST')
        urllib.request.urlopen(req5, timeout=5)
except: pass

print('REGISTERED')
" FILTER_CODE="$FILTER_CODE" 2>/dev/null && echo "[GPTHub] Auto-search filter registered." && break
  done

  # Register virtual model display names (emoji + description)
  # These are stored in OpenWebUI DB — absent on fresh installs
  python3 -c "
import json, urllib.request, sys, os

MODELS = [
  ('auto',           '\u26a1 auto \u2014 \u0443\u043d\u0438\u0432\u0435\u0440\u0441\u0430\u043b\u044c\u043d\u044b\u0439',     '\u0410\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u0432\u044b\u0431\u0438\u0440\u0430\u0435\u0442 \u043b\u0443\u0447\u0448\u0443\u044e \u043c\u043e\u0434\u0435\u043b\u044c. \u041e\u043f\u0442\u0438\u043c\u0430\u043b\u044c\u043d\u043e \u0434\u043b\u044f \u0431\u043e\u043b\u044c\u0448\u0438\u043d\u0441\u0442\u0432\u0430 \u0437\u0430\u0434\u0430\u0447.'),
  ('auto-code',      '\U0001f4bb auto-code \u2014 \u043f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435', '\u041e\u043f\u0442\u0438\u043c\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u043d \u0434\u043b\u044f \u043d\u0430\u043f\u0438\u0441\u0430\u043d\u0438\u044f, \u043e\u0442\u043b\u0430\u0434\u043a\u0438 \u0438 \u0430\u043d\u0430\u043b\u0438\u0437\u0430 \u043a\u043e\u0434\u0430. \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442 Qwen3-Coder 480B.'),
  ('auto-reasoning', '\U0001f9e0 auto-reasoning \u2014 \u0433\u043b\u0443\u0431\u043e\u043a\u0438\u0439 \u0430\u043d\u0430\u043b\u0438\u0437',      '\u041f\u043e\u0448\u0430\u0433\u043e\u0432\u044b\u0435 \u0440\u0430\u0441\u0441\u0443\u0436\u0434\u0435\u043d\u0438\u044f \u0434\u043b\u044f \u0441\u043b\u043e\u0436\u043d\u044b\u0445 \u0437\u0430\u0434\u0430\u0447. \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442 DeepSeek-R1.'),
  ('auto-creative',  '\u2728 auto-creative \u2014 \u0442\u0432\u043e\u0440\u0447\u0435\u0441\u0442\u0432\u043e',                '\u0422\u0432\u043e\u0440\u0447\u0435\u0441\u043a\u043e\u0435 \u043f\u0438\u0441\u044c\u043c\u043e, \u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u044f \u0438\u0434\u0435\u0439, \u0441\u0442\u043e\u0440\u0438\u0442\u0435\u043b\u043b\u0438\u043d\u0433. \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442 Qwen3-235B.'),
  ('auto-fast',      '\U0001f680 auto-fast \u2014 \u0431\u044b\u0441\u0442\u0440\u044b\u0439',                                 '\u041c\u043e\u043b\u043d\u0438\u0435\u043d\u043e\u0441\u043d\u044b\u0435 \u043e\u0442\u0432\u0435\u0442\u044b \u0434\u043b\u044f \u043f\u0440\u043e\u0441\u0442\u044b\u0445 \u0437\u0430\u043f\u0440\u043e\u0441\u043e\u0432. \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442 GPT-OSS 20B.'),
]

try:
    req = urllib.request.Request(
        'http://localhost:8080/api/v1/auths/signup',
        data=json.dumps({'name':'Admin','email':'admin@localhost','password':'admin','profile_image_url':''}).encode(),
        headers={'Content-Type':'application/json'}
    )
    urllib.request.urlopen(req, timeout=3)
except: pass

try:
    req = urllib.request.Request(
        'http://localhost:8080/api/v1/auths/signin',
        data=json.dumps({'email':'admin@localhost','password':'admin'}).encode(),
        headers={'Content-Type':'application/json'}
    )
    token = json.loads(urllib.request.urlopen(req, timeout=3).read())['token']
except Exception as e:
    print('signin failed:', e); sys.exit(1)

headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

for mid, name, desc in MODELS:
    payload = json.dumps({'id': mid, 'name': name, 'meta': {'profile_image_url': '', 'description': desc, 'capabilities': {}}, 'params': {}, 'base_model_id': None}).encode()
    # Try update first, then create
    try:
        req_upd = urllib.request.Request(f'http://localhost:8080/api/v1/models/model/update?id={mid}', data=payload, headers=headers, method='POST')
        urllib.request.urlopen(req_upd, timeout=5)
        print('updated', mid)
    except:
        try:
            req_cre = urllib.request.Request('http://localhost:8080/api/v1/models/create', data=payload, headers=headers, method='POST')
            urllib.request.urlopen(req_cre, timeout=5)
            print('created', mid)
        except Exception as e:
            print('failed', mid, e)
" 2>/dev/null && echo "[GPTHub] Model display names configured."
) &

# Run the original OpenWebUI entrypoint
exec bash start.sh

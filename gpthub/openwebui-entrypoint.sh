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
html = re.sub(r'<meta http-equiv=\"Cache-Control\"[^>]*>\n?', '', html)

# Force no-cache so browsers always pick up updated index.html after rebuild
nocache = '<meta http-equiv=\"Cache-Control\" content=\"no-cache, no-store, must-revalidate\">\n'

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

  // ── Max 2 models: hide Add Model (+) when 2 already selected ─────
  var _addModelSel='path[d=\"M12 6v12m6-6H6\"]';
  function enforceMaxModels(){
    document.querySelectorAll(_addModelSel).forEach(function(p){
      var btn=p.closest('button');
      if(!btn) return;
      // Walk up to the container that holds all model rows (flex-col)
      var wrap=btn;
      for(var i=0;i<5&&wrap;i++){
        wrap=wrap.parentElement;
        if(wrap&&wrap.className&&wrap.className.indexOf('flex-col')>-1) break;
      }
      if(!wrap) return;
      // Count model selector rows: buttons with model names (not the + button, not minus, not default)
      var modelBtns=wrap.querySelectorAll('button');
      var count=0;
      modelBtns.forEach(function(b){
        if(b.querySelector(_addModelSel)) return;
        var t=(b.textContent||'').trim();
        // Skip utility buttons (minus, set default)
        if(t==='-'||t===''||t.length<3) return;
        // Skip non-model buttons
        if(t.indexOf('\\u0423\\u0441\\u0442\\u0430\\u043d\\u043e\\u0432\\u0438\\u0442\\u044c')>-1) return;
        if(t.indexOf('Установить')>-1) return;
        count++;
      });
      if(count>=2){
        btn.style.setProperty('display','none','important');
      } else {
        btn.style.removeProperty('display');
      }
    });
  }
  new MutationObserver(enforceMaxModels).observe(document.documentElement,{childList:true,subtree:true});
  [0,100,500,1500,3000].forEach(function(t){setTimeout(enforceMaxModels,t);});

  // Hide Code Interpreter button (non-functional in GPTHub)
  function hideCI(){
    document.querySelectorAll(String.fromCharCode(98,117,116,116,111,110)).forEach(function(b){
      var t=b.textContent||b.innerText;
      if(t.indexOf(String.fromCharCode(1085,1090,1077,1088,1087,1088,1077,1090,1072,1090,1086,1088))>-1)b.style.cssText=String.fromCharCode(100,105,115,112,108,97,121,58,110,111,110,101,33,105,109,112,111,114,116,97,110,116);
    });
  }
  new MutationObserver(hideCI).observe(document.documentElement,{childList:true,subtree:true});

  // ── Quick Login Buttons ──────────────────────────────────────────────
  var _QL = [
    {l:'Admin', e:String.fromCodePoint(0x1f6e1,0xfe0f), m:'admin@localhost', p:'admin', d:String.fromCharCode(1040,1076,1084,1080,1085,1080,1089,1090,1088,1072,1090,1086,1088)},
    {l:'User',  e:String.fromCodePoint(0x1f464),         m:'user@localhost',  p:'user',  d:String.fromCharCode(1055,1086,1083,1100,1079,1086,1074,1072,1090,1077,1083,1100)}
  ];
  function _qlInject() {
    if (document.getElementById('gpthub-ql')) return;
    if (window.location.pathname.indexOf('/auth') === -1) return;
    var pi = document.querySelector('input[type=password]');
    if (!pi) return;
    var fm = pi.closest('form');
    if (!fm) return;
    var w = document.createElement('div');
    w.id = 'gpthub-ql';
    w.style.cssText = 'margin-top:16px;padding:16px;border-radius:12px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);';
    var tt = document.createElement('div');
    tt.style.cssText = 'font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;text-align:center;';
    tt.textContent = String.fromCharCode(1041,1099,1089,1090,1088,1099,1081,32,1074,1093,1086,1076);
    w.appendChild(tt);
    var rw = document.createElement('div');
    rw.style.cssText = 'display:flex;gap:8px;';
    _QL.forEach(function(a){
      var b = document.createElement('button');
      b.type = 'button';
      b.style.cssText = 'flex:1;padding:10px 12px;border-radius:8px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06);color:#eee;cursor:pointer;font-size:14px;transition:all .2s;display:flex;flex-direction:column;align-items:center;gap:4px;';
      b.innerHTML = '<span style=\"font-size:22px\">'+a.e+'</span><span style=\"font-weight:600\">'+a.l+'</span><span style=\"font-size:11px;color:#888\">'+a.d+'</span>';
      b.onmouseenter = function(){ b.style.background='rgba(227,6,17,.15)'; b.style.borderColor='rgba(227,6,17,.4)'; };
      b.onmouseleave = function(){ b.style.background='rgba(255,255,255,.06)'; b.style.borderColor='rgba(255,255,255,.12)'; };
      b.onclick = function(ev){
        ev.preventDefault(); b.style.opacity='0.6';
        fetch('/api/v1/auths/signin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:a.m,password:a.p})})
        .then(function(r){return r.json()}).then(function(d){
          if(d.token){localStorage.setItem('token',d.token);window.location.href='/';}
          else{b.textContent='Error';setTimeout(function(){location.reload()},1500);}
        }).catch(function(){b.textContent='Error';setTimeout(function(){location.reload()},1500);});
      };
      rw.appendChild(b);
    });
    w.appendChild(rw);
    fm.parentNode.insertBefore(w, fm.nextSibling);
  }
  new MutationObserver(_qlInject).observe(document.documentElement,{childList:true,subtree:true});
  document.addEventListener('DOMContentLoaded', _qlInject);

  // ── Fetch interceptor: changelog, pagination fix, memory cleanup ─────
  var _origFetch = window.fetch;
  var _chatPageEmpty = 0; // tracks consecutive empty chat pages
  window.fetch = function(url, opts) {
    var urlStr = (typeof url === 'string') ? url : (url && url.url) || '';

    // Block changelog popup
    if (urlStr.indexOf('/api/changelog') !== -1) {
      return Promise.resolve(new Response('{}', {status:200, headers:{'Content-Type':'application/json'}}));
    }
    // Block version update check — must return current/latest fields or localeCompare crashes
    if (urlStr.indexOf('/api/version/updates') !== -1) {
      return Promise.resolve(new Response('{\\\"current\\\":\\\"0.6.5\\\",\\\"latest\\\":\\\"0.6.5\\\"}', {status:200, headers:{'Content-Type':'application/json'}}));
    }

    // Fix infinite chat pagination: if we already got empty pages, stop fetching
    var chatPageMatch = urlStr.match(/\\/api\\/v1\\/chats\\/\\?page=(\\d+)/);
    if (chatPageMatch && _chatPageEmpty >= 2) {
      return Promise.resolve(new Response('[]', {status:200, headers:{'Content-Type':'application/json'}}));
    }

    var result = _origFetch.apply(this, arguments);

    // Track empty chat pages to stop the loop
    if (chatPageMatch) {
      var pg = parseInt(chatPageMatch[1]);
      result.then(function(resp) {
        resp.clone().json().then(function(d) {
          if (Array.isArray(d) && d.length === 0) { _chatPageEmpty++; }
          else { _chatPageEmpty = 0; }
        }).catch(function(){});
      }).catch(function(){});
    }
    try {
      var method = (opts && opts.method || 'GET').toUpperCase();
      if (method === 'DELETE') {
        // Memory cleanup on chat deletion
        var m = urlStr.match(/\\/api\\/v1\\/chats\\/([0-9a-f-]{36})$/);
        if (m) {
          var chatId = m[1];
          result.then(function(resp) {
            if (resp.ok) {
              _origFetch('http://localhost:8000/api/memory/by-chat/' + chatId, {method:'DELETE'})
                .then(function(r){return r.json()})
                .then(function(d){console.log('[GPTHub] Cleaned',d.deleted||0,'memories for chat',chatId)})
                .catch(function(){});
            }
          }).catch(function(){});
        }
      }
    } catch(e) {}
    return result;
  };
})();</script>
'''

# CSS tag
css_tag = '<style id=\"gpthub-theme\">\n' + css + '\n</style>\n'

# Custom JS file (file preview + upload blacklist)
custom_js = ''
custom_js_path = '/app/custom-scripts.js'
import os
if os.path.exists(custom_js_path):
    with open(custom_js_path, 'r') as f:
        custom_js = '<script id=\"gpthub-custom\">\n' + f.read() + '\n</script>\n'

# Remove previous custom JS injection
html = re.sub(r'<script id=\"gpthub-custom\">.*?</script>\n?', '', html, flags=re.DOTALL)

# Inject nocache + JS + CSS + custom JS before </head>
inject = nocache + js + css_tag + custom_js
html = html.replace('</head>', inject + '</head>', 1)

with open(idx_path, 'w') as f:
    f.write(html)
print('[GPTHub] Injected CSS (' + str(len(css)) + ' bytes) + JS vars + custom scripts')
" "$CSS_FILE" "$INDEX"
else
  echo "[GPTHub] No custom CSS or index.html found, skipping"
fi

# Register auto-search filter in background (waits for OpenWebUI to be ready)
(
  # Write filter code to temp file to avoid shell escaping issues
  cat > /tmp/gpthub_filter.py << 'FILTEREOF'
"""
title: Auto Web Search
description: Automatically enables OpenWebUI native web search when the query needs current information. Also injects user identity for per-user memory.
"""
from typing import Optional


class Filter:
    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if __user__:
            user_email = __user__.get("email", "")
            user_id = __user__.get("id", "")
            body["user"] = user_email or user_id or "default"
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
FILTEREOF

  for i in $(seq 1 40); do
    sleep 5
    python3 -c "
import json, urllib.request, sys, os

code = open('/tmp/gpthub_filter.py', encoding='utf-8').read()

# On fresh installs — create default accounts (admin + user)
# First try signup without auth; if signup is disabled (403), use admin token to create via admin API
for _name, _email, _pwd in [('Admin', 'admin@localhost', 'admin'), ('User', 'user@localhost', 'user')]:
    try:
        _req = urllib.request.Request(
            'http://localhost:8080/api/v1/auths/signup',
            data=json.dumps({'name':_name,'email':_email,'password':_pwd,'profile_image_url':'/static/favicon.png'}).encode(),
            headers={'Content-Type':'application/json'}
        )
        urllib.request.urlopen(_req, timeout=3)
    except Exception:
        pass  # Already exists or signup disabled — will retry via admin API below

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

# Create user account via admin API (works even if signup is disabled)
try:
    _chk = urllib.request.Request('http://localhost:8080/api/v1/auths/signin',
        data=json.dumps({'email':'user@localhost','password':'user'}).encode(),
        headers={'Content-Type':'application/json'})
    urllib.request.urlopen(_chk, timeout=3)
except Exception:
    # User doesn't exist — create via admin add endpoint
    try:
        _add = urllib.request.Request('http://localhost:8080/api/v1/auths/add',
            data=json.dumps({'name':'User','email':'user@localhost','password':'user','role':'user','profile_image_url':'/static/favicon.png'}).encode(),
            headers=headers, method='POST')
        urllib.request.urlopen(_add, timeout=3)
        print('created user@localhost')
    except Exception as e:
        print('user create failed:', e)

# Fix empty avatars: set Gravatar URL for users with missing profile_image_url
try:
    import hashlib as _hl
    _users_req = urllib.request.Request('http://localhost:8080/api/v1/users/', headers=headers)
    _users = json.loads(urllib.request.urlopen(_users_req, timeout=3).read())
    for _u in _users:
        _img = _u.get('profile_image_url', '')
        if not _img or _img == '' or _img == '/user.png':
            _email = _u.get('email', '')
            _hash = _hl.md5(_email.lower().strip().encode()).hexdigest()
            _grav = f'https://www.gravatar.com/avatar/{_hash}?d=identicon&s=200'
            _upd = urllib.request.Request(
                f"http://localhost:8080/api/v1/users/{_u['id']}/update",
                data=json.dumps({'name': _u['name'], 'email': _email, 'profile_image_url': _grav}).encode(),
                headers=headers, method='POST')
            urllib.request.urlopen(_upd, timeout=3)
            print(f"set gravatar for {_email}")
except Exception as e:
    print(f'avatar fix: {e}')

# Check if filter exists with correct code
filter_exists = False
needs_update = True
try:
    req2 = urllib.request.Request('http://localhost:8080/api/v1/functions/id/auto_web_search', headers=headers)
    resp2 = urllib.request.urlopen(req2, timeout=3)
    fdata = json.loads(resp2.read())
    filter_exists = True
    # Check if code matches current version
    if fdata.get('content','').strip() == code.strip() and fdata.get('is_active') and fdata.get('is_global'):
        print('OK')
        needs_update = False
except:
    pass

if needs_update:
    # Create or update filter
    payload = json.dumps({'id':'auto_web_search','name':'Auto Web Search','content':code,'meta':{'description':'Auto web search filter','manifest':{}},'is_active':True,'is_global':True}).encode()
    if filter_exists:
        try:
            req3b = urllib.request.Request('http://localhost:8080/api/v1/functions/id/auto_web_search/update', data=payload, headers=headers, method='POST')
            urllib.request.urlopen(req3b, timeout=5)
        except: pass
    else:
        try:
            req3 = urllib.request.Request('http://localhost:8080/api/v1/functions/create', data=payload, headers=headers, method='POST')
            urllib.request.urlopen(req3, timeout=5)
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
" 2>/dev/null && echo "[GPTHub] Auto-search filter registered." && break
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
  # Tool-forcing aliases (used by frontend toolbar, not shown in main picker)
  ('auto-search',       '\U0001f50d auto-search \u2014 \u0432\u0435\u0431-\u043f\u043e\u0438\u0441\u043a',        '\u041f\u0440\u0438\u043d\u0443\u0434\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0439 \u043f\u043e\u0438\u0441\u043a \u0447\u0435\u0440\u0435\u0437 \u0442\u0443\u043b\u0431\u0430\u0440'),
  ('auto-image',        '\U0001f5bc\ufe0f auto-image \u2014 \u043a\u0430\u0440\u0442\u0438\u043d\u043a\u0430',    '\u0413\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u044f \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0439 \u0447\u0435\u0440\u0435\u0437 \u0442\u0443\u043b\u0431\u0430\u0440'),
  ('auto-presentation', '\U0001f4ca auto-presentation \u2014 \u043f\u0440\u0435\u0437\u0435\u043d\u0442\u0430\u0446\u0438\u044f', '\u0421\u043e\u0437\u0434\u0430\u043d\u0438\u0435 PPTX \u0447\u0435\u0440\u0435\u0437 \u0442\u0443\u043b\u0431\u0430\u0440'),
  ('auto-research',     '\U0001f52c auto-research \u2014 deep research',                                            '\u0413\u043b\u0443\u0431\u043e\u043a\u0438\u0439 \u043c\u043d\u043e\u0433\u043e\u0443\u0440\u043e\u0432\u043d\u0435\u0432\u044b\u0439 \u043f\u043e\u0438\u0441\u043a \u0447\u0435\u0440\u0435\u0437 \u0442\u0443\u043b\u0431\u0430\u0440'),
  # Real MWS models (must have entries so non-admin users can see them)
  ('gpt-oss-20b',                       'GPT-OSS 20B',                    '\u0411\u044b\u0441\u0442\u0440\u0430\u044f \u0443\u043d\u0438\u0432\u0435\u0440\u0441\u0430\u043b\u044c\u043d\u0430\u044f \u043c\u043e\u0434\u0435\u043b\u044c. 3858 tps.'),
  ('gpt-oss-120b',                      'GPT-OSS 120B',                   '\u041c\u043e\u0449\u043d\u0430\u044f \u043c\u043e\u0434\u0435\u043b\u044c \u0434\u043b\u044f \u0441\u043b\u043e\u0436\u043d\u044b\u0445 \u0437\u0430\u0434\u0430\u0447. 2721 tps.'),
  ('qwen3-coder-480b-a35b',             'Qwen3 Coder 480B',               '\u0421\u043f\u0435\u0446\u0438\u0430\u043b\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u043d\u0430 \u0434\u043b\u044f \u043d\u0430\u043f\u0438\u0441\u0430\u043d\u0438\u044f \u0438 \u043e\u0442\u043b\u0430\u0434\u043a\u0438 \u043a\u043e\u0434\u0430. 8315 tps.'),
  ('deepseek-r1-distill-qwen-32b',      'DeepSeek R1 32B',                'Reasoning-\u043c\u043e\u0434\u0435\u043b\u044c \u0441 \u043f\u043e\u0448\u0430\u0433\u043e\u0432\u044b\u043c \u043c\u044b\u0448\u043b\u0435\u043d\u0438\u0435\u043c.'),
  ('QwQ-32B',                           'QwQ 32B',                        '\u0410\u043b\u044c\u0442\u0435\u0440\u043d\u0430\u0442\u0438\u0432\u043d\u0430\u044f reasoning-\u043c\u043e\u0434\u0435\u043b\u044c.'),
  ('Qwen3-235B-A22B-Instruct-2507-FP8', 'Qwen3 235B',                    '\u0421\u0430\u043c\u0430\u044f \u043c\u043e\u0449\u043d\u0430\u044f \u043c\u043e\u0434\u0435\u043b\u044c. \u0414\u043b\u044f \u0441\u043b\u043e\u0436\u043d\u044b\u0445 \u0438 \u0442\u0432\u043e\u0440\u0447\u0435\u0441\u043a\u0438\u0445 \u0437\u0430\u0434\u0430\u0447.'),
  ('qwen3-32b',                         'Qwen3 32B',                      '\u0421\u0431\u0430\u043b\u0430\u043d\u0441\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u0430\u044f \u043c\u043e\u0434\u0435\u043b\u044c \u0441\u0440\u0435\u0434\u043d\u0435\u0433\u043e \u0440\u0430\u0437\u043c\u0435\u0440\u0430.'),
  ('qwen2.5-72b-instruct',              'Qwen2.5 72B',                    '\u041a\u0440\u0443\u043f\u043d\u0430\u044f \u0438\u043d\u0441\u0442\u0440\u0443\u043a\u0442\u0438\u0432\u043d\u0430\u044f \u043c\u043e\u0434\u0435\u043b\u044c.'),
  ('qwen3-vl-30b-a3b-instruct',         'Qwen3 VL 30B \U0001f441',       'Vision-\u043c\u043e\u0434\u0435\u043b\u044c: \u0430\u043d\u0430\u043b\u0438\u0437 \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0439.'),
  ('qwen2.5-vl',                        'Qwen2.5 VL \U0001f441',         'Vision-\u043c\u043e\u0434\u0435\u043b\u044c: \u043f\u043e\u043d\u0438\u043c\u0430\u043d\u0438\u0435 \u043a\u0430\u0440\u0442\u0438\u043d\u043e\u043a.'),
  ('qwen2.5-vl-72b',                    'Qwen2.5 VL 72B \U0001f441',     '\u041a\u0440\u0443\u043f\u043d\u0430\u044f vision-\u043c\u043e\u0434\u0435\u043b\u044c.'),
  ('cotype-pro-vl-32b',                 'CoType Pro VL 32B \U0001f441',   'Vision-\u043c\u043e\u0434\u0435\u043b\u044c \u0434\u043b\u044f \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u043e\u0432 \u0438 \u0441\u0445\u0435\u043c.'),
  ('llama-3.3-70b-instruct',            'Llama 3.3 70B',                  'Meta Llama. \u0425\u043e\u0440\u043e\u0448\u0430 \u0434\u043b\u044f \u0430\u043d\u0433\u043b\u0438\u0439\u0441\u043a\u043e\u0433\u043e.'),
  ('llama-3.1-8b-instruct',             'Llama 3.1 8B',                   '\u0411\u044b\u0441\u0442\u0440\u0430\u044f \u043b\u0451\u0433\u043a\u0430\u044f \u043c\u043e\u0434\u0435\u043b\u044c Meta.'),
  ('kimi-k2-instruct',                  'Kimi K2',                        'Moonshot AI. \u0414\u043b\u0438\u043d\u043d\u044b\u0439 \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442.'),
  ('glm-4.6-357b',                      'GLM 4.6 357B',                   '\u041a\u0440\u0443\u043f\u043d\u0435\u0439\u0448\u0430\u044f GLM-\u043c\u043e\u0434\u0435\u043b\u044c.'),
  ('gemma-3-27b-it',                    'Gemma 3 27B',                    'Google Gemma. \u041a\u043e\u043c\u043f\u0430\u043a\u0442\u043d\u0430\u044f \u0438 \u0431\u044b\u0441\u0442\u0440\u0430\u044f.'),
  ('mws-gpt-alpha',                     'MWS GPT Alpha',                  '\u042d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442\u0430\u043b\u044c\u043d\u0430\u044f \u043c\u043e\u0434\u0435\u043b\u044c MWS.'),
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

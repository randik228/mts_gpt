import urllib.request, json, time

BASE = 'http://localhost:8000'

def post_chat(payload, timeout=90):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f'{BASE}/v1/chat/completions',
        data=body, headers={'Content-Type': 'application/json'}, method='POST')
    resp = urllib.request.urlopen(req, timeout=timeout)
    h = {k.lower(): v for k, v in resp.headers.items()}
    return h, json.loads(resp.read())

SEP = '=' * 60

# TEST 1: Code routing
print(SEP)
print('TEST 1: Smart Router — code -> qwen3-coder')
print(SEP)
h, d = post_chat({'model':'auto','stream':False,'user':'e2e-test',
    'messages':[{'role':'user','content':'Напиши на Python функцию проверки простого числа'}]})
reply1 = d['choices'][0]['message']['content']
print(f'  requested      : auto')
print(f'  routed-to      : {h.get("x-gpthub-model")}')
print(f'  routing-method : {h.get("x-gpthub-routing-method")}')
print(f'  routing-reason : {h.get("x-gpthub-routing-reason")}')
print(f'  reply snippet  : {reply1[:150].strip()}')
print()

# TEST 2: Reasoning routing + Reasoning Parser
print(SEP)
print('TEST 2: Smart Router — reasoning -> deepseek-r1-32b + <think> parser')
print(SEP)
h, d = post_chat({'model':'auto','stream':False,'user':'e2e-test',
    'messages':[{'role':'user','content':'Докажи почему сортировка слиянием имеет сложность O(n log n)'}]})
reply2 = d['choices'][0]['message']['content']
print(f'  routed-to      : {h.get("x-gpthub-model")}')
print(f'  routing-method : {h.get("x-gpthub-routing-method")}')
print(f'  routing-reason : {h.get("x-gpthub-routing-reason")}')
print(f'  has <details>  : {"<details>" in reply2}  <- parser transformed <think>')
print(f'  raw <think>    : {"<think>" in reply2}  <- should be False')
idx = reply2.find('<details>')
if idx >= 0:
    print(f'  details block  : {reply2[idx:idx+130]}')
print(f'  reply snippet  : {reply2[:200].strip()}')
print()

# TEST 3: Memory inject
print(SEP)
print('TEST 3: Memory inject — recall previous context')
print(SEP)
time.sleep(5)
h, d = post_chat({'model':'auto','stream':False,'user':'e2e-test',
    'messages':[{'role':'user','content':'Что ты помнишь из нашего разговора?'}]})
reply3 = d['choices'][0]['message']['content']
print(f'  routed-to      : {h.get("x-gpthub-model")}')
print(f'  reply (300)    : {reply3[:300].strip()}')
print()

# TEST 4: Memory API list
print(SEP)
print('TEST 4: Memory API — list saved facts')
print(SEP)
time.sleep(5)
req = urllib.request.Request(f'{BASE}/api/memory?user_id=e2e-test')
resp = urllib.request.urlopen(req, timeout=15)
memories = json.loads(resp.read())
print(f'  total saved    : {len(memories)}')
for i, m in enumerate(memories, 1):
    print(f'  [{i}] {m["content"][:90]}')
print()

# TEST 5: Memory semantic search
print(SEP)
print('TEST 5: Memory search — query: Python код функция')
print(SEP)
req = urllib.request.Request(f'{BASE}/api/memory/search?user_id=e2e-test&query=Python+%D0%BA%D0%BE%D0%B4')
resp = urllib.request.urlopen(req, timeout=20)
results = json.loads(resp.read())['results']
print(f'  results        : {len(results)}')
for i, r in enumerate(results, 1):
    print(f'  [{i}] {r[:90]}')

#!/bin/bash
# GPTHub: inject custom CSS + JS vars into OpenWebUI index.html on every container start
# CSS injection is optional — failures here must never prevent OpenWebUI from starting
set +e

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

# Run the original OpenWebUI entrypoint
exec bash start.sh

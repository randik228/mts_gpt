/**
 * GPTHub — Custom file handling for OpenWebUI
 * 1. Inline preview for images, audio, video (instead of downloading)
 * 2. File upload format blacklist
 */
(function () {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════════
  //  1. FILE PREVIEW MODAL — images, audio, video shown inline
  // ═══════════════════════════════════════════════════════════════════════

  var MODAL_ID = 'gpthub-file-preview';

  function getToken() {
    return localStorage.getItem('token') || '';
  }

  function removeModal() {
    var m = document.getElementById(MODAL_ID);
    if (m) m.remove();
  }

  function showModal(inner) {
    removeModal();
    var overlay = document.createElement('div');
    overlay.id = MODAL_ID;
    overlay.style.cssText =
      'position:fixed;top:0;left:0;right:0;bottom:0;z-index:99999;' +
      'background:rgba(0,0,0,.85);display:flex;align-items:center;' +
      'justify-content:center;flex-direction:column;gap:12px;';
    overlay.onclick = function (e) {
      if (e.target === overlay) removeModal();
    };

    // Close button
    var close = document.createElement('button');
    close.textContent = '\u2715';
    close.style.cssText =
      'position:absolute;top:16px;right:24px;color:#fff;font-size:28px;' +
      'background:none;border:none;cursor:pointer;z-index:100000;' +
      'line-height:1;padding:8px;opacity:.8;';
    close.onmouseenter = function () { close.style.opacity = '1'; };
    close.onmouseleave = function () { close.style.opacity = '.8'; };
    close.onclick = removeModal;

    overlay.appendChild(close);
    overlay.appendChild(inner);
    document.body.appendChild(overlay);

    // Esc to close
    var escHandler = function (e) {
      if (e.key === 'Escape') {
        removeModal();
        document.removeEventListener('keydown', escHandler);
      }
    };
    document.addEventListener('keydown', escHandler);
  }

  function showImage(url, name) {
    var wrapper = document.createElement('div');
    wrapper.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:12px;max-width:92vw;max-height:88vh;';

    var img = document.createElement('img');
    img.src = url;
    img.alt = name || 'Preview';
    img.style.cssText = 'max-width:90vw;max-height:80vh;border-radius:8px;object-fit:contain;';

    var label = document.createElement('div');
    label.textContent = name || '';
    label.style.cssText = 'color:#ccc;font-size:13px;max-width:90vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';

    wrapper.appendChild(img);
    if (name) wrapper.appendChild(label);
    showModal(wrapper);
  }

  function showAudio(url, name) {
    var wrapper = document.createElement('div');
    wrapper.style.cssText =
      'display:flex;flex-direction:column;align-items:center;gap:16px;' +
      'background:rgba(255,255,255,.08);border-radius:16px;padding:32px 40px;';

    var icon = document.createElement('div');
    icon.innerHTML = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.5"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>';
    icon.style.cssText = 'opacity:.7;margin-bottom:4px;';

    var label = document.createElement('div');
    label.textContent = name || 'Audio';
    label.style.cssText = 'color:#eee;font-size:14px;font-weight:500;max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';

    var audio = document.createElement('audio');
    audio.controls = true;
    audio.preload = 'metadata';
    audio.src = url;
    audio.style.cssText = 'min-width:360px;max-width:90vw;outline:none;';

    wrapper.appendChild(icon);
    wrapper.appendChild(label);
    wrapper.appendChild(audio);
    showModal(wrapper);
  }

  function showVideo(url, name) {
    var wrapper = document.createElement('div');
    wrapper.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:12px;';

    var video = document.createElement('video');
    video.controls = true;
    video.preload = 'metadata';
    video.src = url;
    video.style.cssText = 'max-width:90vw;max-height:80vh;border-radius:8px;';

    var label = document.createElement('div');
    label.textContent = name || '';
    label.style.cssText = 'color:#ccc;font-size:13px;';

    wrapper.appendChild(video);
    if (name) wrapper.appendChild(label);
    showModal(wrapper);
  }

  // Content-type detection by extension (quick, no network request needed)
  var IMAGE_EXT = /\.(png|jpe?g|gif|webp|svg|bmp|ico|tiff?)$/i;
  var AUDIO_EXT = /\.(mp3|wav|ogg|m4a|aac|flac|wma|opus|aiff?)$/i;
  var VIDEO_EXT = /(?!)/; // Video upload blocked — no preview needed

  function getExtFromName(name) {
    if (!name) return '';
    var m = name.match(/\.[a-zA-Z0-9]+$/);
    return m ? m[0].toLowerCase() : '';
  }

  // Override window.open to intercept file content URLs
  var _origWindowOpen = window.open;
  window.open = function (url) {
    if (typeof url === 'string' && url.indexOf('/api/v1/files/') > -1 && url.indexOf('/content') > -1) {
      // Try to detect type from URL path (which sometimes includes filename)
      var ext = getExtFromName(url);
      if (IMAGE_EXT.test(ext)) { showImage(url); return null; }
      if (AUDIO_EXT.test(ext)) { showAudio(url); return null; }
      if (VIDEO_EXT.test(ext)) { showVideo(url); return null; }

      // If no extension in URL, do a HEAD request to check content-type
      var token = getToken();
      var headers = {};
      if (token) headers['Authorization'] = 'Bearer ' + token;

      fetch(url, { method: 'HEAD', headers: headers })
        .then(function (resp) {
          var ct = (resp.headers.get('content-type') || '').toLowerCase();
          var disp = resp.headers.get('content-disposition') || '';
          var fname = '';
          var fnMatch = disp.match(/filename[*]?=(?:UTF-8''|"?)([^";]+)/i);
          if (fnMatch) fname = decodeURIComponent(fnMatch[1]);

          if (ct.indexOf('image/') === 0) {
            showImage(url, fname);
          } else if (ct.indexOf('audio/') === 0) {
            showAudio(url, fname);
          } else if (ct.indexOf('video/') === 0) {
            showVideo(url, fname);
          } else {
            // Not a previewable type — open in new tab as usual
            _origWindowOpen.apply(window, [url, '_blank']);
          }
        })
        .catch(function () {
          _origWindowOpen.apply(window, [url, '_blank']);
        });
      return null;
    }
    return _origWindowOpen.apply(window, arguments);
  };

  // Also intercept <a> clicks on file items (some versions use <a href> instead of window.open)
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[href*="/api/v1/files/"][href*="/content"]');
    if (!a) return;
    var href = a.getAttribute('href') || '';
    if (!href) return;

    var ext = getExtFromName(href);
    var isMedia = IMAGE_EXT.test(ext) || AUDIO_EXT.test(ext) || VIDEO_EXT.test(ext);

    if (isMedia) {
      e.preventDefault();
      e.stopPropagation();
      if (IMAGE_EXT.test(ext)) showImage(href, a.textContent.trim());
      else if (AUDIO_EXT.test(ext)) showAudio(href, a.textContent.trim());
      else if (VIDEO_EXT.test(ext)) showVideo(href, a.textContent.trim());
    }
  }, true);

  // ═══════════════════════════════════════════════════════════════════════
  //  2. FILE UPLOAD FORMAT BLACKLIST
  // ═══════════════════════════════════════════════════════════════════════

  var BLOCKED_EXTENSIONS = [
    // Executables & installers
    '.exe', '.bat', '.cmd', '.msi', '.com', '.scr', '.pif', '.cpl',
    // System files
    '.dll', '.sys', '.drv', '.inf', '.reg',
    // Windows scripts
    '.ps1', '.vbs', '.wsf', '.hta', '.ws',
    // Video (models don't support video input)
    '.mp4', '.webm', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.m4v', '.3gp',
    '.mpeg', '.mpg', '.ts', '.vob', '.ogv',
    // Disk images & binaries
    '.bin', '.iso', '.img', '.dmg', '.vhd', '.vmdk',
    // Databases
    '.db', '.sqlite', '.mdb', '.accdb',
    // Fonts
    '.ttf', '.otf', '.woff', '.woff2', '.eot',
    // Compiled code
    '.o', '.obj', '.class', '.pyc', '.pyo', '.so', '.dylib', '.a', '.lib',
    // Temp / backup
    '.tmp', '.bak', '.swp', '.swo', '.lock',
    // Torrent
    '.torrent',
    // Shortcuts
    '.lnk', '.url', '.webloc',
  ];

  var BLOCKED_SET = {};
  BLOCKED_EXTENSIONS.forEach(function (ext) { BLOCKED_SET[ext] = true; });

  // Localized error message
  function blockedMsg(fname, ext) {
    return '\u26d4 \u0424\u043e\u0440\u043c\u0430\u0442 ' + ext +
      ' \u043d\u0435 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442\u0441\u044f.\n\u0424\u0430\u0439\u043b \u00ab' +
      fname + '\u00bb \u043d\u0435 \u043c\u043e\u0436\u0435\u0442 \u0431\u044b\u0442\u044c \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d.';
    // ⛔ Формат .ext не поддерживается. Файл «name» не может быть загружен.
  }

  // Intercept the file upload fetch call
  // Chain on top of whatever fetch is current (may already be patched by memory cleanup)
  var _prevFetch = window.fetch;
  window.fetch = function (url, opts) {
    try {
      var urlStr = (typeof url === 'string') ? url : ((url && url.url) || '');
      var method = ((opts && opts.method) || 'GET').toUpperCase();

      if (method === 'POST' && urlStr.indexOf('/api/v1/files/') > -1) {
        var body = opts && opts.body;
        if (body instanceof FormData) {
          var file = body.get('file');
          if (file && file.name) {
            var ext = getExtFromName(file.name);
            if (ext && BLOCKED_SET[ext]) {
              alert(blockedMsg(file.name, ext));
              return Promise.reject(new Error('Blocked file format: ' + ext));
            }
          }
        }
      }
    } catch (ex) {
      // Don't break fetch on errors
    }
    return _prevFetch.apply(this, arguments);
  };

  // Also intercept file input elements to filter before upload begins
  function patchFileInputs() {
    document.querySelectorAll('input[type=file]:not([data-gpthub-patched])').forEach(function (input) {
      input.setAttribute('data-gpthub-patched', '1');
      input.addEventListener('change', function (e) {
        if (!input.files || !input.files.length) return;
        var blocked = [];
        var allowed = new DataTransfer();

        for (var i = 0; i < input.files.length; i++) {
          var f = input.files[i];
          var ext = getExtFromName(f.name);
          if (ext && BLOCKED_SET[ext]) {
            blocked.push(f.name + ' (' + ext + ')');
          } else {
            allowed.items.add(f);
          }
        }

        if (blocked.length > 0) {
          e.stopImmediatePropagation();
          alert(
            '\u26d4 \u041d\u0435\u043f\u043e\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u043c\u044b\u0435 \u0444\u043e\u0440\u043c\u0430\u0442\u044b:\n' +
            // ⛔ Неподдерживаемые форматы:
            blocked.join('\n') +
            '\n\n\u042d\u0442\u0438 \u0444\u0430\u0439\u043b\u044b \u0431\u044b\u043b\u0438 \u0438\u0441\u043a\u043b\u044e\u0447\u0435\u043d\u044b.'
            // Эти файлы были исключены.
          );
          // Replace files with only allowed ones
          if (allowed.files.length > 0) {
            input.files = allowed.files;
          } else {
            // All files blocked — cancel
            e.preventDefault();
            input.value = '';
          }
        }
      }, true);
    });
  }

  new MutationObserver(patchFileInputs).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
  patchFileInputs();

  console.log('[GPTHub] File preview & upload filter loaded');

  // ═══════════════════════════════════════════════════════════════════════
  //  3. CODE BLOCKS — disable run/edit, save as file download
  // ═══════════════════════════════════════════════════════════════════════

  var LANG_EXT = {
    python: '.py', py: '.py', javascript: '.js', js: '.js', typescript: '.ts', ts: '.ts',
    html: '.html', css: '.css', scss: '.scss', less: '.less',
    java: '.java', kotlin: '.kt', swift: '.swift', go: '.go', rust: '.rs',
    c: '.c', cpp: '.cpp', 'c++': '.cpp', csharp: '.cs', 'c#': '.cs',
    ruby: '.rb', php: '.php', perl: '.pl', lua: '.lua', r: '.r',
    bash: '.sh', sh: '.sh', zsh: '.sh', shell: '.sh', powershell: '.ps1',
    sql: '.sql', json: '.json', xml: '.xml', yaml: '.yaml', yml: '.yaml',
    toml: '.toml', ini: '.ini', csv: '.csv',
    markdown: '.md', md: '.md', tex: '.tex', latex: '.tex',
    dockerfile: '.dockerfile', docker: '.dockerfile',
    makefile: '.makefile', cmake: '.cmake',
    vue: '.vue', svelte: '.svelte', jsx: '.jsx', tsx: '.tsx'
  };

  function _codeBlockPatch() {
    // Hide run buttons
    document.querySelectorAll('.run-code-button').forEach(function(btn) {
      btn.style.setProperty('display', 'none', 'important');
    });

    // Disable code editing: remove contenteditable from code/pre
    document.querySelectorAll('pre[contenteditable], pre code[contenteditable]').forEach(function(el) {
      el.removeAttribute('contenteditable');
    });
    // CodeMirror: block all input via beforeinput + keydown interception
    document.querySelectorAll('.cm-editor:not([data-gpthub-readonly])').forEach(function(editor) {
      editor.setAttribute('data-gpthub-readonly', '1');
      // Block all text input
      editor.addEventListener('beforeinput', function(e) { e.preventDefault(); }, true);
      // Block key presses that modify content (allow arrows, copy shortcuts, etc.)
      editor.addEventListener('keydown', function(e) {
        var allow = e.key === 'Tab' || e.key === 'Escape' ||
          e.key.indexOf('Arrow') === 0 || e.key === 'Home' || e.key === 'End' ||
          e.key === 'PageUp' || e.key === 'PageDown' ||
          ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'a'));
        if (!allow) e.preventDefault();
      }, true);
      // Block paste and drop
      editor.addEventListener('paste', function(e) { e.preventDefault(); }, true);
      editor.addEventListener('drop', function(e) { e.preventDefault(); }, true);
    });
  }

  // Event delegation for save buttons — survives Svelte re-renders
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('.save-code-button');
    if (!btn) return;

    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    // Find the code block container
    var container = btn.closest('.relative.my-2, .relative.flex-col');
    if (!container) container = btn.closest('div[class*="rounded-lg"]');
    if (!container) return;

    // Find code content: prefer CodeMirror EditorView state (full doc), then DOM
    var cmContent = container.querySelector('.cm-content');
    var codeEl = container.querySelector('pre code');
    var code = '';

    if (cmContent && cmContent.cmView && cmContent.cmView.view) {
      // CodeMirror 6: get full document from EditorView state (not truncated by viewport)
      try { code = cmContent.cmView.view.state.doc.toString(); } catch(ex) {}
    }
    if (!code && cmContent) {
      // Fallback: get lines from .cm-content DOM (avoids gutter line numbers)
      var lines = cmContent.querySelectorAll('.cm-line');
      if (lines.length > 0) {
        var parts = [];
        lines.forEach(function(l) { parts.push(l.textContent); });
        code = parts.join('\n');
      } else {
        code = cmContent.textContent || '';
      }
    }
    if (!code && codeEl) {
      code = codeEl.textContent || '';
    }
    if (!code) {
      // Fallback: div[class*="language-"] textContent minus line numbers
      var langDiv2 = container.querySelector('div[class*="language-"]');
      if (langDiv2) {
        code = langDiv2.textContent || '';
        code = code.replace(/^\d+\n/gm, '');
      }
    }
    if (!code.trim()) return;

    // Detect language from CSS classes
    var lang = '';
    var langDiv = container.querySelector('div[class*="language-"]');
    if (codeEl) {
      (codeEl.className || '').split(/\s+/).forEach(function(c) {
        var m = c.match(/^(?:language-|hljs-)(.+)$/);
        if (m) lang = m[1].toLowerCase();
      });
    }
    if (!lang && langDiv) {
      (langDiv.className || '').split(/\s+/).forEach(function(c) {
        var m = c.match(/^language-(.+)$/);
        if (m) lang = m[1].toLowerCase();
      });
    }
    // Fallback: read language label in toolbar
    if (!lang) {
      var langLabel = container.querySelector('.text-xs.font-medium');
      if (langLabel) lang = (langLabel.textContent || '').trim().toLowerCase();
    }

    var ext = LANG_EXT[lang] || '.txt';
    var filename = 'code' + ext;

    // Download
    var blob = new Blob([code], { type: 'text/plain;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, true);

  new MutationObserver(_codeBlockPatch).observe(document.documentElement, { childList: true, subtree: true });
  console.log('[GPTHub] Code block patches loaded');

  // ═══════════════════════════════════════════════════════════════════════
  //  4. PROMPT SUGGESTIONS — pills above input (TipTap ProseMirror)
  // ═══════════════════════════════════════════════════════════════════════

  var SG_API = 'http://localhost:8000/api/suggestions/';
  var SG_DEBOUNCE = 500;
  var SG_MAX_WORDS = 10;
  var _sg = { timer: null, abort: null, box: null, arrow: null, wrap: null, last: '', collapsed: false, patched: false, el: null };

  function _sgUserId() {
    try { return (JSON.parse(localStorage.getItem('user') || '{}')).email || 'default'; }
    catch (e) { return 'default'; }
  }

  function _sgGetText() {
    var editor = document.querySelector('#chat-input.tiptap, #chat-input.ProseMirror, #chat-input[contenteditable]');
    if (editor) return (editor.textContent || '').trim();
    var ta = document.querySelector('#chat-input');
    if (ta) return (ta.value || ta.textContent || '').trim();
    return '';
  }

  function _sgSetText(text) {
    var editor = document.querySelector('#chat-input.tiptap, #chat-input.ProseMirror, #chat-input[contenteditable]');
    if (editor) {
      // Clear and set content for TipTap
      editor.innerHTML = '<p>' + text + '</p>';
      editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText' }));
      // Place cursor at end
      var sel = window.getSelection();
      var range = document.createRange();
      range.selectNodeContents(editor);
      range.collapse(false);
      sel.removeAllRanges();
      sel.addRange(range);
      editor.focus();
      return;
    }
    // Fallback: textarea
    var ta = document.querySelector('#chat-input');
    if (ta && ta.tagName === 'TEXTAREA') {
      var setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(ta, text);
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      ta.focus();
    }
  }

  // ── Build UI ─────────────────────────────────────────────────────────
  function _sgBuild() {
    if (_sg.wrap && _sg.wrap.parentNode) return _sg.box;

    // Find the input container — walk up from #chat-input to the form-level wrapper
    var chatInput = document.getElementById('chat-input');
    if (!chatInput) return null;
    var formEl = chatInput.closest('form');
    if (!formEl) return null;

    // Wrap = container for pills + arrow, inserted right before the form
    var wrap = document.createElement('div');
    wrap.id = 'gpthub-sg-wrap';
    wrap.style.cssText =
      'width:100%;max-width:48rem;margin:0 auto;padding:0 16px;box-sizing:border-box;z-index:60;';

    // Pills row
    var box = document.createElement('div');
    box.id = 'gpthub-suggestions';
    box.style.cssText =
      'display:flex;flex-wrap:wrap;gap:8px;padding:4px 0 2px;' +
      'justify-content:center;transition:opacity .25s;opacity:0;';
    wrap.appendChild(box);

    // Collapse/expand arrow (centered)
    var arrow = document.createElement('button');
    arrow.type = 'button';
    arrow.id = 'gpthub-sg-arrow';
    arrow.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"/></svg>';
    arrow.title = '\u0421\u043a\u0440\u044b\u0442\u044c';
    arrow.style.cssText =
      'display:none;margin:4px auto 0;padding:4px 40px;border:none;' +
      'background:transparent;color:rgba(255,255,255,.3);' +
      'cursor:pointer;transition:color .15s,transform .25s;line-height:0;';
    arrow.onmouseenter = function () { arrow.style.color = 'rgba(255,255,255,.65)'; };
    arrow.onmouseleave = function () { arrow.style.color = 'rgba(255,255,255,.3)'; };
    arrow.onclick = function (e) {
      e.preventDefault(); e.stopPropagation();
      _sg.collapsed = !_sg.collapsed;
      arrow.style.transform = _sg.collapsed ? 'rotate(180deg)' : '';
      box.style.display = _sg.collapsed ? 'none' : 'flex';
      // Re-fetch suggestions when expanding
      if (!_sg.collapsed) { _sg.last = ''; _sgSchedule(); }
    };
    wrap.appendChild(arrow);

    // Insert before the form (above the input area)
    formEl.parentNode.insertBefore(wrap, formEl);

    _sg.wrap = wrap;
    _sg.box = box;
    _sg.arrow = arrow;
    return box;
  }

  // ── Render pills ─────────────────────────────────────────────────────
  function _sgShow(suggestions) {
    var box = _sgBuild();
    if (!box) return;
    box.innerHTML = '';
    if (!suggestions || !suggestions.length) { _sgHide(); return; }

    suggestions.forEach(function (text) {
      var pill = document.createElement('button');
      pill.type = 'button';
      pill.textContent = text;
      pill.style.cssText =
        'padding:7px 16px;border-radius:20px;' +
        'background:rgba(255,255,255,.06);' +
        'border:1px solid rgba(255,255,255,.10);' +
        'color:#c8c8c8;font-size:13px;line-height:1.4;' +
        'cursor:pointer;transition:all .15s;' +
        'max-width:92%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      pill.onmouseenter = function () {
        pill.style.background = 'rgba(227,6,17,.18)';
        pill.style.borderColor = 'rgba(227,6,17,.45)';
        pill.style.color = '#fff';
        pill.style.whiteSpace = 'normal';
        pill.style.overflow = 'visible';
        pill.style.textOverflow = 'unset';
      };
      pill.onmouseleave = function () {
        pill.style.background = 'rgba(255,255,255,.06)';
        pill.style.borderColor = 'rgba(255,255,255,.10)';
        pill.style.color = '#c8c8c8';
        pill.style.whiteSpace = 'nowrap';
        pill.style.overflow = 'hidden';
        pill.style.textOverflow = 'ellipsis';
      };
      pill.onclick = function (e) {
        e.preventDefault(); e.stopPropagation();
        _sgSetText(text);
        _sgHide();
      };
      box.appendChild(pill);
    });

    if (!_sg.collapsed) box.style.display = 'flex';
    box.style.opacity = '1';
    if (_sg.arrow) _sg.arrow.style.display = 'block';
  }

  function _sgHide() {
    if (_sg.box) { _sg.box.style.opacity = '0'; setTimeout(function () { if (_sg.box) _sg.box.innerHTML = ''; }, 250); }
    if (_sg.arrow) _sg.arrow.style.display = 'none';
  }

  // ── Fetch suggestions ────────────────────────────────────────────────
  function _sgFetch() {
    var text = _sgGetText();
    if (!text) { _sgHide(); _sg.last = ''; return; }
    var wc = text.split(/\s+/).length;
    if (wc >= SG_MAX_WORDS) { _sgHide(); return; }
    if (text === _sg.last) return;
    _sg.last = text;

    if (_sg.abort) { try { _sg.abort.abort(); } catch (e) {} }
    _sg.abort = new AbortController();

    fetch(SG_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text, user_id: _sgUserId(), messages: [] }),
      signal: _sg.abort.signal,
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.suggestions && d.suggestions.length) _sgShow(d.suggestions);
        else _sgHide();
      })
      .catch(function (err) {
        if (err.name !== 'AbortError') _sgHide();
      });
  }

  function _sgSchedule() {
    clearTimeout(_sg.timer);
    _sg.timer = setTimeout(_sgFetch, SG_DEBOUNCE);
  }

  // ── Attach to the TipTap editor ──────────────────────────────────────
  function _sgPatch() {
    var chatInput = document.getElementById('chat-input');
    if (!chatInput) return;
    // Already patched on this exact element — skip
    if (_sg.patched && _sg.el === chatInput) return;

    // New element or re-patch needed — reset state
    _sg.patched = false;
    _sg.el = chatInput;
    if (_sg.wrap && _sg.wrap.parentNode) _sg.wrap.parentNode.removeChild(_sg.wrap);
    _sg.box = null; _sg.arrow = null; _sg.wrap = null; _sg.last = '';

    // Listen for input on the #chat-input container (TipTap fires input events on it)
    chatInput.addEventListener('input', function () {
      var text = _sgGetText();
      var wc = text ? text.split(/\s+/).length : 0;
      if (wc >= SG_MAX_WORDS) { _sgHide(); return; }
      _sgSchedule();
    });

    chatInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { _sgHide(); _sg.last = ''; }
      if (e.key === 'Escape') _sgHide();
    });

    chatInput.addEventListener('focus', function () {
      var wc = (_sgGetText().split(/\s+/).filter(Boolean)).length;
      if (wc < SG_MAX_WORDS) _sgSchedule();
    }, true);

    _sg.patched = true;
    console.log('[GPTHub] Suggestions attached to #chat-input (TipTap)');

    // Initial fetch
    setTimeout(_sgFetch, 1000);
  }

  // Watch for #chat-input — re-patch when element changes
  new MutationObserver(function () {
    var el = document.getElementById('chat-input');
    if (el && (!_sg.patched || _sg.el !== el)) _sgPatch();
    if (!el && _sg.patched) { _sg.patched = false; _sg.el = null; _sg.box = null; _sg.arrow = null; _sg.wrap = null; }
  }).observe(document.documentElement, { childList: true, subtree: true });
  setTimeout(_sgPatch, 800);

  console.log('[GPTHub] Prompt suggestions loaded');
})();

// ═══════════════════════════════════════════════════════════════════════
//  5. OBSERVABILITY BADGE — show model/routing info under AI responses
// ═══════════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  // Queue of routing info captured from response headers
  var _routingQueue = [];

  // Intercept window.fetch to capture X-GPTHub-* headers
  var _origFetch = window.fetch;
  window.fetch = async function (url, opts) {
    var res = await _origFetch.apply(this, arguments);
    try {
      var urlStr = (typeof url === 'string') ? url : (url.url || '');
      if (urlStr.includes('/chat/completions') || urlStr.includes('/api/chat')) {
        var model    = res.headers.get('X-GPTHub-Model') || '';
        var method   = res.headers.get('X-GPTHub-Routing-Method') || '';
        var reason   = res.headers.get('X-GPTHub-Routing-Reason') || '';
        var memCount = res.headers.get('X-GPTHub-Memory-Count') || '';
        if (model) {
          _routingQueue.push({ model: model, method: method, reason: reason, memCount: memCount, ts: Date.now() });
        }
      }
    } catch (e) {}
    return res;
  };

  // Shorten model name for display
  function _shortModel(m) {
    if (!m) return '';
    var map = {
      'qwen3-coder-480b-a35b': 'Qwen3-Coder 480B',
      'Qwen3-235B-A22B-Instruct-2507-FP8': 'Qwen3 235B',
      'gpt-oss-120b': 'GPT-OSS 120B',
      'gpt-oss-20b': 'GPT-OSS 20B',
      'deepseek-r1-distill-qwen-32b': 'DeepSeek-R1 32B',
      'qwen3-vl-30b-a3b-instruct': 'Qwen3-VL 30B',
      'qwen-image-lightning': 'Qwen-Image ⚡',
      'qwen-image': 'Qwen-Image',
      'qwen3-32b': 'Qwen3 32B',
    };
    return map[m] || m;
  }

  function _methodIcon(method) {
    if (!method) return '';
    if (method.includes('keyword')) return '🔑';
    if (method.includes('llm')) return '🤖';
    if (method.includes('embed')) return '📐';
    if (method.includes('virtual')) return '🎯';
    if (method.includes('context')) return '🔄';
    if (method.includes('passthrough')) return '➡️';
    return '⚡';
  }

  // Attach badge to an assistant message element
  function _attachBadge(msgEl, info) {
    if (msgEl.querySelector('.gpthub-obs-badge')) return; // already has badge
    var badge = document.createElement('div');
    badge.className = 'gpthub-obs-badge';
    var icon = _methodIcon(info.method);
    var modelLabel = _shortModel(info.model);
    var memPart = (info.memCount && info.memCount !== '0')
      ? ' · 💾 ' + info.memCount + ' из памяти'
      : '';
    badge.innerHTML =
      '<span class="gpthub-obs-icon">' + icon + '</span>' +
      '<span class="gpthub-obs-model">' + modelLabel + '</span>' +
      (info.reason ? '<span class="gpthub-obs-reason" title="' + info.reason + '">' + info.method + '</span>' : '') +
      (memPart ? '<span class="gpthub-obs-mem">' + memPart + '</span>' : '');
    // Insert after message content, before action buttons
    var actionBar = msgEl.querySelector('.flex.items-center.gap-1');
    if (actionBar && actionBar.parentNode === msgEl) {
      msgEl.insertBefore(badge, actionBar);
    } else {
      msgEl.appendChild(badge);
    }
  }

  // MutationObserver: watch for new assistant messages
  var _pendingBadge = null; // store info until message appears

  // When routing info arrives, store it
  function _onRoutingInfo(info) {
    _pendingBadge = info;
    // Try immediately if element already there
    setTimeout(_tryAttachPending, 300);
    setTimeout(_tryAttachPending, 1500);
    setTimeout(_tryAttachPending, 3000);
  }

  function _tryAttachPending() {
    if (!_pendingBadge) return;
    // Find the last assistant message that doesn't have a badge yet
    var msgs = document.querySelectorAll('[data-role="assistant"], .assistant-message, [class*="assistant"]');
    // Fallback: look for messages in chat area
    if (!msgs.length) {
      // OpenWebUI renders messages differently — find by structure
      msgs = document.querySelectorAll('.chat-messages [class*="group"]');
    }
    var last = null;
    msgs.forEach(function(el) {
      if (!el.querySelector('.gpthub-obs-badge')) last = el;
    });
    if (last) {
      _attachBadge(last, _pendingBadge);
      _pendingBadge = null;
    }
  }

  // Poll routing queue
  setInterval(function () {
    while (_routingQueue.length > 0) {
      _onRoutingInfo(_routingQueue.shift());
    }
  }, 200);

  // Also watch DOM mutations to attach pending badge when message appears
  new MutationObserver(function (mutations) {
    if (_pendingBadge) _tryAttachPending();
  }).observe(document.documentElement, { childList: true, subtree: true });

  console.log('[GPTHub] Observability badge loaded');
})();

// ═══════════════════════════════════════════════════════════════════════
//  6. TOOL BUTTONS — injected into native toolbar row (next to Веб-поиск)
// ═══════════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  var _activeTool = null; // null = auto routing

  var TOOLS = [
    { id: 'search',       model: 'auto-search',       title: 'Принудительный веб-поиск' },
    { id: 'image',        model: 'auto-image',        title: 'Генерация изображения' },
    { id: 'presentation', model: 'auto-presentation', title: 'Создать PPTX-презентацию' },
    { id: 'research',     model: 'auto-research',     title: 'Глубокий многоуровневый поиск' },
  ];

  // SVG icons matching OpenWebUI's heroicons style (stroke, currentColor, 16×16)
  var _SVG = {
    image: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-2px;flex-shrink:0"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>',
    presentation: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-2px;flex-shrink:0"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/><polyline points="7 10 10 7 13 10 17 6"/></svg>',
    research: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-2px;flex-shrink:0"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>',
  };

  var INJECT_TOOLS = [
    { id: 'image',        icon: _SVG.image,        label: 'Картинка',      title: 'Генерация изображения' },
    { id: 'presentation', icon: _SVG.presentation, label: 'Презентация',   title: 'Создать PPTX-презентацию' },
    { id: 'research',     icon: _SVG.research,     label: 'Deep Research', title: 'Глубокий многоуровневый поиск' },
  ];

  // ── Find the native "Веб-поиск" button ──
  function _findWebSearchBtn() {
    var btns = document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {
      var t = btns[i].textContent.trim();
      if (t.includes('Веб-поиск') || t.includes('Web Search') || t.includes('Web search')) {
        return btns[i];
      }
    }
    return null;
  }

  // ── Check if native web search is active ──
  function _isWebSearchActive(btn) {
    if (!btn) return false;
    var cls = btn.className || '';
    // OW marks active state with various classes; also check aria-pressed
    return btn.getAttribute('aria-pressed') === 'true' ||
           cls.includes('text-blue') || cls.includes('text-green') ||
           cls.includes('bg-blue') || cls.includes('bg-green') ||
           /\bactive\b/.test(cls);
  }

  // ── Deactivate all our tool buttons (no side-effects on native) ──
  function _deactivateOurs() {
    _activeTool = null;
    document.querySelectorAll('.gpthub-tool-btn').forEach(function(b) {
      b.classList.remove('active');
    });
  }

  // ── Build and inject our buttons into the native toolbar ──
  function _injectButtons() {
    if (document.getElementById('gpthub-tool-btn-image')) return;
    var webSearchBtn = _findWebSearchBtn();
    if (!webSearchBtn) return;
    var container = webSearchBtn.parentElement;
    if (!container) return;

    // Copy native button classes so our buttons look identical
    var nativeCls = webSearchBtn.className;

    // Mark native web search button for CSS targeting
    webSearchBtn.classList.add('gpthub-ws-btn');

    // Watch for class changes on web search button to recolor blue → red
    function _applyWsColor() {
      var cls = webSearchBtn.className || '';
      var isActive = cls.includes('blue') || cls.includes('green') ||
                     webSearchBtn.getAttribute('aria-pressed') === 'true';
      var isDark = document.documentElement.classList.contains('dark');
      if (isActive) {
        webSearchBtn.style.setProperty('color', isDark ? '#ff8a8a' : '#c0392b', 'important');
        webSearchBtn.style.setProperty('background', isDark ? 'rgba(227,6,17,0.2)' : 'rgba(227,6,17,0.1)', 'important');
        // Also recolor inner SVG/spans
        webSearchBtn.querySelectorAll('svg, span').forEach(function(el) {
          el.style.setProperty('color', isDark ? '#ff8a8a' : '#c0392b', 'important');
        });
      } else {
        webSearchBtn.style.removeProperty('color');
        webSearchBtn.style.removeProperty('background');
        webSearchBtn.querySelectorAll('svg, span').forEach(function(el) {
          el.style.removeProperty('color');
        });
      }
    }

    new MutationObserver(_applyWsColor).observe(webSearchBtn, {
      attributes: true, attributeFilter: ['class', 'aria-pressed']
    });
    _applyWsColor(); // apply on initial inject too

    // Hook native "Веб-поиск":
    // When clicked → deactivate our tools (mutual exclusion)
    if (!webSearchBtn.dataset.gpthubHooked) {
      webSearchBtn.dataset.gpthubHooked = '1';
      webSearchBtn.addEventListener('click', function () {
        _deactivateOurs();
      });
    }

    // Inject our tool buttons after the web search button
    INJECT_TOOLS.forEach(function (tool) {
      var btn = document.createElement('button');
      btn.id = 'gpthub-tool-btn-' + tool.id;
      // Use same classes as native button for identical appearance
      btn.className = nativeCls + ' gpthub-tool-btn';
      btn.dataset.tool = tool.id;
      btn.title = tool.title;
      btn.type = 'button';
      btn.innerHTML = tool.icon + '<span style="margin-left:4px">' + tool.label + '</span>';

      btn.addEventListener('click', function () {
        if (_activeTool === tool.id) {
          // Toggle off
          _deactivateOurs();
          // Restore native button appearance to default
          btn.className = nativeCls + ' gpthub-tool-btn';
        } else {
          // Deactivate native web search if it's active
          if (_isWebSearchActive(webSearchBtn)) {
            webSearchBtn.click();
          }
          // Deactivate other our buttons
          _deactivateOurs();
          // Activate this one
          _activeTool = tool.id;
          btn.className = nativeCls + ' gpthub-tool-btn active';
        }
        console.log('[GPTHub] Tool active:', _activeTool);
      });

      container.appendChild(btn);
    });

    // Keep our active button styled correctly when native classes change
    // (OW sometimes re-renders the toolbar container)
    console.log('[GPTHub] Tool buttons injected into native toolbar');
  }

  // ── Fetch interceptor — swap model when a tool is active ──
  // Object.defineProperty trick to survive OpenWebUI overwriting window.fetch.
  var _nativeFetch  = window.fetch;
  var _innerFetch   = window.fetch;
  var _toolInFlight = false;

  function _toolFetch(url, opts) {
    if (_toolInFlight) {
      return _nativeFetch.call(this, url, opts);
    }

    if (_activeTool) {
      var urlStr = (typeof url === 'string') ? url : (url && url.url ? url.url : '');
      if (urlStr.includes('/api/chat/completions') || urlStr.includes('/chat/completions')) {
        try {
          var body = opts && opts.body ? JSON.parse(opts.body) : null;
          if (body) {
            var tool = TOOLS.find(function(t) { return t.id === _activeTool; });
            if (tool) {
              console.log('[GPTHub] Tool swap:', body.model, '\u2192', tool.model);
              body.model = tool.model;
              opts = Object.assign({}, opts, { body: JSON.stringify(body) });
            }
          }
        } catch(e) {}
      }
    }

    _toolInFlight = true;
    try {
      return _innerFetch.call(this, url, opts);
    } finally {
      _toolInFlight = false;
    }
  }

  try {
    Object.defineProperty(window, 'fetch', {
      get: function () { return _toolFetch; },
      set: function (fn) { if (fn !== _toolFetch) _innerFetch = fn; },
      configurable: true,
    });
  } catch (e) {
    _innerFetch = window.fetch;
    window.fetch = _toolFetch;
  }

  // Watch for native toolbar to appear and inject our buttons
  new MutationObserver(function () {
    if (!document.getElementById('gpthub-tool-btn-image')) {
      _injectButtons();
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
  setTimeout(_injectButtons, 1000);

  // Auto-deactivate after message send (single-use per message)
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && _activeTool) {
      setTimeout(_deactivateAll, 200);
    }
  }, true);

  console.log('[GPTHub] Tool buttons loaded');
})();

// ═══════════════════════════════════════════════════════════════════════
//  6. MODEL DESCRIPTIONS — subtitle under each model in the selector
// ═══════════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  var MODEL_DESCS = {
    'auto':                                    'Автоматический выбор лучшей модели',
    'auto-code':                               'Оптимизирован для кода — Qwen3 Coder 480B',
    'auto-reasoning':                          'Глубокие рассуждения — DeepSeek R1 / QwQ 32B',
    'auto-creative':                           'Творческие задачи — Qwen3 235B',
    'auto-fast':                               'Быстрые ответы — GPT-OSS 20B',
    'gpt-oss-20b':                             'Быстрая общая модель · 3858 TPS',
    'gpt-oss-120b':                            'Мощная общая модель · 2721 TPS',
    'qwen3-coder-480b-a35b':                   'Лучший код · 480B параметров',
    'deepseek-r1-distill-qwen-32b':            'Рассуждения с цепочкой мыслей',
    'QwQ-32B':                                 'Альтернативная reasoning модель',
    'Qwen3-235B-A22B-Instruct-2507-FP8':       'Творчество и сложные задачи · 235B',
    'qwen3-32b':                               'Быстрая модель Qwen · 32B',
    'qwen2.5-72b-instruct':                    'Общая модель Qwen 2.5 · 72B',
    'qwen3-vl-30b-a3b-instruct':               'Понимает изображения · Vision 30B',
    'qwen2.5-vl':                              'Vision модель Qwen 2.5',
    'qwen2.5-vl-72b':                          'Мощное зрение · Vision 72B',
    'cotype-pro-vl-32b':                       'Vision модель CoType Pro · 32B',
    'whisper-turbo-local':                     'Распознавание речи · Whisper Turbo',
    'whisper-medium':                          'Распознавание речи · Whisper Medium',
    'qwen-image-lightning':                    'Генерация изображений · быстро',
    'qwen-image':                              'Генерация изображений · качество',
    'bge-m3':                                  'Эмбеддинги для поиска и RAG',
    'llama-3.3-70b-instruct':                  'Llama 3.3 · 70B',
    'llama-3.1-8b-instruct':                   'Llama 3.1 · 8B быстрый',
    'kimi-k2-instruct':                        'Kimi K2 от Moonshot AI',
    'glm-4.6-357b':                            'GLM-4.6 · 357B параметров',
    'gemma-3-27b-it':                          'Gemma 3 от Google · 27B',
    'T-pro-it-1.0':                            'T-Pro от МТС',
    'mws-gpt-alpha':                           'MWS GPT Alpha',
  };

  function _injectDescs() {
    var buttons = document.querySelectorAll('button[aria-label="model-item"]:not([data-gpthub-desc])');
    buttons.forEach(function (btn) {
      btn.setAttribute('data-gpthub-desc', '1');
      var modelId = btn.getAttribute('data-value') || '';
      var desc = MODEL_DESCS[modelId];
      if (!desc) return;

      // Fix line-clamp that cuts off subtitles
      btn.style.webkitLineClamp = 'unset';
      btn.style.overflow = 'visible';

      var colDiv = btn.querySelector('div');
      if (!colDiv) return;

      var span = document.createElement('span');
      span.className = 'gpthub-model-desc';
      span.textContent = desc;
      colDiv.appendChild(span);
    });
  }

  new MutationObserver(function () {
    if (document.querySelector('button[aria-label="model-item"]')) {
      _injectDescs();
    }
  }).observe(document.documentElement, { childList: true, subtree: true });

  setTimeout(_injectDescs, 500);
  console.log('[GPTHub] Model descriptions loaded');
})();


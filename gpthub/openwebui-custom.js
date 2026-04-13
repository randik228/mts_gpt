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
})();

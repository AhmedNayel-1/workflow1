/* Gmail MD3 RTL Interactive UI Controller */
(function () {
  var modalZoomPct = 100;
  var activeDraftObjectUrl = null;
  var activeUtilityTab = null;
  var modalRotateDeg = 0;
  var currentPreviewUrl = '';
  var currentPreviewRawText = '';
  var currentPreviewState = {
    name: '',
    kind: 'other',
    previewUrl: '',
    rawText: '',
    officeHtml: ''
  };

  /* Smart Notifications state */
  var notifCache = [];
  var activeNotifFilter = 'ALL';

  /* Real-Time Chat state */
  var chatState = {
    current_user_id: null,
    current_username: '',
    conversations: [],
    messages: [],
    chat_users: [],
    online_user_ids: [],
    total_unread: 0
  };
  var chatView = 'list';
  var activeChatConvId = null;
  var chatExpanded = false;
  var chatDraftFile = null;
  var chatDraftObjUrl = null;
  var chatGroupSelectedIds = {};
  var chatChannel = null;
  try {
    if (typeof BroadcastChannel !== 'undefined') {
      chatChannel = new BroadcastChannel('correspondence_chat_sync');
      chatChannel.onmessage = function () {
        loadChatState(false);
      };
    }
  } catch (_) {}

  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.getAttribute('content')) return meta.getAttribute('content');
    var inp = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return inp ? inp.value : '';
  }

  function escapeHtml(val) {
    return String(val == null ? '' : val)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatBytes(bytes) {
    var n = Number(bytes || 0);
    if (!n) return '0 B';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return Math.max(1, Math.round(n / 1024)) + ' KB';
    return (n / (1024 * 1024)).toFixed(1) + ' MB';
  }

  /* =========================================================================
     Sidebar & Utility Rail Drawer
     ========================================================================= */
  window.toggleSidebar = function () {
    var sb = document.getElementById('gmail-sidebar');
    if (!sb) return;
    if (window.innerWidth < 768) {
      sb.classList.toggle('hidden');
      sb.classList.add('is-expanded');
    } else {
      sb.classList.remove('hidden');
      var expanded = sb.classList.toggle('is-expanded');
      try { localStorage.setItem('gmail_rail_expanded', expanded ? '1' : '0'); } catch (_) {}
    }
  };

  window.toggleAccountPopover = function (e) {
    if (e && e.stopPropagation) e.stopPropagation();
    var pop = document.getElementById('topbar-account-popover');
    if (pop) pop.classList.toggle('hidden');
  };

  window.toggleComposeAdvanced = function () {
    var box = document.getElementById('compose-advanced-options');
    var arrow = document.getElementById('compose-adv-arrow');
    if (!box) return;
    var hidden = box.classList.toggle('hidden');
    if (arrow) arrow.textContent = hidden ? '▾' : '▴';
  };

  window.toggleRailSwitcherPopover = function (e) {
    if (e && e.stopPropagation) e.stopPropagation();
    var pop = document.getElementById('rail-switcher-popover');
    if (pop) pop.classList.toggle('hidden');
  };

  window.toggleMoreFolders = function () {
    var el = document.getElementById('more-folders');
    var arr = document.getElementById('more-arrow');
    if (!el) return;
    el.classList.toggle('hidden');
    if (arr) arr.textContent = el.classList.contains('hidden') ? '▾' : '▴';
  };

  function syncUtilityDrawerChrome(tabKey) {
    var drawer = document.getElementById('gmail-utility-drawer');
    var titleEl = document.getElementById('utility-drawer-title');
    var expandBtn = document.getElementById('chat-expand-btn');
    var titles = {
      alerts: 'التنبيهات والمتابعة',
      tasks: 'المهام والقرارات',
      guide: 'دليل الاستخدام السريع',
      chat: 'المحادثات الفورية'
    };
    if (titleEl) titleEl.textContent = titles[tabKey] || 'لوحة المساعدة';
    if (expandBtn) {
      if (tabKey === 'chat') expandBtn.classList.remove('hidden');
      else expandBtn.classList.add('hidden');
    }
    if (drawer) {
      if (tabKey === 'chat' && chatExpanded) drawer.classList.add('is-wide');
      else drawer.classList.remove('is-wide');
    }
  }

  window.toggleUtilityDrawer = function (tabKey) {
    var drawer = document.getElementById('gmail-utility-drawer');
    if (!drawer) return;
    var panels = drawer.querySelectorAll('[data-drawer-panel]');
    var btns = document.querySelectorAll('[data-rail-btn]');

    if (activeUtilityTab === tabKey && !drawer.classList.contains('hidden')) {
      drawer.classList.add('hidden');
      drawer.classList.remove('is-wide');
      activeUtilityTab = null;
      btns.forEach(function (b) { b.classList.remove('bg-[#D3E3FD]', 'text-[#001D35]'); });
      return;
    }

    activeUtilityTab = tabKey;
    drawer.classList.remove('hidden');
    syncUtilityDrawerChrome(tabKey);

    panels.forEach(function (p) {
      if (p.getAttribute('data-drawer-panel') === tabKey) {
        p.classList.remove('hidden');
      } else {
        p.classList.add('hidden');
      }
    });
    btns.forEach(function (b) {
      if (b.getAttribute('data-rail-btn') === tabKey) {
        b.classList.add('bg-[#D3E3FD]', 'text-[#001D35]');
      } else {
        b.classList.remove('bg-[#D3E3FD]', 'text-[#001D35]');
      }
    });

    if (tabKey === 'alerts') loadSmartNotificationsDrawer();
    if (tabKey === 'chat') loadChatState(true);
  };

  window.closeUtilityDrawer = function () {
    var drawer = document.getElementById('gmail-utility-drawer');
    if (drawer) {
      drawer.classList.add('hidden');
      drawer.classList.remove('is-wide');
    }
    activeUtilityTab = null;
    document.querySelectorAll('[data-rail-btn]').forEach(function (b) {
      b.classList.remove('bg-[#D3E3FD]', 'text-[#001D35]');
    });
  };

  /* =========================================================================
     Dual-Mode Compose & Reference Memo Dropdown
     ========================================================================= */
  window.filterComposeUnitsBySector = function () {
    var secEl = document.getElementById('compose-sector-select');
    var unitEl = document.getElementById('compose-unit-select');
    if (!secEl || !unitEl) return;
    var secId = secEl.value;
    var firstVisible = null;
    for (var i = 0; i < unitEl.options.length; i++) {
      var opt = unitEl.options[i];
      var match = !opt.getAttribute('data-sector') || opt.getAttribute('data-sector') === secId;
      opt.hidden = !match;
      if (match && !firstVisible) firstVisible = opt;
    }
    if (unitEl.selectedOptions.length === 0 || unitEl.selectedOptions[0].hidden) {
      if (firstVisible) unitEl.value = firstVisible.value;
    }
  };

  window.setComposeMode = function (mode) {
    var modeInput = document.getElementById('compose-mode-input');
    var docBtn = document.getElementById('compose-mode-doc-btn');
    var msgBtn = document.getElementById('compose-mode-msg-btn');
    var msgRow = document.getElementById('compose-msg-recipients-row');
    var submitBtn = document.getElementById('compose-submit-btn');

    if (modeInput) modeInput.value = mode;
    if (mode === 'message') {
      if (msgRow) msgRow.classList.remove('hidden');
      if (docBtn) {
        docBtn.classList.remove('bg-[#D3E3FD]', 'text-[#001D35]');
        docBtn.classList.add('text-[#5F6368]');
      }
      if (msgBtn) {
        msgBtn.classList.add('bg-[#D3E3FD]', 'text-[#001D35]');
        msgBtn.classList.remove('text-[#5F6368]');
      }
      if (submitBtn) submitBtn.textContent = 'إرسال الرسالة الآن';
    } else {
      if (msgRow) msgRow.classList.add('hidden');
      if (docBtn) {
        docBtn.classList.add('bg-[#D3E3FD]', 'text-[#001D35]');
        docBtn.classList.remove('text-[#5F6368]');
      }
      if (msgBtn) {
        msgBtn.classList.remove('bg-[#D3E3FD]', 'text-[#001D35]');
        msgBtn.classList.add('text-[#5F6368]');
      }
      if (submitBtn) submitBtn.textContent = 'حفظ وإنشاء الموضوع';
    }
  };

  window.toggleCustomMemoRecipient = function () {
    var sel = document.getElementById('memo-directed-select');
    var custom = document.getElementById('memo-directed-custom');
    if (!sel || !custom) return;
    if (sel.value === '__CUSTOM__') {
      custom.classList.remove('hidden');
      custom.required = true;
    } else {
      custom.classList.add('hidden');
      custom.required = false;
    }
  };

  window.openComposeModal = function () {
    var m = document.getElementById('gmail-compose-modal');
    if (m) {
      m.classList.remove('hidden', 'is-minimized');
      window.filterComposeUnitsBySector();
    }
  };

  window.closeComposeModal = function () {
    var m = document.getElementById('gmail-compose-modal');
    if (m) m.classList.add('hidden');
  };

  window.toggleComposeMinimize = function () {
    var m = document.getElementById('gmail-compose-modal');
    if (!m) return;
    m.classList.remove('is-expanded');
    m.classList.toggle('is-minimized');
  };

  window.toggleComposeExpand = function () {
    var m = document.getElementById('gmail-compose-modal');
    if (!m) return;
    m.classList.remove('is-minimized');
    m.classList.toggle('is-expanded');
  };

  window.handleComposeFileSelect = function (input) {
    var lbl = document.getElementById('compose-file-label');
    var previewBtn = document.getElementById('compose-file-preview-btn');
    if (!input || !input.files || !input.files[0]) {
      if (lbl) lbl.textContent = '';
      if (previewBtn) previewBtn.classList.add('hidden');
      return;
    }
    var file = input.files[0];
    if (lbl) lbl.textContent = 'تم اختيار: ' + file.name + ' (' + Math.max(1, Math.round(file.size / 1024)) + ' KB)';
    if (previewBtn) previewBtn.classList.remove('hidden');
  };

  window.previewSelectedComposeFile = function () {
    var input = document.getElementById('compose-attachment-input');
    if (!input || !input.files || !input.files[0]) return;
    previewLocalFileObject(input.files[0]);
  };

  function previewLocalFileObject(file) {
    if (!file) return;
    if (activeDraftObjectUrl) {
      URL.revokeObjectURL(activeDraftObjectUrl);
      activeDraftObjectUrl = null;
    }
    var kind = inferKindFromName(file.name, 'auto', file.type);
    if (kind === 'text' || kind === 'csv' || kind === 'json') {
      var reader = new FileReader();
      reader.onload = function () {
        openInlineAttachmentPreview('draft', file.name, kind, '', '', '', String(reader.result || ''));
      };
      reader.readAsText(file, 'UTF-8');
      return;
    }
    activeDraftObjectUrl = URL.createObjectURL(file);
    openInlineAttachmentPreview('draft', file.name, kind, activeDraftObjectUrl, activeDraftObjectUrl, '');
  }

  /* =========================================================================
     Universal Attachment Preview Modal / Docked Side Panel
     ========================================================================= */
  function getFileExtension(name) {
    var parts = String(name || '').toLowerCase().split('.');
    return parts.length > 1 ? parts.pop() : 'FILE';
  }

  function inferKindFromName(name, explicitKind, mimeType) {
    var lower = String(name || '').toLowerCase();
    var mime = String(mimeType || '').toLowerCase();
    if (lower.endsWith('.csv') || lower.endsWith('.tsv')) return 'csv';
    if (lower.endsWith('.json')) return 'json';
    if (lower.endsWith('.pdf') || mime === 'application/pdf') return 'pdf';
    if (/\.(png|jpe?g|gif|webp|svg|bmp|ico|avif)$/.test(lower) || /^image\/(png|jpe?g|gif|webp|svg\+xml|bmp|x-icon|avif)$/.test(mime)) return 'image';
    if (/\.(mp3|wav|ogg|m4a|aac|flac)$/.test(lower) || mime.indexOf('audio/') === 0) return 'audio';
    if (/\.(mp4|webm|mov|m4v)$/.test(lower) || mime.indexOf('video/') === 0) return 'video';
    if (/\.(txt|md|log|xml|html?|yml|yaml|sql|py|js|ts|css|ini|conf)$/.test(lower) || mime.indexOf('text/') === 0) return 'text';
    if (explicitKind && explicitKind !== 'auto' && explicitKind !== 'office') return explicitKind;
    return 'office';
  }

  function renderCsvIntoContainer(wrapEl, rawText) {
    wrapEl.innerHTML = '';
    var lines = String(rawText || '').replace(/\r/g, '').split('\n').filter(function (l) { return l.trim().length > 0; }).slice(0, 120);
    if (!lines.length) {
      wrapEl.textContent = 'الملف فارغ.';
      return;
    }
    var sep = lines[0].indexOf('\t') !== -1 ? '\t' : ',';
    var table = document.createElement('table');
    table.className = 'w-full text-xs text-right';
    lines.forEach(function (line, rIdx) {
      var tr = document.createElement('tr');
      tr.className = rIdx === 0 ? 'bg-[#F2F6FC] font-bold text-[#1F1F1F] border-b border-[#E1E3E1]' : 'border-b border-[#ECEFF1] hover:bg-[#F8FAFD]';
      line.split(sep).forEach(function (cell) {
        var td = document.createElement(rIdx === 0 ? 'th' : 'td');
        td.className = 'px-3 py-2 text-[#1F1F1F]';
        td.textContent = cell.replace(/^"|"$/g, '');
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    wrapEl.appendChild(table);
  }

  window.togglePreviewDisplayMode = function () {
    var modal = document.getElementById('inline-preview-modal');
    var btn = document.getElementById('inline-preview-mode-btn');
    if (!modal) return;
    var isSide = modal.classList.toggle('is-side-panel');
    if (btn) btn.textContent = isSide ? 'نافذة منبثقة' : 'لوحة جانبية';
  };

  window.rotateModalImage = function () {
    modalRotateDeg = (modalRotateDeg + 90) % 360;
    var imgEl = document.getElementById('inline-preview-img');
    if (imgEl) imgEl.style.transform = 'rotate(' + modalRotateDeg + 'deg)';
  };

  window.inspectFallbackRawText = function () {
    var textBox = document.getElementById('inline-preview-text-box');
    var fallback = document.getElementById('inline-preview-fallback');
    if (!textBox) return;
    if (currentPreviewRawText) {
      if (fallback) fallback.classList.add('hidden');
      textBox.textContent = currentPreviewRawText;
      textBox.classList.remove('hidden');
    } else if (currentPreviewUrl) {
      var rawEndpoint = currentPreviewUrl.split('?')[0] + '?raw=1';
      fetch(rawEndpoint, { credentials: 'same-origin' })
        .then(function (r) { return r.text(); })
        .then(function (txt) {
          if (fallback) fallback.classList.add('hidden');
          textBox.textContent = txt.slice(0, 12000) || '(لا توجد بيانات نصية مقروءة)';
          textBox.classList.remove('hidden');
        })
        .catch(function () {});
    }
  };

  window.openInlineAttachmentPreview = function (attId, name, kind, previewUrl, downloadUrl, fullPageUrl, rawTextContent) {
    var modal = document.getElementById('inline-preview-modal');
    var titleEl = document.getElementById('inline-preview-title');
    var extEl = document.getElementById('inline-preview-ext');
    var fallbackExtEl = document.getElementById('inline-preview-fallback-ext');
    var frame = document.getElementById('inline-preview-frame');
    var textBox = document.getElementById('inline-preview-text-box');
    var csvWrap = document.getElementById('inline-preview-csv-wrap');
    var audioWrap = document.getElementById('inline-preview-audio-wrap');
    var audioEl = document.getElementById('inline-preview-audio');
    var videoWrap = document.getElementById('inline-preview-video-wrap');
    var videoEl = document.getElementById('inline-preview-video');
    var imgWrap = document.getElementById('inline-preview-img-wrap');
    var imgEl = document.getElementById('inline-preview-img');
    var fallback = document.getElementById('inline-preview-fallback');
    var dl = document.getElementById('inline-preview-download');
    var newTab = document.getElementById('inline-preview-newtab');
    var zoomVal = document.getElementById('inline-preview-zoom-val');

    var officeWrap = document.getElementById('inline-preview-office-wrap');
    if (!modal) return;
    var resolvedKind = inferKindFromName(name, kind);
    var extLabel = getFileExtension(name).toUpperCase();
    currentPreviewUrl = previewUrl || '';
    currentPreviewRawText = rawTextContent || '';
    currentPreviewState = {
      name: name || 'مرفق',
      kind: resolvedKind,
      previewUrl: previewUrl || '',
      rawText: rawTextContent || '',
      officeHtml: ''
    };
    modalZoomPct = 100;
    modalRotateDeg = 0;
    if (zoomVal) zoomVal.textContent = '100%';
    if (titleEl) titleEl.textContent = 'معاينة: ' + (name || 'مرفق');
    if (extEl) extEl.textContent = extLabel;
    if (fallbackExtEl) fallbackExtEl.textContent = extLabel;

    if (dl) {
      if (downloadUrl) {
        dl.href = downloadUrl;
        dl.setAttribute('download', name || 'document');
        dl.classList.remove('hidden');
      } else {
        dl.classList.add('hidden');
      }
    }
    if (newTab) {
      var tabHref = fullPageUrl || previewUrl;
      if (tabHref) {
        newTab.href = tabHref;
        newTab.classList.remove('hidden');
      } else {
        newTab.classList.add('hidden');
      }
    }

    if (frame) { frame.classList.add('hidden'); frame.src = ''; }
    if (textBox) { textBox.classList.add('hidden'); textBox.textContent = ''; }
    if (csvWrap) { csvWrap.classList.add('hidden'); csvWrap.innerHTML = ''; }
    if (officeWrap) { officeWrap.classList.add('hidden'); officeWrap.innerHTML = ''; }
    if (audioWrap) audioWrap.classList.add('hidden');
    if (audioEl) audioEl.src = '';
    if (videoWrap) videoWrap.classList.add('hidden');
    if (videoEl) videoEl.src = '';
    if (imgWrap) imgWrap.classList.add('hidden');
    if (imgEl) { imgEl.src = ''; imgEl.style.width = '100%'; imgEl.style.transform = 'rotate(0deg)'; }
    if (fallback) fallback.classList.add('hidden');

    if (resolvedKind === 'image' && previewUrl && imgWrap && imgEl) {
      imgEl.src = previewUrl;
      imgWrap.classList.remove('hidden');
    } else if (resolvedKind === 'audio' && previewUrl && audioWrap && audioEl) {
      audioEl.src = previewUrl;
      audioWrap.classList.remove('hidden');
    } else if (resolvedKind === 'video' && previewUrl && videoWrap && videoEl) {
      videoEl.src = previewUrl;
      videoWrap.classList.remove('hidden');
    } else if (resolvedKind === 'office' && officeWrap && previewUrl) {
      officeWrap.innerHTML = '<div class="p-6 text-center text-xs text-[#5F6368]">جاري استخراج ومعاينة مستند الأوفيس...</div>';
      officeWrap.classList.remove('hidden');
      var officeEndpoint = previewUrl.split('?')[0] + '?mode=office_html';
      fetch(officeEndpoint, { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.text();
        })
        .then(function (html) {
          currentPreviewState.officeHtml = html;
          officeWrap.innerHTML = html;
        })
        .catch(function () {
          officeWrap.classList.add('hidden');
          if (fallback) fallback.classList.remove('hidden');
        });
    } else if ((resolvedKind === 'text' || resolvedKind === 'csv' || resolvedKind === 'json') && textBox) {
      var applyText = function (txt) {
        currentPreviewState.rawText = txt;
        if (resolvedKind === 'csv' && csvWrap) {
          renderCsvIntoContainer(csvWrap, txt);
          csvWrap.classList.remove('hidden');
        } else if (resolvedKind === 'json') {
          try { textBox.textContent = JSON.stringify(JSON.parse(txt), null, 2); }
          catch (_) { textBox.textContent = txt; }
          textBox.classList.remove('hidden');
        } else {
          textBox.textContent = txt;
          textBox.classList.remove('hidden');
        }
      };
      if (typeof rawTextContent === 'string' && rawTextContent.length > 0) {
        applyText(rawTextContent);
      } else if (previewUrl) {
        textBox.textContent = 'جاري تحميل محتوى الملف...';
        textBox.classList.remove('hidden');
        fetch(previewUrl, { credentials: 'same-origin' })
          .then(function (r) { return r.text(); })
          .then(function (txt) {
            textBox.classList.add('hidden');
            applyText(txt);
          })
          .catch(function () {
            textBox.classList.add('hidden');
            if (fallback) fallback.classList.remove('hidden');
          });
      } else if (fallback) {
        fallback.classList.remove('hidden');
      }
    } else if (resolvedKind === 'pdf' && previewUrl && frame) {
      frame.src = previewUrl;
      frame.classList.remove('hidden');
    } else if (fallback) {
      fallback.classList.remove('hidden');
    }

    if (window.location && window.location.pathname && window.location.pathname.indexOf('/subjects/') !== -1) {
      modal.classList.add('is-side-panel');
      var modeBtn = document.getElementById('inline-preview-mode-btn');
      if (modeBtn) modeBtn.textContent = 'نافذة منبثقة';
    }

    modal.classList.remove('hidden');
  };

  window.closeInlineAttachmentPreview = function () {
    var modal = document.getElementById('inline-preview-modal');
    var frame = document.getElementById('inline-preview-frame');
    var imgEl = document.getElementById('inline-preview-img');
    var audioEl = document.getElementById('inline-preview-audio');
    var videoEl = document.getElementById('inline-preview-video');
    if (frame) frame.src = '';
    if (imgEl) imgEl.src = '';
    if (audioEl) { audioEl.pause(); audioEl.src = ''; }
    if (videoEl) { videoEl.pause(); videoEl.src = ''; }
    if (modal) modal.classList.add('hidden');
  };

  window.setModalZoom = function (deltaOrReset) {
    var imgEl = document.getElementById('inline-preview-img');
    var zoomVal = document.getElementById('inline-preview-zoom-val');
    if (deltaOrReset === 0) modalZoomPct = 100;
    else modalZoomPct = Math.min(200, Math.max(40, modalZoomPct + deltaOrReset));
    if (imgEl) imgEl.style.width = modalZoomPct + '%';
    if (zoomVal) zoomVal.textContent = modalZoomPct + '%';
  };

  /* =========================================================================
     Inbox Split Reading Panel
     ========================================================================= */
  window.closeInboxSplitPreview = function () {
    var panel = document.getElementById('inbox-split-panel');
    if (panel) {
      panel.classList.add('hidden');
      panel.innerHTML = '';
    }
    document.querySelectorAll('[data-subject-row]').forEach(function (r) {
      r.classList.remove('bg-[#E8F0FE]/60');
    });
  };

  window.openInboxSplitPreview = function (subjectId, rowEl) {
    var panel = document.getElementById('inbox-split-panel');
    if (!panel) return;
    document.querySelectorAll('[data-subject-row]').forEach(function (r) {
      r.classList.remove('bg-[#E8F0FE]/60');
    });
    if (rowEl) rowEl.classList.add('bg-[#E8F0FE]/60');

    panel.classList.remove('hidden');
    panel.innerHTML = '<div class="p-6 text-center text-xs text-[#5F6368]">جاري تحميل معاينة الموضوع...</div>';

    fetch('/subjects/' + encodeURIComponent(subjectId) + '/preview-json/', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        renderInboxSplitPanel(panel, data);
      })
      .catch(function () {
        panel.innerHTML =
          '<div class="p-6 text-center space-y-2 text-xs text-[#A50E0E]">' +
          '<div>تعذر تحميل تفاصيل الموضوع في لوحة القراءة.</div>' +
          '<button type="button" onclick="closeInboxSplitPreview()" class="px-3 py-1 rounded-full bg-[#F2F6FC] text-[#444746] font-bold">إغلاق</button>' +
          '</div>';
      });
  };

  function renderInboxSplitPanel(panel, d) {
    panel.innerHTML = '';

    /* Header */
    var header = document.createElement('div');
    header.className = 'p-4 border-b border-[#ECEFF1] bg-[#F9FBFD] flex items-center justify-between gap-2 shrink-0';
    var badgesWrap = document.createElement('div');
    badgesWrap.className = 'flex flex-wrap items-center gap-1.5 min-w-0';
    badgesWrap.innerHTML =
      '<span class="mono-num text-xs font-bold text-[#0B57D0] bg-[#E8F0FE] px-2.5 py-0.5 rounded-full">' + escapeHtml(d.internal_number) + '</span>' +
      '<span class="text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-white border border-[#DADCE0] text-[#444746]">' + escapeHtml(d.status_label) + '</span>' +
      (d.is_top_secret ? '<span class="text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-[#FCE8E6] text-[#A50E0E]">🔒 ' + escapeHtml(d.confidentiality) + '</span>' : '');
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'p-1.5 rounded-full hover:bg-[#E1E5EA] text-[#5F6368] shrink-0';
    closeBtn.title = 'إغلاق لوحة القراءة';
    closeBtn.textContent = '✕';
    closeBtn.onclick = window.closeInboxSplitPreview;
    header.appendChild(badgesWrap);
    header.appendChild(closeBtn);
    panel.appendChild(header);

    /* Body */
    var body = document.createElement('div');
    body.className = 'flex-1 overflow-y-auto p-5 space-y-4 text-sm';

    var titleBlock = document.createElement('div');
    titleBlock.className = 'space-y-1';
    var h3 = document.createElement('h3');
    h3.className = 'text-base font-bold text-[#1F1F1F] leading-snug';
    h3.textContent = d.title || '';
    var subMeta = document.createElement('div');
    subMeta.className = 'text-xs text-[#5F6368]';
    subMeta.textContent = (d.transaction_type || '') + ' · ' + (d.sector || '');
    titleBlock.appendChild(h3);
    titleBlock.appendChild(subMeta);
    body.appendChild(titleBlock);

    /* 2x2 grid */
    var metaGrid = document.createElement('div');
    metaGrid.className = 'grid grid-cols-2 gap-3 bg-[#F6F8FC] p-3.5 rounded-2xl border border-[#ECEFF1]';
    metaGrid.innerHTML =
      '<div><div class="text-xs text-[#5F6368] font-medium">القسم المختص</div><div class="font-bold text-[#1F1F1F] mt-0.5">' + escapeHtml(d.org_unit) + '</div></div>' +
      '<div><div class="text-xs text-[#5F6368] font-medium">المكلف الحالي</div><div class="font-bold text-[#1F1F1F] mt-0.5">' + escapeHtml(d.current_owner) + '</div></div>' +
      '<div><div class="text-xs text-[#5F6368] font-medium">الأهمية</div><div class="font-bold text-[#1F1F1F] mt-0.5">' + escapeHtml(d.priority) + '</div></div>' +
      '<div><div class="text-xs text-[#5F6368] font-medium">موعد الإنجاز</div><div class="font-bold mono-num mt-0.5 ' + (d.is_overdue ? 'text-[#8B5014]' : 'text-[#1F1F1F]') + '">' + escapeHtml(d.due_date) + '</div></div>';
    body.appendChild(metaGrid);

    if (d.description) {
      var descBox = document.createElement('div');
      descBox.className = 'p-4 rounded-2xl bg-white border border-[#ECEFF1] text-[#1F1F1F] text-[15px] leading-[1.8] whitespace-pre-line';
      descBox.textContent = d.description;
      body.appendChild(descBox);
    }

    /* Attachments */
    if (Array.isArray(d.attachments) && d.attachments.length > 0) {
      var attSection = document.createElement('div');
      attSection.className = 'space-y-2';
      var attHdr = document.createElement('div');
      attHdr.className = 'font-bold text-[#1F1F1F] flex items-center justify-between';
      attHdr.textContent = 'المرفقات (' + d.attachments.length + ')';
      attSection.appendChild(attHdr);

      d.attachments.forEach(function (att) {
        var card = document.createElement('div');
        card.className = 'flex items-center justify-between gap-2 p-2.5 rounded-xl bg-[#F9FBFD] border border-[#DADCE0] hover:bg-[#EAF1FB] transition-colors';

        var infoBtn = document.createElement('button');
        infoBtn.type = 'button';
        infoBtn.className = 'min-w-0 flex-1 text-right';
        infoBtn.onclick = function () {
          window.openInlineAttachmentPreview(att.id, att.filename, att.preview_kind, att.preview_url, att.download_url, att.full_page_url);
        };
        infoBtn.innerHTML =
          '<div class="font-bold text-[#1F1F1F] truncate">📎 ' + escapeHtml(att.filename) + '</div>' +
          '<div class="text-[10px] text-[#5F6368] truncate">' + escapeHtml(att.doc_type) + ' · ' + escapeHtml(formatBytes(att.file_size)) + '</div>';

        var actions = document.createElement('div');
        actions.className = 'flex items-center gap-1 shrink-0';
        var prevBtn = document.createElement('button');
        prevBtn.type = 'button';
        prevBtn.className = 'px-2.5 py-1 rounded-full bg-[#D3E3FD] text-[#001D35] text-[11px] font-bold';
        prevBtn.textContent = '👁 معاينة';
        prevBtn.onclick = infoBtn.onclick;
        var dlLink = document.createElement('a');
        dlLink.href = att.download_url;
        dlLink.className = 'px-2 py-1 rounded-full bg-white border border-[#DADCE0] text-[#0B57D0] text-[11px] font-bold';
        dlLink.textContent = '⬇';
        dlLink.title = 'تنزيل';

        actions.appendChild(prevBtn);
        actions.appendChild(dlLink);
        card.appendChild(infoBtn);
        card.appendChild(actions);
        attSection.appendChild(card);
      });
      body.appendChild(attSection);
    }

    /* Recent referrals */
    if (Array.isArray(d.recent_referrals) && d.recent_referrals.length > 0) {
      var refSection = document.createElement('div');
      refSection.className = 'space-y-2';
      var refHdr = document.createElement('div');
      refHdr.className = 'font-bold text-[#1F1F1F]';
      refHdr.textContent = 'أحدث الإحالات والتوجيهات';
      refSection.appendChild(refHdr);
      d.recent_referrals.forEach(function (ref) {
        var rCard = document.createElement('div');
        rCard.className = 'p-2.5 rounded-xl bg-white border border-[#ECEFF1] space-y-1';
        rCard.innerHTML =
          '<div class="flex items-center justify-between gap-2 text-[11px]">' +
          '<strong class="text-[#0B57D0]">' + escapeHtml(ref.referred_by) + ' ← ' + escapeHtml(ref.targets) + '</strong>' +
          '<span class="mono-num text-[#5F6368]">' + escapeHtml(ref.created_at) + '</span>' +
          '</div>' +
          '<div class="text-[11px] text-[#5F6368]">' + escapeHtml(ref.purpose) + (ref.notes ? ': ' + escapeHtml(ref.notes) : '') + '</div>';
        refSection.appendChild(rCard);
      });
      body.appendChild(refSection);
    }

    panel.appendChild(body);

    /* Footer */
    var footer = document.createElement('div');
    footer.className = 'p-3.5 border-t border-[#ECEFF1] bg-[#F9FBFD] flex items-center justify-between gap-2 shrink-0';

    if (d.pending_ref_id && d.ack_url) {
      var ackForm = document.createElement('form');
      ackForm.method = 'post';
      ackForm.action = d.ack_url;
      ackForm.innerHTML =
        '<input type="hidden" name="csrfmiddlewaretoken" value="' + escapeHtml(getCsrfToken()) + '">' +
        '<input type="hidden" name="action" value="acknowledge">' +
        '<button type="submit" class="px-3.5 py-1.5 rounded-full bg-[#137333] hover:bg-[#0D652D] text-white text-xs font-bold">✓ تأكيد الاستلام</button>';
      footer.appendChild(ackForm);
    } else {
      var spanEl = document.createElement('span');
      spanEl.className = 'text-[11px] text-[#5F6368]';
      spanEl.textContent = d.can_act ? 'في عهدتك التنفيذية' : 'للاطلاع والمتابعة';
      footer.appendChild(spanEl);
    }

    var openLink = document.createElement('a');
    openLink.href = d.detail_url || ('/subjects/' + d.id + '/');
    openLink.className = 'px-4 py-1.5 rounded-full bg-[#0B57D0] hover:bg-[#0842A0] text-white text-xs font-bold';
    openLink.textContent = 'فتح السلسلة الكاملة ←';
    footer.appendChild(openLink);

    panel.appendChild(footer);
  }

  /* =========================================================================
     Smart Notifications Drawer
     ========================================================================= */
  function updateNotificationBadges(unreadCount) {
    var count = Number(unreadCount || 0);
    var topBadge = document.getElementById('topbar-notif-badge');
    var railDot = document.getElementById('rail-notif-dot');
    if (topBadge) {
      topBadge.textContent = String(count);
      if (count > 0) topBadge.classList.remove('hidden');
      else topBadge.classList.add('hidden');
    }
    if (railDot) {
      if (count > 0) railDot.classList.remove('hidden');
      else railDot.classList.add('hidden');
    }
  }

  window.loadSmartNotificationsDrawer = function () {
    fetch('/notifications/drawer-state/', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        notifCache = Array.isArray(data.notifications) ? data.notifications : [];
        updateNotificationBadges(data.unread_count);
        renderSmartNotifications();
      })
      .catch(function () {});
  };

  window.filterSmartNotifications = function (cat) {
    activeNotifFilter = cat || 'ALL';
    document.querySelectorAll('[data-notif-filter]').forEach(function (btn) {
      var key = btn.getAttribute('data-notif-filter');
      if (key === activeNotifFilter) {
        btn.classList.add('bg-[#D3E3FD]', 'text-[#001D35]');
        btn.classList.remove('text-[#5F6368]');
      } else {
        btn.classList.remove('bg-[#D3E3FD]', 'text-[#001D35]');
        btn.classList.add('text-[#5F6368]');
      }
    });
    renderSmartNotifications();
  };

  function getNotifCategoryStyle(cat) {
    if (cat === 'INCOMING_REFERRAL') return { icon: '📥', bg: 'bg-[#E8F0FE] text-[#0B57D0]' };
    if (cat === 'REPLY_MEMO') return { icon: '↩', bg: 'bg-[#E6F4EA] text-[#137333]' };
    if (cat === 'ESCALATION_OVERDUE') return { icon: '⚠', bg: 'bg-[#FCE8E6] text-[#A50E0E]' };
    return { icon: '⚖', bg: 'bg-[#FEF7E0] text-[#B06000]' };
  }

  function renderSmartNotifications() {
    var listEl = document.getElementById('smart-notif-list');
    if (!listEl) return;

    var filtered = notifCache.filter(function (n) {
      if (activeNotifFilter === 'ALL') return true;
      if (activeNotifFilter === 'DECISION_TASK') {
        return n.category === 'DECISION_TASK' || n.category === 'APPROVAL_NEEDED';
      }
      return n.category === activeNotifFilter;
    });

    listEl.innerHTML = '';
    if (!filtered.length) {
      var empty = document.createElement('div');
      empty.className = 'py-8 text-center text-[#5F6368] text-xs';
      empty.textContent = 'لا توجد تنبيهات ذكية في هذا التصنيف حالياً.';
      listEl.appendChild(empty);
      return;
    }

    filtered.forEach(function (n) {
      var st = getNotifCategoryStyle(n.category);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className =
        'w-full text-right p-2.5 rounded-xl transition-colors flex flex-col gap-1 ' +
        (n.is_read ? 'bg-white hover:bg-[#F2F6FC]' : 'bg-[#F2F6FC]/70 hover:bg-[#EAF1FB]');

      var topRow = document.createElement('div');
      topRow.className = 'flex items-center justify-between gap-1.5 w-full';
      topRow.innerHTML =
        '<div class="flex items-center gap-1.5 flex-wrap">' +
        (!n.is_read ? '<span class="w-2 h-2 rounded-full bg-[#0B57D0] shrink-0"></span>' : '') +
        '<span class="px-2 py-0.5 rounded-full text-[11px] font-bold ' + st.bg + '">' + st.icon + ' ' + escapeHtml(n.category_label) + '</span>' +
        (n.is_top_secret ? '<span class="px-1.5 py-0.5 rounded bg-[#FCE8E6] text-[#A50E0E] text-[11px] font-bold">🔒 سري</span>' : '') +
        '</div>' +
        '<span class="text-[11px] mono-num text-[#5F6368] shrink-0">' + escapeHtml(n.created_at) + '</span>';

      var titleDiv = document.createElement('div');
      titleDiv.className = 'font-bold text-[#1F1F1F] text-xs leading-snug';
      titleDiv.textContent = n.title || '';

      var msgDiv = document.createElement('div');
      msgDiv.className = 'text-[11px] text-[#444746] leading-snug';
      msgDiv.textContent = n.message || '';

      var reasonDiv = document.createElement('div');
      reasonDiv.className = 'text-[10px] text-[#0B57D0] font-medium';
      reasonDiv.textContent = n.reason_for_level || '';

      btn.appendChild(topRow);
      btn.appendChild(titleDiv);
      btn.appendChild(msgDiv);
      if (n.reason_for_level) btn.appendChild(reasonDiv);

      btn.onclick = function () {
        window.markSmartNotificationRead(n.is_live_escalation ? null : n.id, false, n.link_url);
      };
      listEl.appendChild(btn);
    });
  }

  window.markSmartNotificationRead = function (notifId, markAll, navigateUrl) {
    if (!notifId && !markAll) {
      if (navigateUrl) window.location.href = navigateUrl;
      return;
    }
    fetch('/notifications/mark-read/', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({ notification_id: notifId, mark_all: Boolean(markAll) })
    })
      .then(function () {
        if (markAll) {
          notifCache.forEach(function (x) { x.is_read = true; });
        } else {
          notifCache.forEach(function (x) { if (x.id === notifId) x.is_read = true; });
        }
        var unreadLeft = notifCache.filter(function (x) { return !x.is_read; }).length;
        updateNotificationBadges(unreadLeft);
        renderSmartNotifications();
        if (navigateUrl) window.location.href = navigateUrl;
      })
      .catch(function () {
        if (navigateUrl) window.location.href = navigateUrl;
      });
  };

  /* =========================================================================
     Real-Time Interactive Chat Drawer
     ========================================================================= */
  function showChatError(msg) {
    var box = document.getElementById('chat-error-banner');
    if (!box) return;
    if (!msg) {
      box.classList.add('hidden');
      box.textContent = '';
    } else {
      box.textContent = msg;
      box.classList.remove('hidden');
    }
  }

  function updateChatBadge(totalUnread) {
    var n = Number(totalUnread || 0);
    ['chat-rail-badge', 'topbar-chat-badge'].forEach(function (id) {
      var badge = document.getElementById(id);
      if (!badge) return;
      badge.textContent = String(n);
      if (n > 0) badge.classList.remove('hidden');
      else badge.classList.add('hidden');
    });
  }

  window.toggleChatDrawerExpand = function () {
    chatExpanded = !chatExpanded;
    var drawer = document.getElementById('gmail-utility-drawer');
    if (drawer) drawer.classList.toggle('is-wide', chatExpanded);
  };

  window.switchChatView = function (mode) {
    chatView = mode || 'list';
    showChatError('');
    ['list', 'new_dm', 'new_group', 'thread'].forEach(function (v) {
      var el = document.getElementById('chat-view-' + v);
      if (el) {
        if (v === chatView) el.classList.remove('hidden');
        else el.classList.add('hidden');
      }
    });

    var backBtn = document.getElementById('chat-back-btn');
    var hdrTitle = document.getElementById('chat-header-title');
    var hdrSub = document.getElementById('chat-header-sub');
    if (backBtn) {
      if (chatView === 'list') backBtn.classList.add('hidden');
      else backBtn.classList.remove('hidden');
    }

    if (chatView === 'list') {
      if (hdrTitle) hdrTitle.textContent = 'المحادثات الفورية';
      if (hdrSub) hdrSub.textContent = 'متصل الآن';
      window.renderChatConversations();
    } else if (chatView === 'new_dm') {
      if (hdrTitle) hdrTitle.textContent = 'بدء محادثة مستخدم';
      if (hdrSub) hdrSub.textContent = 'اختر المستخدم لفتح المحادثة المباشرة';
      window.renderChatDirectory('dm');
    } else if (chatView === 'new_group') {
      if (hdrTitle) hdrTitle.textContent = 'إنشاء مجموعة محادثة';
      if (hdrSub) hdrSub.textContent = 'حدد الأعضاء واسم المجموعة';
      window.renderChatDirectory('group');
    } else if (chatView === 'thread') {
      renderActiveThreadHeader();
      renderChatMessages();
    }
  };

  window.loadChatState = function (shouldRender) {
    fetch('/chat/state/', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        chatState = data;
        updateChatBadge(data.total_unread);
        if (activeUtilityTab === 'chat' || shouldRender) {
          if (chatView === 'list') window.renderChatConversations();
          else if (chatView === 'thread') {
            renderActiveThreadHeader();
            renderChatMessages();
          } else if (chatView === 'new_dm') {
            window.renderChatDirectory('dm');
          } else if (chatView === 'new_group') {
            window.renderChatDirectory('group');
          }
        }
      })
      .catch(function () {});
  };

  window.renderChatConversations = function () {
    var listEl = document.getElementById('chat-conversations-list');
    var searchEl = document.getElementById('chat-conv-search');
    if (!listEl) return;
    var q = searchEl ? (searchEl.value || '').trim().toLowerCase() : '';
    var convs = (chatState.conversations || []).filter(function (c) {
      if (!q) return true;
      var hay = ((c.display_title || '') + ' ' + ((c.member_names || []).join(' '))).toLowerCase();
      return hay.indexOf(q) !== -1;
    });

    listEl.innerHTML = '';
    if (!convs.length) {
      var empty = document.createElement('div');
      empty.className = 'py-8 text-center text-xs text-[#5F6368]';
      empty.textContent = 'لا توجد محادثات بعد. ابدأ محادثة أو أنشئ مجموعة.';
      listEl.appendChild(empty);
      return;
    }

    var onlineSet = {};
    (chatState.online_user_ids || []).forEach(function (id) { onlineSet[id] = true; });

    convs.forEach(function (c) {
      var isOnline = c.type === 'direct' && c.peer_id && onlineSet[c.peer_id];
      var lastPreview = c.last_message
        ? (c.last_message.text || (c.last_message.attachment ? '📎 ' + c.last_message.attachment.name : ''))
        : 'لا توجد رسائل بعد';

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'w-full text-right px-2.5 py-2.5 hover:bg-[#F2F6FC] rounded-xl flex items-center gap-2.5 transition-colors';
      btn.onclick = function () { window.openChatConversation(c.id); };

      btn.innerHTML =
        '<div class="relative w-9 h-9 rounded-full flex items-center justify-center font-bold text-xs shrink-0 ' +
        (c.type === 'group' ? 'bg-[#E6F4EA] text-[#137333]' : 'bg-[#D3E3FD] text-[#001D35]') + '">' +
        (c.type === 'group' ? '👥' : escapeHtml((c.display_title || 'م').slice(0, 1))) +
        (c.type === 'direct' ? '<span class="absolute bottom-0 left-0 w-2.5 h-2.5 rounded-full border border-white ' + (isOnline ? 'bg-[#137333]' : 'bg-[#DADCE0]') + '"></span>' : '') +
        '</div>' +
        '<div class="min-w-0 flex-1">' +
        '<div class="flex items-center justify-between gap-2">' +
        '<span class="font-bold text-[#1F1F1F] truncate">' + escapeHtml(c.display_title) + '</span>' +
        (c.unread_count > 0
          ? '<span class="px-1.5 py-0.5 rounded-full bg-[#0B57D0] text-white text-[10px] font-bold mono-num shrink-0">' + c.unread_count + '</span>'
          : (c.last_message ? '<span class="text-[10px] mono-num text-[#5F6368] shrink-0">' + escapeHtml(c.last_message.time_short) + '</span>' : '')) +
        '</div>' +
        '<div class="text-[11px] text-[#5F6368] truncate mt-0.5">' + escapeHtml(lastPreview) + '</div>' +
        '</div>';

      listEl.appendChild(btn);
    });
  };

  window.renderChatDirectory = function (mode) {
    var isGroup = mode === 'group';
    var listEl = document.getElementById(isGroup ? 'chat-group-users-list' : 'chat-dm-users-list');
    var searchEl = document.getElementById(isGroup ? 'chat-group-user-search' : 'chat-dm-user-search');
    if (!listEl) return;

    var q = searchEl ? (searchEl.value || '').trim().toLowerCase() : '';
    var users = (chatState.chat_users || []).filter(function (u) {
      if (u.id === chatState.current_user_id) return false;
      if (!q) return true;
      var hay = ((u.full_name || '') + ' ' + (u.username || '') + ' ' + (u.unit || '')).toLowerCase();
      return hay.indexOf(q) !== -1;
    });

    listEl.innerHTML = '';
    if (!users.length) {
      var empty = document.createElement('div');
      empty.className = 'py-6 text-center text-xs text-[#5F6368]';
      empty.textContent = 'لا يوجد مستخدمون مطابقون للبحث.';
      listEl.appendChild(empty);
      return;
    }

    users.forEach(function (u) {
      if (isGroup) {
        var row = document.createElement('label');
        row.className = 'flex items-center justify-between gap-2 px-2.5 py-2 hover:bg-[#F2F6FC] rounded-xl cursor-pointer';
        var left = document.createElement('div');
        left.className = 'flex items-center gap-2 min-w-0';
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = Boolean(chatGroupSelectedIds[u.id]);
        cb.onchange = function () {
          if (cb.checked) chatGroupSelectedIds[u.id] = true;
          else delete chatGroupSelectedIds[u.id];
          var cnt = Object.keys(chatGroupSelectedIds).length;
          var cntEl = document.getElementById('chat-group-selected-count');
          if (cntEl) cntEl.textContent = cnt + ' أعضاء محددون';
        };
        var txt = document.createElement('div');
        txt.className = 'min-w-0';
        txt.innerHTML =
          '<div class="font-bold text-[#1F1F1F] truncate">' + escapeHtml(u.full_name) + '</div>' +
          '<div class="text-[10px] text-[#5F6368] truncate">' + escapeHtml(u.unit) + ' · ' + escapeHtml(u.level) + '</div>';
        left.appendChild(cb);
        left.appendChild(txt);
        row.appendChild(left);
        listEl.appendChild(row);
      } else {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'w-full text-right flex items-center justify-between gap-2 px-2.5 py-2 hover:bg-[#F2F6FC] rounded-xl';
        btn.onclick = function () { window.createDirectChat(u.id); };
        btn.innerHTML =
          '<div class="flex items-center gap-2 min-w-0">' +
          '<span class="w-2.5 h-2.5 rounded-full shrink-0 ' + (u.is_online ? 'bg-[#137333]' : 'bg-[#DADCE0]') + '"></span>' +
          '<div class="min-w-0">' +
          '<div class="font-bold text-[#1F1F1F] truncate">' + escapeHtml(u.full_name) + '</div>' +
          '<div class="text-[10px] text-[#5F6368] truncate">' + escapeHtml(u.unit) + '</div>' +
          '</div>' +
          '</div>' +
          '<span class="px-2 py-0.5 rounded-full bg-[#EAF1FB] text-[#0B57D0] text-[10px] font-bold shrink-0">محادثة</span>';
        listEl.appendChild(btn);
      }
    });
  };

  function renderActiveThreadHeader() {
    var conv = (chatState.conversations || []).find(function (c) { return c.id === activeChatConvId; });
    if (!conv) return;
    var hdrTitle = document.getElementById('chat-header-title');
    var hdrSub = document.getElementById('chat-header-sub');
    var membersBar = document.getElementById('chat-thread-members-bar');
    if (hdrTitle) hdrTitle.textContent = conv.display_title;
    if (hdrSub) {
      if (conv.type === 'group') {
        hdrSub.textContent = (conv.member_names || []).length + ' أعضاء في المجموعة';
      } else {
        var isOnline = conv.peer_id && (chatState.online_user_ids || []).indexOf(conv.peer_id) !== -1;
        hdrSub.textContent = isOnline ? 'متصل الآن' : 'غير متصل حالياً';
      }
    }
    if (membersBar) {
      if (conv.type === 'group' && conv.member_names && conv.member_names.length) {
        membersBar.textContent = 'الأعضاء: ' + conv.member_names.join('، ');
        membersBar.classList.remove('hidden');
      } else {
        membersBar.classList.add('hidden');
      }
    }
  }

  function renderChatMessages() {
    var box = document.getElementById('chat-messages-list');
    if (!box) return;
    var conv = (chatState.conversations || []).find(function (c) { return c.id === activeChatConvId; });
    var msgs = (chatState.messages || []).filter(function (m) { return m.conversation_id === activeChatConvId; });

    box.innerHTML = '';
    if (!msgs.length) {
      var empty = document.createElement('div');
      empty.className = 'py-8 text-center text-xs text-[#5F6368]';
      empty.textContent = 'ابدأ المحادثة بإرسال رسالة أو إرفاق مستند.';
      box.appendChild(empty);
      return;
    }

    msgs.forEach(function (m) {
      var isMine = m.sender_id === chatState.current_user_id;
      var wrap = document.createElement('div');
      wrap.className = 'flex flex-col ' + (isMine ? 'items-start' : 'items-end');

      var bubble = document.createElement('div');
      bubble.className =
        'max-w-[78%] rounded-2xl px-3 py-2 text-xs space-y-1.5 shadow-sm ' +
        (isMine
          ? 'bg-[#D3E3FD] text-[#001D35] rounded-tr-sm'
          : 'bg-white border border-[#E1E3E1] text-[#1F1F1F] rounded-tl-sm');

      if (!isMine && conv && conv.type === 'group') {
        var senderDiv = document.createElement('div');
        senderDiv.className = 'text-[10px] font-bold text-[#0B57D0]';
        senderDiv.textContent = m.sender_name || m.sender_username;
        bubble.appendChild(senderDiv);
      }

      if (m.text) {
        var textDiv = document.createElement('div');
        textDiv.className = 'whitespace-pre-wrap leading-relaxed';
        textDiv.textContent = m.text;
        bubble.appendChild(textDiv);
      }

      if (m.attachment) {
        var att = m.attachment;
        var attCard = document.createElement('div');
        attCard.className = 'flex items-center justify-between gap-2 p-2 rounded-xl bg-white/90 border border-[#C2E7FF] text-[11px]';

        var prevBtn = document.createElement('button');
        prevBtn.type = 'button';
        prevBtn.className = 'text-right min-w-0 flex-1 font-bold text-[#0B57D0] hover:underline truncate';
        prevBtn.textContent = '📎 ' + att.name;
        prevBtn.onclick = function () {
          window.openInlineAttachmentPreview(m.id, att.name, att.preview_kind, att.preview_url, att.download_url, att.raw_url || att.preview_url);
        };

        var dlA = document.createElement('a');
        dlA.href = att.download_url;
        dlA.className = 'px-1.5 py-0.5 rounded-full bg-[#EAF1FB] text-[#0B57D0] font-bold shrink-0';
        dlA.textContent = '⬇';
        dlA.title = 'تنزيل المرفق';

        attCard.appendChild(prevBtn);
        attCard.appendChild(dlA);
        bubble.appendChild(attCard);
      }

      var timeDiv = document.createElement('div');
      timeDiv.className = 'text-[10px] text-[#5F6368] mono-num ' + (isMine ? 'text-left' : 'text-right');
      timeDiv.textContent = m.time_short || m.created_at;
      bubble.appendChild(timeDiv);

      wrap.appendChild(bubble);
      box.appendChild(wrap);
    });

    box.scrollTop = box.scrollHeight;
  }

  window.openChatConversation = function (convId) {
    activeChatConvId = convId;
    window.switchChatView('thread');
    fetch('/chat/read/', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({ conversation_id: convId })
    })
      .then(function () {
        loadChatState(true);
      })
      .catch(function () {});
  };

  window.createDirectChat = function (userId) {
    showChatError('');
    fetch('/chat/direct/', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({ target_user_id: userId })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok) {
          showChatError(res.data.error || 'تعذر فتح المحادثة.');
          return;
        }
        var convId = res.data.conversation.id;
        fetch('/chat/state/', { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (st) {
            chatState = st;
            updateChatBadge(st.total_unread);
            window.openChatConversation(convId);
          });
      })
      .catch(function () {
        showChatError('تعذر الاتصال بخادم المحادثة.');
      });
  };

  window.createGroupChat = function () {
    showChatError('');
    var nameEl = document.getElementById('chat-group-name');
    var groupName = nameEl ? nameEl.value.trim() : '';
    if (!groupName) {
      showChatError('يرجى إدخال اسم المجموعة.');
      return;
    }
    var memberIds = Object.keys(chatGroupSelectedIds).map(function (k) { return Number(k); });
    fetch('/chat/groups/', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({ name: groupName, member_ids: memberIds })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok) {
          showChatError(res.data.error || 'تعذر إنشاء المجموعة.');
          return;
        }
        if (nameEl) nameEl.value = '';
        chatGroupSelectedIds = {};
        var cntEl = document.getElementById('chat-group-selected-count');
        if (cntEl) cntEl.textContent = '0 أعضاء محددون';
        var convId = res.data.conversation.id;
        fetch('/chat/state/', { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (st) {
            chatState = st;
            updateChatBadge(st.total_unread);
            window.openChatConversation(convId);
            if (chatChannel) chatChannel.postMessage({ type: 'group_created', id: convId });
          });
      })
      .catch(function () {
        showChatError('تعذر الاتصال بخادم المحادثة.');
      });
  };

  window.handleChatFilePicked = function (input) {
    var bar = document.getElementById('chat-draft-att-bar');
    var nameEl = document.getElementById('chat-draft-att-name');
    if (!input || !input.files || !input.files[0]) {
      window.clearDraftChatAttachment();
      return;
    }
    chatDraftFile = input.files[0];
    if (nameEl) nameEl.textContent = '📎 ' + chatDraftFile.name + ' (' + formatBytes(chatDraftFile.size) + ')';
    if (bar) bar.classList.remove('hidden');
  };

  window.previewDraftChatAttachment = function () {
    if (chatDraftFile) previewLocalFileObject(chatDraftFile);
  };

  window.clearDraftChatAttachment = function () {
    chatDraftFile = null;
    if (chatDraftObjUrl) {
      URL.revokeObjectURL(chatDraftObjUrl);
      chatDraftObjUrl = null;
    }
    var inp = document.getElementById('chat-file-input');
    var bar = document.getElementById('chat-draft-att-bar');
    if (inp) inp.value = '';
    if (bar) bar.classList.add('hidden');
  };

  window.sendChatMessage = function () {
    if (!activeChatConvId) return;
    showChatError('');
    var textEl = document.getElementById('chat-message-input');
    var text = textEl ? textEl.value.trim() : '';
    if (!text && !chatDraftFile) {
      showChatError('اكتب رسالة أو اختر مرفقاً للإرسال.');
      return;
    }

    var fd = new FormData();
    fd.append('conversation_id', String(activeChatConvId));
    fd.append('text', text);
    if (chatDraftFile) fd.append('attachment', chatDraftFile);

    fetch('/chat/messages/', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': getCsrfToken() },
      body: fd
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok) {
          showChatError(res.data.error || 'تعذر إرسال الرسالة.');
          return;
        }
        if (textEl) textEl.value = '';
        window.clearDraftChatAttachment();
        loadChatState(true);
        if (chatChannel) chatChannel.postMessage({ type: 'message_sent', conv_id: activeChatConvId });
      })
      .catch(function () {
        showChatError('فشل إرسال الرسالة، يرجى المحاولة مرة أخرى.');
      });
  };

  /* =========================================================================
     Interactive RTL Org Tree Engine for organization/org_tree.html
     ========================================================================= */
  window.initInteractiveOrgTree = function (unitsData, addUserBaseUrl, canManage) {
    var container = document.getElementById('interactive-org-tree-body');
    var panel = document.getElementById('org-tree-panel');
    var statusEl = document.getElementById('org-tree-dnd-status');
    var payloadInput = Array.isArray(unitsData)
      ? { holding: { code: 'EEHC', name: 'الشركة القابضة لكهرباء مصر' }, companies: [], units: unitsData }
      : (unitsData || {});
    var units = Array.isArray(payloadInput.units) ? payloadInput.units : [];
    var companies = Array.isArray(payloadInput.companies) ? payloadInput.companies : [];
    var holding = payloadInput.holding || { code: 'EEHC', name: 'الشركة القابضة لكهرباء مصر' };

    if (!container || !units.length) return;

    var moveUnitUrl = panel ? panel.getAttribute('data-move-unit-url') : '';
    var moveUserUrl = panel ? panel.getAttribute('data-move-user-url') : '';
    var searchInput = document.getElementById('org-tree-search');
    var expandAllBtn = document.getElementById('org-tree-expand-all');
    var collapseAllBtn = document.getElementById('org-tree-collapse-all');

    var byId = {};
    var childrenMap = {};
    var expanded = { EEHC_UMBRELLA: true };
    var dragState = null;

    function showDndStatus(msg, isError) {
      if (!statusEl) return;
      statusEl.innerHTML = '<span>' + escapeHtml(msg) + '</span>';
      statusEl.className = isError
        ? 'px-4 py-2 bg-[#FCE8E6] border-b border-[#F6AEA9] text-[11px] font-bold text-[#A50E0E]'
        : 'px-4 py-2 bg-[#E6F4EA] border-b border-[#CEEAD6] text-[11px] font-bold text-[#137333]';
    }

    function rebuildIndex() {
      byId = {};
      childrenMap = {};
      units.forEach(function (u) {
        byId[u.id] = u;
        childrenMap[u.id] = [];
        if (u.level === 'L1' || u.level === 'L2' || u.level === 'L3') {
          if (expanded[u.id] === undefined) expanded[u.id] = true;
        }
      });
      companies.forEach(function (c) {
        expanded['COMP_' + c.code] = true;
      });
      units.forEach(function (u) {
        if (u.parent_id && byId[u.parent_id] && u.parent_id !== u.id) {
          childrenMap[u.parent_id].push(u);
        }
      });
    }
    rebuildIndex();

    function isDescendant(ancestorId, targetId) {
      var queue = [ancestorId];
      var visited = {};
      while (queue.length) {
        var cur = queue.shift();
        if (visited[cur]) continue;
        visited[cur] = true;
        var kids = childrenMap[cur] || [];
        for (var i = 0; i < kids.length; i++) {
          if (kids[i].id === targetId) return true;
          queue.push(kids[i].id);
        }
      }
      return false;
    }

    function matchesQuery(u, q) {
      if (!q) return true;
      var hay = ((u.name || '') + ' ' + (u.code || '') + ' ' + (u.sector_name || '') + ' ' + (u.unit_type || '') + ' ' + (u.level || '')).toLowerCase();
      if (hay.indexOf(q) !== -1) return true;
      var uUsers = u.users || [];
      for (var i = 0; i < uUsers.length; i++) {
        var uh = ((uUsers[i].full_name || '') + ' ' + (uUsers[i].username || '') + ' ' + (uUsers[i].job_title || '')).toLowerCase();
        if (uh.indexOf(q) !== -1) return true;
      }
      return (childrenMap[u.id] || []).some(function (ch) { return matchesQuery(ch, q); });
    }

    function prefillCreateUnit(parentUnit) {
      var unitForm = document.getElementById('create-unit-form');
      if (!unitForm) return;
      var parentSel = unitForm.querySelector('[name="parent_id"]');
      var secSel = unitForm.querySelector('[name="sector_id"]');
      if (parentSel) parentSel.value = String(parentUnit.id);
      if (secSel && parentUnit.sector_id) secSel.value = String(parentUnit.sector_id);
      unitForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
      var nameInput = unitForm.querySelector('[name="name"]');
      if (nameInput) nameInput.focus();
    }

    function postDnd(url, bodyObj, onSuccess) {
      if (!url) return;
      fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify(bodyObj)
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (res) {
          if (!res.ok || !res.data.ok) {
            showDndStatus(res.data.error || 'تعذر تنفيذ النقل داخل الشجرة.', true);
            return;
          }
          onSuccess(res.data);
          showDndStatus(res.data.message || 'تم النقل وتحديث الهيكل بنجاح.', false);
          render();
        })
        .catch(function () {
          showDndStatus('تعذر الاتصال بالخادم لتنفيذ عملية النقل.', true);
        });
    }

    function performMoveUnit(unitId, newParentId) {
      if (!unitId || !newParentId || unitId === newParentId) return;
      var unitObj = byId[unitId];
      var parentObj = byId[newParentId];
      if (!unitObj || !parentObj) return;
      if (unitObj.level === 'L1' || !unitObj.parent_id) {
        showDndStatus('لا يمكن نقل قمة الهيكل التنظيمي (L1).', true);
        return;
      }
      if (isDescendant(unitId, newParentId)) {
        showDndStatus('لا يمكن نقل وحدة تنظيمية إلى إحدى الوحدات الفرعية التابعة لها.', true);
        return;
      }
      postDnd(moveUnitUrl, { unit_id: unitId, new_parent_id: newParentId }, function () {
        unitObj.parent_id = parentObj.id;
        unitObj.parent_code = parentObj.code;
        unitObj.sector_id = parentObj.sector_id;
        unitObj.sector_name = parentObj.sector_name;
        expanded[parentObj.id] = true;
        rebuildIndex();
      });
    }

    function performMoveUser(employeeId, fromUnitId, targetUnitId) {
      if (!employeeId || !targetUnitId || fromUnitId === targetUnitId) return;
      var fromUnit = byId[fromUnitId];
      var targetUnit = byId[targetUnitId];
      if (!fromUnit || !targetUnit) return;
      postDnd(moveUserUrl, { employee_id: employeeId, target_unit_id: targetUnitId }, function () {
        var fromUsers = fromUnit.users || [];
        var moved = null;
        fromUnit.users = fromUsers.filter(function (usr) {
          if (usr.employee_id === employeeId) {
            moved = usr;
            return false;
          }
          return true;
        });
        fromUnit.users_count = fromUnit.users.length;
        if (moved) {
          targetUnit.users = targetUnit.users || [];
          targetUnit.users.push(moved);
          targetUnit.users_count = targetUnit.users.length;
        }
        expanded[targetUnit.id] = true;
      });
    }

    function renderUnitNode(u, depth, q) {
      if (!matchesQuery(u, q)) return null;
      var kids = (childrenMap[u.id] || []).filter(function (c) { return matchesQuery(c, q); });
      var unitUsers = (u.users || []).filter(function (usr) {
        if (!q) return true;
        var uh = ((usr.full_name || '') + ' ' + (usr.username || '') + ' ' + (usr.job_title || '') + ' ' + (u.name || '')).toLowerCase();
        return uh.indexOf(q) !== -1;
      });
      var hasKids = kids.length > 0 || unitUsers.length > 0;
      var isExp = q ? true : Boolean(expanded[u.id]);

      var wrapper = document.createElement('div');
      var row = document.createElement('div');
      row.className = 'gm-tree-row gap-2 text-xs';
      row.style.paddingRight = (depth * 24 + 8) + 'px';

      if (canManage && u.level !== 'L1' && u.parent_id) {
        row.draggable = true;
        row.addEventListener('dragstart', function (e) {
          e.stopPropagation();
          dragState = { kind: 'unit', unitId: u.id };
          row.classList.add('is-dragging');
          if (e.dataTransfer) {
            e.dataTransfer.setData('text/plain', 'unit:' + u.id);
            e.dataTransfer.effectAllowed = 'move';
          }
        });
        row.addEventListener('dragend', function () {
          dragState = null;
          row.classList.remove('is-dragging');
          container.querySelectorAll('.is-drop-target').forEach(function (el) {
            el.classList.remove('is-drop-target');
          });
        });
      }

      if (canManage) {
        row.addEventListener('dragover', function (e) {
          if (!dragState) return;
          if (dragState.kind === 'unit' && dragState.unitId === u.id) return;
          e.preventDefault();
          e.stopPropagation();
          row.classList.add('is-drop-target');
        });
        row.addEventListener('dragleave', function () {
          row.classList.remove('is-drop-target');
        });
        row.addEventListener('drop', function (e) {
          e.preventDefault();
          e.stopPropagation();
          row.classList.remove('is-drop-target');
          var st = dragState;
          if (!st && e.dataTransfer) {
            var raw = e.dataTransfer.getData('text/plain') || '';
            if (raw.indexOf('user:') === 0) {
              var parts = raw.slice(5).split(':');
              st = { kind: 'user', employeeId: Number(parts[0]), fromUnitId: Number(parts[1]) };
            } else if (raw.indexOf('unit:') === 0) {
              st = { kind: 'unit', unitId: Number(raw.slice(5)) };
            }
          }
          dragState = null;
          if (!st) return;
          if (st.kind === 'unit') {
            performMoveUnit(st.unitId, u.id);
          } else if (st.kind === 'user') {
            performMoveUser(st.employeeId, st.fromUnitId, u.id);
          }
        });
      }

      if (hasKids) {
        var toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.className = 'gm-tree-toggle';
        toggleBtn.textContent = isExp ? '−' : '+';
        toggleBtn.title = isExp ? 'إغلاق المجموعة' : 'فتح المجموعة';
        toggleBtn.onclick = function () {
          expanded[u.id] = !expanded[u.id];
          render();
        };
        row.appendChild(toggleBtn);
      } else {
        var dot = document.createElement('span');
        dot.className = 'inline-flex items-center justify-center shrink-0';
        dot.style.width = '20px';
        dot.innerHTML = '<span style="width:6px;height:6px;border-radius:999px;background:#DADCE0;display:inline-block;"></span>';
        row.appendChild(dot);
      }

      if (canManage && u.level !== 'L1' && u.parent_id) {
        var grip = document.createElement('span');
        grip.className = 'text-[#747775] px-0.5 cursor-grab shrink-0';
        grip.title = 'اسحب وأفلت لتغيير التبعية';
        grip.textContent = '⋮⋮';
        row.appendChild(grip);
      }

      var titleSpan = document.createElement('span');
      titleSpan.className = (depth <= 2 ? 'font-bold text-[#202124]' : 'font-medium text-[#3C4043]') + ' truncate text-[13px]';
      titleSpan.textContent = u.name;
      row.appendChild(titleSpan);

      var lvlBadge = document.createElement('span');
      lvlBadge.className = 'px-2 py-0.5 rounded-full bg-[#E8F0FE] text-[#1A73E8] text-[11px] font-mono shrink-0';
      lvlBadge.textContent = u.level || u.code;
      row.appendChild(lvlBadge);

      var typeBadge = document.createElement('span');
      typeBadge.className = 'px-2 py-0.5 rounded-full bg-[#F1F3F4] text-[#5F6368] text-[10px] shrink-0';
      typeBadge.textContent = u.unit_type || u.unit_type_name || '';
      row.appendChild(typeBadge);

      var empBadge = document.createElement('span');
      empBadge.className = 'text-[11px] text-[#5F6368] mono-num shrink-0';
      empBadge.textContent = '(' + (unitUsers.length || u.users_count || 0) + ')';
      row.appendChild(empBadge);

      if (canManage) {
        var actions = document.createElement('div');
        actions.className = 'mr-auto flex items-center gap-1.5 shrink-0';

        if (addUserBaseUrl) {
          var addUserLink = document.createElement('a');
          addUserLink.href = addUserBaseUrl + '?unit_id=' + encodeURIComponent(u.id) + '&sector_id=' + encodeURIComponent(u.sector_id || '');
          addUserLink.className = 'px-2.5 py-0.5 rounded-[20px] bg-[#E6F4EA] hover:bg-[#CEEAD6] text-[#137333] text-[11px] font-bold';
          addUserLink.textContent = '+ مستخدم';
          actions.appendChild(addUserLink);
        }

        var addSubBtn = document.createElement('button');
        addSubBtn.type = 'button';
        addSubBtn.className = 'px-2.5 py-0.5 rounded-[20px] bg-[#E8F0FE] hover:bg-[#D3E3FD] text-[#1A73E8] text-[11px] font-bold';
        addSubBtn.textContent = '+ وحدة فرعية';
        addSubBtn.onclick = function () { prefillCreateUnit(u); };
        actions.appendChild(addSubBtn);

        row.appendChild(actions);
      }

      wrapper.appendChild(row);

      if (hasKids && isExp) {
        if (unitUsers.length > 0) {
          var usersWrap = document.createElement('div');
          usersWrap.className = 'flex flex-wrap items-center gap-1.5 py-1.5';
          usersWrap.style.paddingRight = ((depth + 1) * 24 + 28) + 'px';
          unitUsers.forEach(function (usr) {
            var chip = document.createElement('div');
            chip.className = 'gm-tree-user-chip';
            chip.title = (usr.full_name || '') + (usr.job_title ? ' — ' + usr.job_title : '') + ' (اسحب للنقل إلى وحدة أخرى)';
            if (canManage) {
              chip.draggable = true;
              chip.addEventListener('dragstart', function (e) {
                e.stopPropagation();
                dragState = { kind: 'user', employeeId: usr.employee_id, fromUnitId: u.id };
                chip.classList.add('is-dragging');
                if (e.dataTransfer) {
                  e.dataTransfer.setData('text/plain', 'user:' + usr.employee_id + ':' + u.id);
                  e.dataTransfer.effectAllowed = 'move';
                }
              });
              chip.addEventListener('dragend', function () {
                dragState = null;
                chip.classList.remove('is-dragging');
                container.querySelectorAll('.is-drop-target').forEach(function (el) {
                  el.classList.remove('is-drop-target');
                });
              });
            }
            var initial = (usr.full_name || usr.username || 'م').slice(0, 1);
            chip.innerHTML =
              (canManage ? '<span class="text-[#5F6368]">⋮⋮</span>' : '') +
              '<span style="width:16px;height:16px;border-radius:999px;background:#1A73E8;color:#fff;font-size:9px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;">' + escapeHtml(initial) + '</span>' +
              '<span class="font-bold">' + escapeHtml(usr.full_name || usr.username) + '</span>' +
              (usr.job_title ? '<span class="text-[#5F6368]">· ' + escapeHtml(usr.job_title) + '</span>' : '');
            usersWrap.appendChild(chip);
          });
          wrapper.appendChild(usersWrap);
        }

        kids.forEach(function (child) {
          var childEl = renderUnitNode(child, depth + 1, q);
          if (childEl) wrapper.appendChild(childEl);
        });
      }
      return wrapper;
    }

    function render() {
      var q = searchInput ? (searchInput.value || '').trim().toLowerCase() : '';
      container.innerHTML = '';

      // 1. عقدة الشركة القابضة الموحدة (EEHC)
      var eehcHeader = document.createElement('div');
      eehcHeader.className = 'gm-tree-row gap-2 text-xs bg-[#E8F0FE] border border-[#D3E3FD] rounded-[12px] mb-1';
      eehcHeader.style.paddingRight = '10px';
      var eehcToggle = document.createElement('button');
      eehcToggle.type = 'button';
      eehcToggle.className = 'gm-tree-toggle';
      eehcToggle.textContent = expanded.EEHC_UMBRELLA !== false ? '−' : '+';
      eehcToggle.onclick = function () {
        expanded.EEHC_UMBRELLA = expanded.EEHC_UMBRELLA === false;
        render();
      };
      eehcHeader.appendChild(eehcToggle);
      var eehcTitle = document.createElement('span');
      eehcTitle.className = 'font-bold text-[13px] text-[#202124]';
      eehcTitle.textContent = '⚡ ' + holding.name + ' (' + holding.code + ')';
      eehcHeader.appendChild(eehcTitle);
      var eehcBadge = document.createElement('span');
      eehcBadge.className = 'px-2 py-0.5 rounded-full bg-[#1A73E8] text-white text-[10px] font-bold';
      eehcBadge.textContent = 'المظلة القابضة';
      eehcHeader.appendChild(eehcBadge);
      container.appendChild(eehcHeader);

      if (expanded.EEHC_UMBRELLA === false && !q) return;

      // 2. الشركات التابعة الموازية تحت القابضة
      var companyGroups = companies.length ? companies : [{ code: 'WDEPCO', name: 'شركة غرب الدلتا لإنتاج الكهرباء' }];
      var renderedAny = false;
      companyGroups.forEach(function (comp) {
        var compUnits = units.filter(function (u) {
          var belongsComp = (u.company_code || 'WDEPCO') === comp.code;
          var isRootUnit = !u.parent_id || !byId[u.parent_id];
          return belongsComp && isRootUnit;
        });
        var visibleRoots = compUnits.filter(function (ru) { return matchesQuery(ru, q); });
        if (q && !visibleRoots.length && (comp.name || '').toLowerCase().indexOf(q) === -1) return;

        renderedAny = true;
        var compKey = 'COMP_' + comp.code;
        var compExpanded = q ? true : expanded[compKey] !== false;

        var compRow = document.createElement('div');
        compRow.className = 'gm-tree-row gap-2 text-xs bg-[#F8F9FA] border border-[#ECEFF1] rounded-[12px] my-1';
        compRow.style.paddingRight = '32px';

        var compBtn = document.createElement('button');
        compBtn.type = 'button';
        compBtn.className = 'gm-tree-toggle';
        compBtn.textContent = compExpanded ? '−' : '+';
        compBtn.onclick = function () {
          expanded[compKey] = !compExpanded;
          render();
        };
        compRow.appendChild(compBtn);

        var compName = document.createElement('span');
        compName.className = 'font-bold text-[13px] text-[#202124]';
        compName.textContent = '🏢 ' + comp.name + ' (' + comp.code + ')';
        compRow.appendChild(compName);

        var compTag = document.createElement('span');
        compTag.className = 'px-2 py-0.5 rounded-full bg-white border border-[#DADCE0] text-[#1A73E8] text-[10px] font-bold';
        compTag.textContent = 'شركة تابعة';
        compRow.appendChild(compTag);

        container.appendChild(compRow);

        if (compExpanded) {
          visibleRoots.forEach(function (ru) {
            var el = renderUnitNode(ru, 2, q);
            if (el) container.appendChild(el);
          });
        }
      });

      if (!renderedAny) {
        var empty = document.createElement('div');
        empty.className = 'py-8 text-center text-xs text-[#5F6368]';
        empty.textContent = 'لا توجد وحدات أو مستخدمون مطابقون لعبارة البحث.';
        container.appendChild(empty);
      }
    }

    if (searchInput) searchInput.addEventListener('input', render);
    if (expandAllBtn) {
      expandAllBtn.onclick = function () {
        expanded.EEHC_UMBRELLA = true;
        companies.forEach(function (c) { expanded['COMP_' + c.code] = true; });
        units.forEach(function (u) { expanded[u.id] = true; });
        render();
      };
    }
    if (collapseAllBtn) {
      collapseAllBtn.onclick = function () {
        expanded = { EEHC_UMBRELLA: true };
        companies.forEach(function (c) { expanded['COMP_' + c.code] = true; });
        render();
      };
    }
    render();
  };

  /* Prefill #create-user-form when redirected from Org Tree (+ إضافة مستخدم) */
  function initUsersQueryPrefill() {
    var form = document.getElementById('create-user-form');
    if (!form || !window.URLSearchParams) return;
    var params = new URLSearchParams(window.location.search);
    var unitId = params.get('unit_id');
    var sectorId = params.get('sector_id');
    if (!unitId && !sectorId) return;
    if (unitId) {
      var unitSel = form.querySelector('[name="org_unit_id"]');
      if (unitSel) unitSel.value = unitId;
    }
    if (sectorId) {
      var secSel = form.querySelector('[name="sector_id"]');
      if (secSel) secSel.value = sectorId;
    }
    form.scrollIntoView({ behavior: 'smooth', block: 'center' });
    form.style.boxShadow = '0 0 0 3px rgba(11, 87, 208, 0.25)';
    var fullNameInput = form.querySelector('[name="full_name"]');
    if (fullNameInput) fullNameInput.focus();
  }

  /* =========================================================================
     Universal Print (Hidden Iframe) & Institutional RTL PDF Export
     ========================================================================= */
  window.printHtmlInHiddenIframe = function (title, bodyHtml) {
    var iframe = document.createElement('iframe');
    iframe.style.position = 'fixed';
    iframe.style.left = '-9999px';
    iframe.style.top = '0';
    iframe.style.width = '1px';
    iframe.style.height = '1px';
    iframe.style.border = '0';
    iframe.style.opacity = '0';

    var html = '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">' +
      '<title>' + escapeHtml(title || 'طباعة مستند') + '</title>' +
      '<style>@page{size:A4;margin:16mm;}body{font-family:"IBM Plex Sans Arabic","Cairo","Segoe UI",Tahoma,Arial,sans-serif;color:#1F1F1F;direction:rtl;margin:0;padding:0;font-size:13px;line-height:1.75;}' +
      '.inst-hdr{border-bottom:2px solid #0B57D0;padding-bottom:10px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:flex-end;}' +
      '.inst-co{font-size:15px;font-weight:700;color:#0B57D0;}.inst-sub{font-size:11px;color:#5F6368;}' +
      'table{width:100%;border-collapse:collapse;margin:10px 0;font-size:12px;}th,td{border:1px solid #DADCE0;padding:6px 8px;text-align:right;vertical-align:top;}th{background:#F2F6FC;font-weight:700;}' +
      'pre{white-space:pre-wrap;word-break:break-word;font-family:monospace;background:#F6F8FC;padding:12px;border:1px solid #ECEFF1;border-radius:8px;}' +
      'img{max-width:100%;height:auto;display:block;margin:10px auto;border:1px solid #ECEFF1;}</style></head><body>' +
      '<div class="inst-hdr"><div><div class="inst-co">الشركة القابضة لكهرباء مصر — شركة غرب الدلتا لإنتاج الكهرباء</div>' +
      '<div class="inst-sub">نموذج طباعة معتمد — منظومة المراسلات والقرارات الإدارية</div></div>' +
      '<div class="inst-sub">' + escapeHtml(new Date().toLocaleDateString('ar-EG')) + '</div></div>' +
      (bodyHtml || '') + '</body></html>';

    document.body.appendChild(iframe);
    var cleanup = function () {
      setTimeout(function () {
        if (iframe.parentNode) iframe.parentNode.removeChild(iframe);
      }, 1500);
    };
    iframe.onload = function () {
      try {
        iframe.contentWindow.focus();
        iframe.contentWindow.print();
      } catch (_) {}
      cleanup();
    };
    iframe.srcdoc = html;
  };

  window.printCurrentPreviewAttachment = function () {
    var st = currentPreviewState || {};
    if (st.kind === 'pdf' && st.previewUrl) {
      var frame = document.getElementById('inline-preview-frame');
      try {
        if (frame && frame.contentWindow) {
          frame.contentWindow.focus();
          frame.contentWindow.print();
          return;
        }
      } catch (_) {}
    }
    if (st.kind === 'image' && st.previewUrl) {
      window.printHtmlInHiddenIframe(st.name, '<h3>' + escapeHtml(st.name) + '</h3><img src="' + escapeHtml(st.previewUrl) + '" alt="preview" />');
      return;
    }
    if (st.kind === 'office' && st.officeHtml) {
      window.printHtmlInHiddenIframe(st.name, '<h3>' + escapeHtml(st.name) + '</h3>' + st.officeHtml);
      return;
    }
    var csvWrap = document.getElementById('inline-preview-csv-wrap');
    if (st.kind === 'csv' && csvWrap && csvWrap.innerHTML) {
      window.printHtmlInHiddenIframe(st.name, '<h3>' + escapeHtml(st.name) + '</h3>' + csvWrap.innerHTML);
      return;
    }
    if (st.rawText) {
      window.printHtmlInHiddenIframe(st.name, '<h3>' + escapeHtml(st.name) + '</h3><pre>' + escapeHtml(st.rawText) + '</pre>');
      return;
    }
    window.printHtmlInHiddenIframe(
      st.name || 'بطاقة مرفق',
      '<h3>بطاقة توثيق وطباعة المرفق</h3>' +
      '<table><tr><th>اسم الملف</th><td>' + escapeHtml(st.name || '—') + '</td></tr>' +
      '<tr><th>النوع</th><td>' + escapeHtml((st.kind || 'FILE').toUpperCase()) + '</td></tr>' +
      '<tr><th>الحالة</th><td>مرفق موثق ومحفوظ ضمن سجل المنظومة</td></tr></table>'
    );
  };

  window.exportInstitutionalPdf = function (spec) {
    spec = spec || {};
    var pageW = 1240, pageH = 1754, marginX = 76;
    var contentW = pageW - marginX * 2;
    var topStart = 215, bottomLimit = pageH - 105;
    var canvases = [];

    function drawRoundRect(ctx, x, y, w, h, r) {
      ctx.beginPath();
      ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
      ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
      ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
      ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y); ctx.closePath();
    }

    function wrapText(ctx, text, maxW) {
      var raw = String(text == null ? '' : text).replace(/\r/g, '');
      if (!raw.trim()) return [];
      var paras = raw.split('\n');
      var lines = [];
      paras.forEach(function (para) {
        var trimmed = para.trim();
        if (!trimmed) { lines.push(''); return; }
        var words = trimmed.split(/\s+/);
        var cur = '';
        words.forEach(function (w) {
          var cand = cur ? (cur + ' ' + w) : w;
          if (ctx.measureText(cand).width <= maxW) { cur = cand; }
          else {
            if (cur) lines.push(cur);
            cur = w;
          }
        });
        if (cur) lines.push(cur);
      });
      return lines;
    }

    function newPage(idx) {
      var c = document.createElement('canvas');
      c.width = pageW; c.height = pageH;
      var cx = c.getContext('2d');
      cx.fillStyle = '#FFFFFF'; cx.fillRect(0, 0, pageW, pageH);
      cx.strokeStyle = '#DADCE0'; cx.lineWidth = 2; cx.strokeRect(36, 36, pageW - 72, pageH - 72);
      cx.fillStyle = '#F2F6FC'; drawRoundRect(cx, 56, 56, pageW - 112, 126, 14); cx.fill();
      cx.strokeStyle = '#D3E3FD'; cx.lineWidth = 2; cx.stroke();
      cx.direction = 'rtl'; cx.textAlign = 'right';
      cx.fillStyle = '#0B57D0'; cx.font = 'bold 21px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
      cx.fillText('الشركة القابضة لكهرباء مصر', pageW - marginX, 95);
      cx.fillStyle = '#1F1F1F'; cx.font = 'bold 24px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
      cx.fillText(spec.companyName || 'شركة غرب الدلتا لإنتاج الكهرباء', pageW - marginX, 132);
      cx.fillStyle = '#5F6368'; cx.font = '18px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
      cx.fillText('منظومة المراسلات والقرارات الإدارية والأرشفة المؤمّنة', pageW - marginX, 164);
      cx.textAlign = 'left'; cx.fillStyle = '#0B57D0'; cx.font = 'bold 18px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
      cx.fillText('التاريخ: ' + new Date().toLocaleDateString('ar-EG'), marginX, 100);
      cx.fillStyle = '#5F6368'; cx.font = '16px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
      cx.fillText(idx === 0 ? 'مستند مؤسسي معتمد للطباعة' : 'تابع المستند المؤسسي', marginX, 134);
      cx.textAlign = 'right';
      canvases.push(c);
      return cx;
    }

    var ctx = newPage(0);
    var y = topStart;
    function ensureSpace(h) {
      if (y + h > bottomLimit) { ctx = newPage(canvases.length); y = topStart; }
    }

    ctx.direction = 'rtl'; ctx.textAlign = 'right';
    ctx.fillStyle = '#1F1F1F'; ctx.font = 'bold 30px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
    wrapText(ctx, spec.title || 'مستند رسمي', contentW).forEach(function (ln) {
      ensureSpace(44); ctx.fillText(ln, pageW - marginX, y); y += 40;
    });
    if (spec.subtitle) {
      ctx.fillStyle = '#5F6368'; ctx.font = '20px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
      wrapText(ctx, spec.subtitle, contentW).forEach(function (ln) {
        ensureSpace(32); ctx.fillText(ln, pageW - marginX, y); y += 30;
      });
    }
    y += 12;

    if (Array.isArray(spec.metadata) && spec.metadata.length) {
      var colW = (contentW - 18) / 2, rowH = 54;
      for (var i = 0; i < spec.metadata.length; i += 2) {
        ensureSpace(rowH + 10);
        spec.metadata.slice(i, i + 2).forEach(function (pair, idx) {
          var bx = idx === 0 ? (pageW - marginX - colW) : marginX;
          ctx.fillStyle = '#F6F8FC'; drawRoundRect(ctx, bx, y, colW, rowH, 10); ctx.fill();
          ctx.strokeStyle = '#ECEFF1'; ctx.lineWidth = 1.5; ctx.stroke();
          ctx.textAlign = 'right'; ctx.fillStyle = '#5F6368'; ctx.font = 'bold 16px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
          ctx.fillText(pair[0] || '', bx + colW - 14, y + 21);
          ctx.fillStyle = '#1F1F1F'; ctx.font = '18px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
          var valLn = wrapText(ctx, pair[1] || '—', colW - 28)[0] || '—';
          ctx.fillText(valLn, bx + colW - 14, y + 45);
        });
        y += rowH + 10;
      }
      y += 14;
    }

    (spec.sections || []).forEach(function (sec) {
      ensureSpace(75);
      ctx.fillStyle = '#E8F0FE'; drawRoundRect(ctx, marginX, y, contentW, 42, 8); ctx.fill();
      ctx.fillStyle = '#0B57D0'; ctx.textAlign = 'right'; ctx.font = 'bold 22px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
      ctx.fillText(sec.heading || '', pageW - marginX - 16, y + 28);
      y += 58;
      (sec.paragraphs || []).forEach(function (p) {
        ctx.fillStyle = '#1F1F1F'; ctx.font = '19px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
        wrapText(ctx, p, contentW - 20).forEach(function (ln) {
          ensureSpace(32); ctx.fillText(ln, pageW - marginX - 8, y); y += 30;
        });
        y += 8;
      });
      if (sec.table && Array.isArray(sec.table.headers) && sec.table.headers.length) {
        var cols = sec.table.headers.length, cw = contentW / cols;
        ensureSpace(46);
        ctx.fillStyle = '#F2F6FC'; ctx.fillRect(marginX, y, contentW, 42);
        ctx.strokeStyle = '#DADCE0'; ctx.lineWidth = 1.5; ctx.strokeRect(marginX, y, contentW, 42);
        ctx.fillStyle = '#1F1F1F'; ctx.font = 'bold 17px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
        sec.table.headers.forEach(function (h, ci) {
          var rx = pageW - marginX - ci * cw - 10;
          ctx.fillText(wrapText(ctx, h, cw - 20)[0] || '', rx, y + 27);
        });
        y += 42;
        (sec.table.rows || []).forEach(function (row) {
          ensureSpace(42);
          ctx.strokeStyle = '#ECEFF1'; ctx.lineWidth = 1; ctx.strokeRect(marginX, y, contentW, 40);
          ctx.fillStyle = '#1F1F1F'; ctx.font = '16px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
          row.forEach(function (cell, ci) {
            var rx = pageW - marginX - ci * cw - 10;
            ctx.fillText(wrapText(ctx, cell || '—', cw - 20)[0] || '—', rx, y + 26);
          });
          y += 40;
        });
        y += 14;
      }
      y += 10;
    });

    var totalP = canvases.length;
    canvases.forEach(function (c, idx) {
      var cc = c.getContext('2d');
      cc.strokeStyle = '#ECEFF1'; cc.lineWidth = 1.5;
      cc.beginPath(); cc.moveTo(marginX, pageH - 76); cc.lineTo(pageW - marginX, pageH - 76); cc.stroke();
      cc.direction = 'rtl'; cc.fillStyle = '#5F6368'; cc.font = '16px "IBM Plex Sans Arabic", "Cairo", "Segoe UI", Tahoma, Arial, sans-serif';
      cc.textAlign = 'right'; cc.fillText('نسخة إلكترونية موثقة — نظام إدارة المراسلات والقرارات', pageW - marginX, pageH - 50);
      cc.textAlign = 'left'; cc.fillText('صفحة ' + (idx + 1) + ' من ' + totalP, marginX, pageH - 50);
    });

    var enc = new TextEncoder();
    var parts = [], off = 0, offsets = [0];
    function pushB(b) { parts.push(b); off += b.length; }
    function pushS(s) { pushB(enc.encode(s)); }
    pushS('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n');
    var kids = canvases.map(function (_, i) { return (3 + i * 3) + ' 0 R'; }).join(' ');
    offsets[1] = off; pushS('1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n');
    offsets[2] = off; pushS('2 0 obj\n<< /Type /Pages /Count ' + totalP + ' /Kids [' + kids + '] >>\nendobj\n');
    canvases.forEach(function (c, i) {
      var dUrl = c.toDataURL('image/jpeg', 0.92);
      var b64 = dUrl.slice(dUrl.indexOf(',') + 1);
      var bin = atob(b64), jb = new Uint8Array(bin.length);
      for (var k = 0; k < bin.length; k++) jb[k] = bin.charCodeAt(k);
      var pId = 3 + i * 3, cId = 4 + i * 3, imId = 5 + i * 3;
      offsets[pId] = off;
      pushS(pId + ' 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] /Resources << /XObject << /Im0 ' + imId + ' 0 R >> >> /Contents ' + cId + ' 0 R >>\nendobj\n');
      var cmd = 'q\n595.28 0 0 841.89 0 0 cm\n/Im0 Do\nQ\n';
      var cmdB = enc.encode(cmd);
      offsets[cId] = off;
      pushS(cId + ' 0 obj\n<< /Length ' + cmdB.length + ' >>\nstream\n'); pushB(cmdB); pushS('\nendstream\nendobj\n');
      offsets[imId] = off;
      pushS(imId + ' 0 obj\n<< /Type /XObject /Subtype /Image /Width ' + c.width + ' /Height ' + c.height + ' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ' + jb.length + ' >>\nstream\n');
      pushB(jb); pushS('\nendstream\nendobj\n');
    });
    var xref = off, nObj = offsets.length;
    pushS('xref\n0 ' + nObj + '\n0000000000 65535 f \n');
    for (var oi = 1; oi < nObj; oi++) pushS(String(offsets[oi]).padStart(10, '0') + ' 00000 n \n');
    pushS('trailer\n<< /Size ' + nObj + ' /Root 1 0 R >>\nstartxref\n' + xref + '\n%%EOF');
    var out = new Uint8Array(off), pos = 0;
    parts.forEach(function (ch) { out.set(ch, pos); pos += ch.length; });
    var blob = new Blob([out], { type: 'application/pdf' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (spec.filename || 'document').replace(/\.pdf$/i, '') + '.pdf';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  };

  window.toggleOverflowMenu = function (menuId) {
    var menu = document.getElementById(menuId);
    if (!menu) return;
    document.querySelectorAll('.gm-overflow-menu').forEach(function (el) {
      if (el.id !== menuId) el.classList.add('hidden');
    });
    menu.classList.toggle('hidden');
  };

  document.addEventListener('click', function (e) {
    if (!e.target.closest || !e.target.closest('.gm-overflow-wrap')) {
      document.querySelectorAll('.gm-overflow-menu').forEach(function (el) {
        el.classList.add('hidden');
      });
    }
    if (!e.target.closest || !e.target.closest('#rail-switcher-wrap')) {
      var pop = document.getElementById('rail-switcher-popover');
      if (pop) pop.classList.add('hidden');
    }
    if (!e.target.closest || !e.target.closest('#topbar-account-wrap')) {
      var accPop = document.getElementById('topbar-account-popover');
      if (accPop) accPop.classList.add('hidden');
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      closeInlineAttachmentPreview();
      document.querySelectorAll('.gm-overflow-menu').forEach(function (el) {
        el.classList.add('hidden');
      });
      var pop = document.getElementById('rail-switcher-popover');
      if (pop) pop.classList.add('hidden');
      var accPop = document.getElementById('topbar-account-popover');
      if (accPop) accPop.classList.add('hidden');
    }
  });

  /* =========================================================================
     Unified Gmail Material 3 Theme + Dark Mode Controller
     ========================================================================= */
  var MODE_KEY = 'correspondence_color_mode';

  function getSavedTheme() {
    return 'gmail';
  }
  function getSavedColorMode() {
    try { return localStorage.getItem(MODE_KEY) === 'dark' ? 'dark' : 'light'; } catch (_) { return 'light'; }
  }

  function syncThemeUI() {
    var mode = document.documentElement.getAttribute('data-mode') || getSavedColorMode();
    var sunIcon = document.getElementById('theme-icon-sun');
    var moonIcon = document.getElementById('theme-icon-moon');
    var modeBtn = document.getElementById('color-mode-toggle');
    if (sunIcon && moonIcon) {
      if (mode === 'dark') {
        sunIcon.classList.remove('hidden');
        moonIcon.classList.add('hidden');
      } else {
        sunIcon.classList.add('hidden');
        moonIcon.classList.remove('hidden');
      }
    }
    if (modeBtn) {
      modeBtn.setAttribute('data-tooltip', mode === 'dark' ? 'التبديل للوضع الفاتح' : 'التبديل للوضع الداكن');
    }
  }

  window.setAppTheme = function () {
    document.documentElement.setAttribute('data-theme', 'gmail');
    syncThemeUI();
  };

  window.setAppColorMode = function (mode) {
    var next = mode === 'dark' ? 'dark' : 'light';
    try { localStorage.setItem(MODE_KEY, next); } catch (_) {}
    document.documentElement.setAttribute('data-mode', next);
    document.documentElement.classList.toggle('dark', next === 'dark');
    syncThemeUI();
  };

  window.toggleAppColorMode = function () {
    var cur = document.documentElement.getAttribute('data-mode') === 'dark' ? 'dark' : 'light';
    window.setAppColorMode(cur === 'dark' ? 'light' : 'dark');
  };

  window.addEventListener('storage', function (e) {
    if (e.key === MODE_KEY) {
      document.documentElement.setAttribute('data-theme', 'gmail');
      var m = getSavedColorMode();
      document.documentElement.setAttribute('data-mode', m);
      document.documentElement.classList.toggle('dark', m === 'dark');
      syncThemeUI();
    }
  });

  document.addEventListener('DOMContentLoaded', function () {
    document.documentElement.setAttribute('data-theme', getSavedTheme());
    var m = getSavedColorMode();
    document.documentElement.setAttribute('data-mode', m);
    document.documentElement.classList.toggle('dark', m === 'dark');
    syncThemeUI();

    /* Keep desktop sidebar expanded by default for beginners unless user explicitly collapsed it */
    var sb = document.getElementById('gmail-sidebar');
    if (sb && window.innerWidth >= 768) {
      var pref = '1';
      try {
        var saved = localStorage.getItem('gmail_rail_expanded');
        if (saved === '0') pref = '0';
      } catch (_) {}
      if (pref === '1') sb.classList.add('is-expanded');
      else sb.classList.remove('is-expanded');
    }

    window.filterComposeUnitsBySector();
    window.toggleCustomMemoRecipient();
    initUsersQueryPrefill();

    var drawer = document.getElementById('gmail-utility-drawer');
    if (drawer) {
      setInterval(function () {
        if (document.hidden) return;
        if (activeUtilityTab === 'chat') {
          loadChatState(true);
        }
      }, 8000);
      setInterval(function () {
        if (document.hidden) return;
        loadChatState(false);
        if (activeUtilityTab === 'alerts') loadSmartNotificationsDrawer();
      }, 30000);
    }
  });
})();

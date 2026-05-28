/**
 * Albedo PWA — app.js
 * WebSocket relay client for iOS/web users.
 * Works in Safari (iOS 16+), Chrome, Firefox.
 */

'use strict';

// ── Storage ───────────────────────────────────────────────────────────────────
const LS = {
  get relayUrl() { return localStorage.getItem('relay_url') || ''; },
  get token()    { return localStorage.getItem('token')     || ''; },
  save(url, tok) {
    localStorage.setItem('relay_url', url);
    localStorage.setItem('token',     tok);
  },
  clear() {
    localStorage.removeItem('relay_url');
    localStorage.removeItem('token');
  },
};

// ── State ─────────────────────────────────────────────────────────────────────
let ws          = null;
let wsConnected = false;
let reconnTimer = null;
let pendingIds  = new Set();
let listening   = false;
let recognition = null;
let deferredInstall = null;

// ── Boot ──────────────────────────────────────────────────────────────────────
window.addEventListener('load', () => {
  if (LS.relayUrl && LS.token) {
    showChat();
    connect();
  } else {
    showSetup();
    startQrScanner();
  }
  registerSW();
});

// ── PWA install prompt ────────────────────────────────────────────────────────
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  deferredInstall = e;
  document.getElementById('installBanner').classList.add('show');
});

function installApp() {
  if (!deferredInstall) return;
  deferredInstall.prompt();
  deferredInstall.userChoice.then(() => {
    deferredInstall = null;
    document.getElementById('installBanner').classList.remove('show');
  });
}

// iOS "Add to Home Screen" hint (Safari doesn't fire beforeinstallprompt)
function checkIosInstall() {
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isStandalone = window.navigator.standalone;
  if (isIos && !isStandalone) {
    document.getElementById('installBanner').classList.add('show');
    document.querySelector('#installBanner span').textContent =
      'Tap Share → Add to Home Screen for the full app experience';
    document.querySelector('#installBanner button').style.display = 'none';
  }
}

// ── Service Worker ────────────────────────────────────────────────────────────
function registerSW() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
}

// ── View switching ────────────────────────────────────────────────────────────
function showSetup() {
  document.getElementById('setupView').classList.add('active');
  document.getElementById('chatView').classList.remove('active');
}

function showChat() {
  document.getElementById('setupView').classList.remove('active');
  document.getElementById('chatView').classList.add('active');
  checkIosInstall();
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(tab) {
  document.getElementById('tabQr').classList.toggle('active',     tab === 'qr');
  document.getElementById('tabManual').classList.toggle('active', tab === 'manual');
  document.getElementById('qrPane').classList.toggle('active',     tab === 'qr');
  document.getElementById('manualPane').classList.toggle('active', tab === 'manual');
  if (tab === 'qr') startQrScanner();
  else stopQrScanner();
}

// ── QR Scanner ────────────────────────────────────────────────────────────────
let qrStream   = null;
let qrAnimFrame = null;
let qrCanvas   = null;
let qrCtx      = null;
let jsQRScript = null;

function startQrScanner() {
  const errEl = document.getElementById('qrError');
  errEl.textContent = '';

  // Load jsQR on demand
  if (!window.jsQR) {
    if (!jsQRScript) {
      jsQRScript = document.createElement('script');
      jsQRScript.src = 'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js';
      jsQRScript.onload = () => startQrScanner();
      jsQRScript.onerror = () => {
        errEl.textContent = 'QR library failed to load. Use Manual Entry.';
      };
      document.head.appendChild(jsQRScript);
    }
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    errEl.textContent = 'Camera not available. Use Manual Entry.';
    return;
  }

  navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
    .then(stream => {
      qrStream = stream;
      const video = document.getElementById('qrVideo');
      video.srcObject = stream;
      video.play();
      qrCanvas = document.createElement('canvas');
      qrCtx    = qrCanvas.getContext('2d');
      qrAnimFrame = requestAnimationFrame(scanFrame);
    })
    .catch(err => {
      errEl.textContent = 'Camera access denied. Use Manual Entry.';
    });
}

function scanFrame() {
  const video = document.getElementById('qrVideo');
  if (!video || video.readyState !== video.HAVE_ENOUGH_DATA) {
    qrAnimFrame = requestAnimationFrame(scanFrame);
    return;
  }
  qrCanvas.width  = video.videoWidth;
  qrCanvas.height = video.videoHeight;
  qrCtx.drawImage(video, 0, 0);
  const img  = qrCtx.getImageData(0, 0, qrCanvas.width, qrCanvas.height);
  const code = window.jsQR(img.data, img.width, img.height, { inversionAttempts: 'dontInvert' });
  if (code && code.data.includes('|')) {
    stopQrScanner();
    parseAndSave(code.data);
    return;
  }
  qrAnimFrame = requestAnimationFrame(scanFrame);
}

function stopQrScanner() {
  if (qrAnimFrame) { cancelAnimationFrame(qrAnimFrame); qrAnimFrame = null; }
  if (qrStream) { qrStream.getTracks().forEach(t => t.stop()); qrStream = null; }
}

// ── Pairing ───────────────────────────────────────────────────────────────────
function parseAndSave(raw) {
  const parts = raw.split('|');
  if (parts.length < 2) {
    document.getElementById('qrError').textContent = 'Invalid QR format.';
    startQrScanner();
    return;
  }
  const url = parts[0].trim();
  const tok = parts[1].trim();
  if (!url || !tok) {
    document.getElementById('qrError').textContent = 'Empty relay URL or token.';
    startQrScanner();
    return;
  }
  LS.save(url, tok);
  showChat();
  connect();
}

function saveManual() {
  const url = document.getElementById('relayUrl').value.trim();
  const tok = document.getElementById('tokenInput').value.trim();
  const err = document.getElementById('manualErr');
  err.textContent = '';
  if (!url) { err.textContent = 'Relay URL is required.'; return; }
  if (!url.startsWith('wss://') && !url.startsWith('ws://')) {
    err.textContent = 'URL must start with wss:// or ws://'; return;
  }
  if (!tok || tok.length < 8) { err.textContent = 'Token is too short.'; return; }
  LS.save(url, tok);
  showChat();
  connect();
}

function unpair() {
  if (!confirm('Remove pairing? You will need to scan the QR code again.')) return;
  LS.clear();
  if (ws) { ws.close(); ws = null; }
  clearTimeout(reconnTimer);
  showSetup();
  startQrScanner();
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connect() {
  clearTimeout(reconnTimer);
  if (ws) { try { ws.close(); } catch {} }

  const wsUrl = `${LS.relayUrl}/phone/${LS.token}`;
  try {
    ws = new WebSocket(wsUrl);
  } catch {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    wsConnected = true;
    setStatus('wait');
  };

  ws.onmessage = e => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    handleMessage(msg);
  };

  ws.onerror  = () => {};
  ws.onclose  = () => {
    wsConnected = false;
    setStatus('off');
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  clearTimeout(reconnTimer);
  reconnTimer = setTimeout(connect, 5000);
}

function handleMessage(msg) {
  const type = msg.type || '';

  if (type === 'albedo_status') {
    setStatus(msg.online ? 'on' : 'wait');
    if (!msg.online) {
      document.getElementById('emptyHint').textContent = 'Waiting for Albedo desktop...';
    }
    return;
  }

  if (type === 'response') {
    pendingIds.delete(msg.id);
    if (pendingIds.size === 0) hideTyping();
    addMessage(msg.text || '', 'albedo');
    return;
  }

  if (type === 'push') {
    addMessage(msg.text || 'Alert from Albedo', 'albedo');
    pushNotification('Albedo', msg.text || 'Alert');
    return;
  }

  if (type === 'error') {
    pendingIds.delete(msg.id);
    if (pendingIds.size === 0) hideTyping();
    addMessage(msg.text || 'Error', 'sys');
  }
}

// ── Status ─────────────────────────────────────────────────────────────────────
function setStatus(state) {
  const el = document.getElementById('statusLabel');
  const hint = document.getElementById('emptyHint');
  if (state === 'on') {
    el.className = 'hdr-sub on';  el.textContent = '● ONLINE';
    hint.textContent = 'Send a message or speak.';
  } else if (state === 'wait') {
    el.className = 'hdr-sub wait'; el.textContent = '◌ RELAY CONNECTED';
    hint.textContent = 'Waiting for Albedo desktop...';
  } else {
    el.className = 'hdr-sub off';  el.textContent = '✕ DISCONNECTED';
    hint.textContent = 'Reconnecting...';
  }
}

// ── Messaging ─────────────────────────────────────────────────────────────────
function sendMessage() {
  const input = document.getElementById('msgInput');
  const text  = input.value.trim();
  if (!text || !wsConnected) return;

  addMessage(text, 'user');
  input.value = '';
  autoGrow(input);

  const id = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
  pendingIds.add(id);
  showTyping();

  try {
    ws.send(JSON.stringify({ type: 'query', text, id }));
  } catch {
    pendingIds.delete(id);
    hideTyping();
  }
}

function addMessage(text, sender) {
  const list = document.getElementById('msgList');
  const empty = document.getElementById('emptyState');
  if (empty) empty.style.display = 'none';

  const div = document.createElement('div');
  div.className = `msg ${sender}`;
  if (sender === 'albedo') {
    div.innerHTML = `<div class="sender">ALBEDO</div><div class="bubble">${escHtml(text)}</div>`;
  } else if (sender === 'sys') {
    div.innerHTML = `<div class="bubble">${escHtml(text)}</div>`;
  } else {
    div.innerHTML = `<div class="bubble">${escHtml(text)}</div>`;
  }
  list.appendChild(div);
  list.scrollTop = list.scrollHeight;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
           .replace(/\n/g,'<br>');
}

function showTyping() { document.getElementById('typingBar').classList.add('show'); }
function hideTyping()  { document.getElementById('typingBar').classList.remove('show'); }

// ── Input helpers ─────────────────────────────────────────────────────────────
function autoGrow(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  document.getElementById('sendBtn').disabled = el.value.trim() === '';
}

function onInputKey(e) {
  // Send on Enter (not Shift+Enter) on desktop
  if (e.key === 'Enter' && !e.shiftKey && window.innerWidth > 600) {
    e.preventDefault();
    sendMessage();
  }
}

// ── Speech (STT) ──────────────────────────────────────────────────────────────
function toggleMic() {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) { alert('Speech recognition not supported in this browser.'); return; }

  if (listening) {
    recognition && recognition.stop();
    setMicOff();
    return;
  }

  recognition = new SpeechRec();
  recognition.continuous    = false;
  recognition.interimResults = false;
  recognition.lang          = 'en-US';

  recognition.onstart  = () => setMicOn();
  recognition.onend    = () => setMicOff();
  recognition.onerror  = () => setMicOff();
  recognition.onresult = e => {
    const text = e.results[0][0].transcript.trim();
    if (text) {
      document.getElementById('msgInput').value = text;
      autoGrow(document.getElementById('msgInput'));
      sendMessage();
    }
  };
  recognition.start();
}

function setMicOn()  { listening = true;  document.getElementById('micBtn').classList.add('listening'); }
function setMicOff() { listening = false; document.getElementById('micBtn').classList.remove('listening'); }

// ── Push notifications ────────────────────────────────────────────────────────
async function pushNotification(title, body) {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default') {
    await Notification.requestPermission();
  }
  if (Notification.permission === 'granted') {
    new Notification(title, { body, icon: 'icon-192.png' });
  }
}

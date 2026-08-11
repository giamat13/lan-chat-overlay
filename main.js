const { app, BrowserWindow, ipcMain, screen, globalShortcut } = require('electron');
const path = require('path');
const fs = require('fs');
const net = require('net');

let mainWindow;
let server = null;
let client = null; // net.Socket - the active connection (either accepted or outgoing)
let isServer = false;
let listenPort = 51837; // fixed app port, same on both sides
let recvBuffer = '';

// --- Persisted config (remembers the peer IP between sessions) ---
const CONFIG_PATH = path.join(app.getPath('userData'), 'lan-chat-overlay-config.json');

function loadConfig() {
  try {
    const raw = fs.readFileSync(CONFIG_PATH, 'utf8');
    return JSON.parse(raw);
  } catch (e) {
    return {};
  }
}

function saveConfig(cfg) {
  try {
    fs.mkdirSync(path.dirname(CONFIG_PATH), { recursive: true });
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2), 'utf8');
  } catch (e) {
    // best effort - not fatal
  }
}

let config = loadConfig();

// --- Auto-reconnect state ---
let reconnectTimer = null;
let manualDisconnect = false; // true only when the user explicitly clicks disconnect
const RECONNECT_DELAY_MS = 2000;

// --- Manual-connect retry loop state ---
// If we click "connect" but the peer never answers, don't just give up
// after 30s and leave the user stuck - keep trying once a minute forever
// (until the user disconnects or a connection succeeds).
const MANUAL_CONNECT_TIMEOUT_MS = 60000; // give each attempt up to 1 minute
const MANUAL_CONNECT_RETRY_DELAY_MS = 60000; // then wait a minute and retry

function stopReconnectLoop() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
}

function scheduleReconnect(peerIp) {
  if (manualDisconnect || !peerIp) return;
  stopReconnectLoop();
  reconnectTimer = setTimeout(() => {
    if (manualDisconnect || client) return;
    startConnection(peerIp, true);
  }, RECONNECT_DELAY_MS);
}

function createWindow() {
  const { width: sw, height: sh } = screen.getPrimaryDisplay().workAreaSize;
  const winWidth = 340;
  const winHeight = 260;

  mainWindow = new BrowserWindow({
    width: winWidth,
    height: winHeight,
    x: sw - winWidth - 24,
    y: sh - winHeight - 24,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.setAlwaysOnTop(true, 'screen-saver');
  mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  mainWindow.loadFile('index.html');

  // Toggle click-through / focus with a global shortcut, so the overlay
  // never steals mouse focus from the game unless the user asks for it.
  globalShortcut.register('Control+Shift+C', () => {
    mainWindow.webContents.send('toggle-focus-request');
  });
}

function send(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

function attachSocket(socket, role, peerIp) {
  client = socket;
  isServer = role === 'server';
  recvBuffer = '';
  manualDisconnect = false;
  stopReconnectLoop();

  if (peerIp) {
    config.lastPeerIp = peerIp;
    saveConfig(config);
  }

  send('status', { state: 'connected', role });

  socket.on('data', (chunk) => {
    recvBuffer += chunk.toString('utf8');
    let idx;
    // Messages are newline-delimited JSON
    while ((idx = recvBuffer.indexOf('\n')) >= 0) {
      const line = recvBuffer.slice(0, idx);
      recvBuffer = recvBuffer.slice(idx + 1);
      if (!line.trim()) continue;
      try {
        const msg = JSON.parse(line);
        send('message', msg);
      } catch (e) {
        // ignore malformed line
      }
    }
  });

  socket.on('close', () => {
    client = null;
    if (manualDisconnect) {
      send('status', { state: 'disconnected' });
    } else {
      // Peer probably closed the app - keep trying to get back in touch
      // automatically instead of forcing both sides to click connect again.
      send('status', { state: 'reconnecting' });
      scheduleReconnect(peerIp || config.lastPeerIp);
    }
  });

  socket.on('error', (err) => {
    send('status', { state: 'error', error: err.message });
  });
}

function startConnection(peerIp, isAutoReconnect, giveupMsOverride) {
  // Strategy: BOTH sides listen on the fixed port AND simultaneously try to
  // connect out to the peer, in a race. Since the two sides are on two
  // different machines, listen() succeeding on both is expected and NOT a
  // conflict (unlike a single-machine EADDRINUSE scenario) - so we can't
  // rely on "who got the port" to decide server/client. Instead, whichever
  // direction actually completes a TCP handshake first wins; the loser is
  // torn down. The outgoing attempt retries periodically in case the peer
  // hasn't started listening yet.
  return new Promise((resolve) => {
    if (client) {
      resolve({ ok: false, error: 'כבר יש חיבור פעיל' });
      return;
    }

    manualDisconnect = false;

    const CONNECT_RETRY_MS = 1500;
    // Auto-reconnect attempts (after the peer briefly closed/reopened the
    // app) keep retrying indefinitely in the background; a fresh manual
    // click from the user still gives up after a while so the UI doesn't
    // hang forever on a bad IP.
    const CONNECT_GIVEUP_MS = giveupMsOverride !== undefined
      ? giveupMsOverride
      : (isAutoReconnect ? 0 : 30000);

    let resolved = false;
    let retryTimer = null;
    let giveupTimer = null;
    let trialServer = null;

    function cleanupTimers() {
      if (retryTimer) { clearInterval(retryTimer); retryTimer = null; }
      if (giveupTimer) { clearTimeout(giveupTimer); giveupTimer = null; }
    }

    function finish(result) {
      if (resolved) return;
      resolved = true;
      cleanupTimers();
      resolve(result);
    }

    // --- Listening side: accept an incoming connection from the peer ---
    trialServer = net.createServer((socket) => {
      if (client) {
        // We already connected out successfully in the meantime - reject
        // this extra incoming connection.
        socket.destroy();
        return;
      }
      trialServer.close();
      attachSocket(socket, 'server', peerIp);
      finish({ ok: true, mode: 'connected' });
    });

    trialServer.on('error', (err) => {
      // Not fatal: if the port is taken locally (e.g. a stray previous
      // process), the outgoing connect attempts below can still succeed.
      if (err.code !== 'EADDRINUSE') {
        send('status', { state: 'error', error: 'שרת: ' + err.message });
      }
    });

    trialServer.listen(listenPort, () => {
      server = trialServer;
      if (!client) send('status', { state: isAutoReconnect ? 'reconnecting' : 'listening', port: listenPort });
    });

    // --- Outgoing side: keep trying to connect to the peer ---
    function attemptClientConnect() {
      if (client || resolved) return;

      const socket = new net.Socket();

      const onError = () => {
        socket.destroy();
        // Swallow the error - we'll just retry on the next tick (the peer
        // may not be listening yet). Final failure is handled by giveupTimer.
      };
      socket.once('error', onError);

      socket.once('connect', () => {
        if (client) {
          // Race lost - the server side already accepted a connection.
          socket.destroy();
          return;
        }
        socket.removeListener('error', onError);
        attachSocket(socket, 'client', peerIp);
        if (server) { try { server.close(); } catch (e) {} server = null; }
        finish({ ok: true, mode: 'connected' });
      });

      socket.connect(listenPort, peerIp);
    }

    attemptClientConnect();
    retryTimer = setInterval(attemptClientConnect, CONNECT_RETRY_MS);

    if (CONNECT_GIVEUP_MS > 0) {
      giveupTimer = setTimeout(() => {
        if (resolved) return;
        if (server) { try { server.close(); } catch (e) {} server = null; }
        finish({ ok: false, error: 'לא הצלחתי להתחבר (timeout) - בדקו IP/פיירוול' });
      }, CONNECT_GIVEUP_MS);
    }
  });
}

function manualConnectLoop(peerIp) {
  if (manualDisconnect) return;

  startConnection(peerIp, false, MANUAL_CONNECT_TIMEOUT_MS).then((res) => {
    if (res.ok || manualDisconnect) return;

    // A minute passed with no answer from the peer - instead of giving up
    // for good, wait a minute and try again, and keep doing that until it
    // connects or the user hits disconnect.
    send('status', { state: 'listening', retryingIn: 60 });
    stopReconnectLoop();
    reconnectTimer = setTimeout(() => manualConnectLoop(peerIp), MANUAL_CONNECT_RETRY_DELAY_MS);
  });
}

ipcMain.handle('connect', async (_evt, { peerIp }) => {
  manualDisconnect = false;
  stopReconnectLoop();
  manualConnectLoop(peerIp);
  // Don't block the UI on the full retry loop - the renderer gets live
  // updates via 'status' events (listening / connected / reconnecting...).
  return { ok: true, mode: 'connecting' };
});

ipcMain.handle('get-saved-peer', async () => {
  return { peerIp: config.lastPeerIp || '' };
});

ipcMain.handle('send-message', async (_evt, { text }) => {
  if (!client) return { ok: false, error: 'אין חיבור' };
  const msg = { text, ts: Date.now(), from: 'me' };
  try {
    client.write(JSON.stringify({ text, ts: msg.ts }) + '\n');
    return { ok: true, ts: msg.ts };
  } catch (e) {
    return { ok: false, error: e.message };
  }
});

ipcMain.handle('disconnect', async () => {
  manualDisconnect = true;
  stopReconnectLoop();
  if (client) client.destroy();
  if (server) { server.close(); server = null; }
  client = null;
  send('status', { state: 'disconnected' });
  return { ok: true };
});

ipcMain.on('set-click-through', (_evt, enable) => {
  if (!mainWindow) return;
  mainWindow.setIgnoreMouseEvents(enable, { forward: true });
});

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('will-quit', () => {
  manualDisconnect = true;
  stopReconnectLoop();
  globalShortcut.unregisterAll();
  if (client) client.destroy();
  if (server) server.close();
});
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('overlayAPI', {
  connect: (peerIp) => ipcRenderer.invoke('connect', { peerIp }),
  disconnect: () => ipcRenderer.invoke('disconnect'),
  getSavedPeer: () => ipcRenderer.invoke('get-saved-peer'),
  sendMessage: (text) => ipcRenderer.invoke('send-message', { text }),
  setClickThrough: (enable) => ipcRenderer.send('set-click-through', enable),

  onMessage: (cb) => ipcRenderer.on('message', (_e, msg) => cb(msg)),
  onStatus: (cb) => ipcRenderer.on('status', (_e, status) => cb(status)),
  onToggleFocusRequest: (cb) => ipcRenderer.on('toggle-focus-request', () => cb()),
});

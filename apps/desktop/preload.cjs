const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("agentConchDesktop", {
  platform: process.platform,
  selectWorkspace: () => ipcRenderer.invoke("workspace:select"),
  selectFiles: () => ipcRenderer.invoke("files:select"),
  runTerminal: (request) => ipcRenderer.invoke("terminal:run", { ...request }),
  showNotification: (request) => ipcRenderer.invoke("notification:show", { ...request }),
});

const { app, BrowserWindow, dialog, ipcMain, Notification } = require("electron");
const path = require("node:path");

const WEB_URL = process.env.CONCH_WEB_URL;
const API_BASE = process.env.CONCH_API_BASE || "http://127.0.0.1:8765";

function createWindow() {
  const window = new BrowserWindow({
    width: 1600,
    height: 1000,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: "#070b14",
    title: "Agent Conch",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  if (WEB_URL) {
    window.loadURL(WEB_URL);
  } else {
    window.loadFile(path.join(__dirname, "../web/dist/index.html"));
  }
}

ipcMain.handle("workspace:select", async () => {
  const result = await dialog.showOpenDialog({ properties: ["openDirectory"] });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle("files:select", async () => {
  const result = await dialog.showOpenDialog({ properties: ["openFile", "multiSelections"] });
  return result.canceled ? [] : result.filePaths;
});

ipcMain.handle("notification:show", (_event, request) => {
  const title = String(request.title || "Agent Conch").slice(0, 120);
  const body = String(request.body || "").slice(0, 500);
  new Notification({ title, body }).show();
});

ipcMain.handle("terminal:run", async (_event, request) => {
  const response = await fetch(`${API_BASE}/desktop/terminal`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Conch-Principal": request.principal || "desktop",
      "X-Conch-Role": request.role || "developer",
    },
    body: JSON.stringify({
      session_id: request.sessionId,
      command: request.command,
      cwd: request.cwd || null,
      timeout: request.timeout || 120,
    }),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.json();
});

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

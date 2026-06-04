import { app, BrowserWindow } from "electron";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const desktopRoot = path.resolve(__dirname, "..");
const projectRoot = path.resolve(desktopRoot, "..");
const preloadPath = path.join(__dirname, "preload.js");

let mainWindow = null;
let backendProcess = null;

function startBackend() {
  if (backendProcess) return;

  backendProcess = spawn("python", ["-m", "anews_agent.api.server"], {
    cwd: projectRoot,
    env: {
      ...process.env,
      PYTHONPATH: path.join(projectRoot, "src"),
      ANEWS_DB_PATH: path.join(projectRoot, "anews.db"),
    },
    stdio: "inherit",
    windowsHide: true,
  });

  backendProcess.on("error", (error) => {
    console.error("Failed to start ANews backend:", error);
  });

  backendProcess.on("exit", () => {
    backendProcess = null;
  });
}

function stopBackend() {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
  backendProcess = null;
}

function isHttpUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function isDevServerUrl(url) {
  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (!devServerUrl) return false;

  try {
    return new URL(url).origin === new URL(devServerUrl).origin;
  } catch {
    return false;
  }
}

async function loadApp(window) {
  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    await window.loadURL(devServerUrl);
    return;
  }

  await window.loadFile(path.join(desktopRoot, "dist", "index.html"));
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 980,
    minHeight: 720,
    backgroundColor: "#f5f7fa",
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(() => {
    return { action: "deny" };
  });

  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (isHttpUrl(url) && !isDevServerUrl(url)) {
      event.preventDefault();
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  await loadApp(mainWindow);
}

app.whenReady().then(async () => {
  startBackend();
  await createWindow();

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  stopBackend();
});

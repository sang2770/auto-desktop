const { app, BrowserWindow, ipcMain, dialog, screen, desktopCapturer } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const { spawn } = require("node:child_process");

const isDev = !app.isPackaged;
const devServerUrl = process.env.AUTO_DESKTOP_DEV_SERVER_URL || "http://localhost:5173";
const workflowDir = path.join(app.getPath("userData"), "workflows");

function getProjectRoot() {
  return path.join(__dirname, "..");
}

function getBundledRunnerPath() {
  const exeName = process.platform === "win32" ? "automation_runner.exe" : "automation_runner";
  return path.join(process.resourcesPath, "runner", exeName);
}

function getRunnerScriptPath() {
  return path.join(getProjectRoot(), "runner", "automation_runner.py");
}

function resolvePythonCommand() {
  let python = process.env.PYTHON_PATH;
  if (python) {
    return python;
  }

  const venvDir = path.join(getProjectRoot(), ".venv");
  if (fs.existsSync(venvDir)) {
    const binPath = process.platform === "win32"
      ? path.join(venvDir, "Scripts", "python.exe")
      : path.join(venvDir, "bin", "python");
    if (fs.existsSync(binPath)) {
      return binPath;
    }
  }

  return process.platform === "win32" ? "python" : "python3";
}

function resolveRunnerCommand() {
  if (app.isPackaged) {
    const bundledRunner = getBundledRunnerPath();
    if (fs.existsSync(bundledRunner)) {
      return {
        command: bundledRunner,
        args: []
      };
    }
  }

  return {
    command: resolvePythonCommand(),
    args: [getRunnerScriptPath()]
  };
}

function ensureWorkflowDir() {
  fs.mkdirSync(workflowDir, { recursive: true });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 920,
    minWidth: 320,
    minHeight: 200,
    backgroundColor: "#121211",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  if (isDev) {
    win.loadURL(devServerUrl);
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

ipcMain.handle("workflow:list", async () => {
  ensureWorkflowDir();
  const files = fs.readdirSync(workflowDir).filter((file) => file.endsWith(".json"));
  const userDataList = files.map((file) => path.join(workflowDir, file));

  const projectWorkflowsDir = path.join(getProjectRoot(), "workflows");
  let projectList = [];
  if (fs.existsSync(projectWorkflowsDir)) {
    const projectFiles = fs.readdirSync(projectWorkflowsDir).filter((file) => file.endsWith(".json"));
    projectList = projectFiles.map((file) => path.join(projectWorkflowsDir, file));
  }

  const combined = [...userDataList, ...projectList];
  return Array.from(new Set(combined));
});

ipcMain.handle("workflow:load", async (_event, filePath) => {
  return fs.readFileSync(filePath, "utf8");
});

ipcMain.handle("workflow:save", async (_event, payload) => {
  let target;
  if (payload.filePath && path.isAbsolute(payload.filePath)) {
    target = payload.filePath;
  } else {
    ensureWorkflowDir();
    const safeName = payload.name.replace(/[^a-z0-9-_]+/gi, "-").toLowerCase();
    target = path.join(workflowDir, `${safeName || "workflow"}.json`);
  }
  fs.writeFileSync(target, payload.content, "utf8");
  return target;
});

ipcMain.handle("workflow:delete", async (_event, filePath) => {
  if (fs.existsSync(filePath)) {
    fs.unlinkSync(filePath);
    return true;
  }
  return false;
});


ipcMain.handle("workflow:pick-file", async () => {

  const result = await dialog.showOpenDialog({
    properties: ["openFile"],
    filters: [{ name: "JSON", extensions: ["json"] }]
  });
  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }
  return result.filePaths[0];
});

ipcMain.handle("image:save", async (_event, payload) => {
  ensureWorkflowDir();
  const imageDir = path.join(workflowDir, "images");
  fs.mkdirSync(imageDir, { recursive: true });

  const ext = path.extname(payload.name) || ".png";
  const baseName = path.basename(payload.name, ext).replace(/[^a-z0-9-_]+/gi, "-").toLowerCase();
  const targetFilename = `${baseName}-${Date.now()}${ext}`;
  const targetPath = path.join(imageDir, targetFilename);

  const base64Data = payload.base64.includes("base64,")
    ? payload.base64.split("base64,")[1]
    : payload.base64;

  fs.writeFileSync(targetPath, Buffer.from(base64Data, "base64"));
  return targetPath;
});

ipcMain.handle("image:read", async (_event, filePath) => {
  if (!fs.existsSync(filePath)) {
    return "";
  }
  const buffer = fs.readFileSync(filePath);
  const ext = path.extname(filePath).slice(1) || "png";
  return `data:image/${ext};base64,${buffer.toString("base64")}`;
});

ipcMain.handle("mouse:capture-position", async () => {
  try {
    const point = screen.getCursorScreenPoint();
    return { x: point.x, y: point.y };
  } catch (error) {
    console.error("Error capturing mouse position:", error);
    return null;
  }
});

ipcMain.handle("screen:capture-region", async () => {
  try {
    const primaryDisplay = screen.getPrimaryDisplay();
    const { width, height } = primaryDisplay.size;
    const scaleFactor = primaryDisplay.scaleFactor || 1;

    const sources = await desktopCapturer.getSources({
      types: ["screen"],
      thumbnailSize: {
        width: Math.round(width * scaleFactor),
        height: Math.round(height * scaleFactor)
      }
    });

    if (!sources || sources.length === 0) {
      console.error("No screen capture sources found.");
      return null;
    }

    const primarySource = sources.find(
      (s) => s.display_id === primaryDisplay.id.toString()
    ) || sources[0];

    const base64Image = primarySource.thumbnail.toDataURL();

    return await new Promise((resolve) => {
      let resolved = false;
      const safeResolve = (val) => {
        if (!resolved) {
          resolved = true;
          resolve(val);
        }
      };

      const cropWin = new BrowserWindow({
        width,
        height,
        x: 0,
        y: 0,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        fullscreen: true,
        skipTaskbar: true,
        enableLargerThanScreen: true,
        webPreferences: {
          nodeIntegration: true,
          contextIsolation: false
        }
      });

      cropWin.loadFile(path.join(__dirname, "crop.html"));

      cropWin.webContents.on("did-finish-load", () => {
        cropWin.webContents.send("init-crop", {
          imagePath: base64Image,
          width,
          height
        });
      });

      ipcMain.once("crop:done", (_event, result) => {
        if (!cropWin.isDestroyed()) {
          cropWin.close();
        }
        safeResolve(result);
      });

      ipcMain.once("crop:cancel", () => {
        if (!cropWin.isDestroyed()) {
          cropWin.close();
        }
        safeResolve(null);
      });

      cropWin.on("closed", () => {
        ipcMain.removeAllListeners("crop:done");
        ipcMain.removeAllListeners("crop:cancel");
        safeResolve(null);
      });
    });
  } catch (error) {
    console.error("Error capturing region:", error);
    return null;
  }
});

ipcMain.handle("runner:start", async (_event, payload) => {
  const runner = resolveRunnerCommand();

  return await new Promise((resolve, reject) => {
    const child = spawn(runner.command, [...runner.args, "--workflow-json", payload.workflow], {
      cwd: app.isPackaged ? process.resourcesPath : getProjectRoot()
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("error", (error) => reject(error));
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
});

ipcMain.handle("window:set-size", async (event, width, height) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win) {
    win.setSize(width, height);
    return true;
  }
  return false;
});

ipcMain.handle("window:set-always-on-top", async (event, flag) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win) {
    win.setAlwaysOnTop(flag);
    return true;
  }
  return false;
});

app.whenReady().then(() => {
  ensureWorkflowDir();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

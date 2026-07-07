const STORAGE_KEY = "auto-desktop.workflows";

type RunnerResult = {
  code: number;
  stdout: string;
  stderr: string;
};

type DesktopApi = {
  getWorkflowDir?: () => Promise<string>;
  listWorkflows: () => Promise<string[]>;
  loadWorkflow: (filePath: string) => Promise<string>;
  saveWorkflow: (payload: { name: string; content: string; filePath?: string }) => Promise<string>;
  deleteWorkflow: (filePath: string) => Promise<boolean>;
  pickWorkflowFile: () => Promise<string | null>;
  runWorkflow: (payload: { workflow: string }) => Promise<RunnerResult>;
  stopWorkflow: () => Promise<boolean>;
  saveImage: (payload: { name: string; base64: string }) => Promise<string>;
  readImage: (filePath: string) => Promise<string>;
  readDebugOcrImage: () => Promise<string>;
  captureMousePosition: () => Promise<{ x: number; y: number } | null>;
  captureRegion: () => Promise<{ x: number; y: number; width: number; height: number; base64: string } | null>;
  setWindowSize?: (width: number, height: number) => Promise<boolean>;
  setWindowAlwaysOnTop?: (flag: boolean) => Promise<boolean>;
  onStatusChange?: (callback: (status: "running" | "paused") => void) => () => void;
  onLog?: (callback: (log: string) => void) => () => void;
  captureWindowLayout?: () => Promise<Array<{
    title: string;
    x: number;
    y: number;
    width: number;
    height: number;
    enabled: boolean;
  }>>;
};

function readLocalWorkflows(): Record<string, string> {
  if (typeof window === "undefined") {
    return {};
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function writeLocalWorkflows(workflows: Record<string, string>) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(workflows));
}

const browserApi: DesktopApi = {
  async getWorkflowDir() {
    return "browser://";
  },
  async listWorkflows() {
    return Object.keys(readLocalWorkflows());
  },
  async loadWorkflow(filePath) {
    const workflows = readLocalWorkflows();
    const content = workflows[filePath];
    if (!content) {
      throw new Error(`Workflow not found in browser storage: ${filePath}`);
    }
    return content;
  },
  async saveWorkflow(payload) {
    const filePath = payload.filePath || `browser://${payload.name || "workflow"}.json`;
    const workflows = readLocalWorkflows();
    workflows[filePath] = payload.content;
    writeLocalWorkflows(workflows);
    return filePath;
  },

  async deleteWorkflow(filePath) {
    const workflows = readLocalWorkflows();
    if (workflows[filePath]) {
      delete workflows[filePath];
      writeLocalWorkflows(workflows);
      return true;
    }
    return false;
  },
  async pickWorkflowFile() {
    return null;
  },
  async runWorkflow(payload) {
    return {
      code: 0,
      stdout: [
        "[browser mode] Dry simulation only.",
        "[browser mode] Open this project through Electron to run Python automation.",
        payload.workflow ? "[browser mode] Workflow JSON received." : "[browser mode] No workflow payload."
      ].join("\n"),
      stderr: ""
    };
  },
  async stopWorkflow() {
    return true;
  },
  async saveImage(payload) {
    // In browser, return base64 string directly as the "file path"
    return payload.base64;
  },
  async readImage(filePath) {
    // In browser, file path is the base64 URL itself
    return filePath;
  },
  async readDebugOcrImage() {
    return "";
  },
  async captureMousePosition() {
    return { x: 800, y: 450 };
  },
  async captureRegion() {
    return {
      x: 200,
      y: 150,
      width: 100,
      height: 50,
      base64: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    };
  },
  async setWindowSize(width, height) {
    console.log(`[browser mode] Resize window to ${width}x${height}`);
    return true;
  },
  async setWindowAlwaysOnTop(flag) {
    console.log(`[browser mode] Set always on top: ${flag}`);
    return true;
  },
  onStatusChange(callback) {
    return () => {};
  },
  onLog(callback) {
    return () => {};
  },
  async captureWindowLayout() {
    return [
      { title: "Google Chrome", x: 100, y: 100, width: 1200, height: 800, enabled: true },
      { title: "TikTok Studio", x: 200, y: 150, width: 1000, height: 700, enabled: true }
    ];
  }
};

export const desktopApi: DesktopApi = window.desktopApi ?? browserApi;
export const isElectronDesktopApi = Boolean(window.desktopApi);

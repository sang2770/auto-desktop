const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktopApi", {
  listWorkflows: () => ipcRenderer.invoke("workflow:list"),
  loadWorkflow: (filePath) => ipcRenderer.invoke("workflow:load", filePath),
  saveWorkflow: (payload) => ipcRenderer.invoke("workflow:save", payload),
  deleteWorkflow: (filePath) => ipcRenderer.invoke("workflow:delete", filePath),
  pickWorkflowFile: () => ipcRenderer.invoke("workflow:pick-file"),

  runWorkflow: (payload) => ipcRenderer.invoke("runner:start", payload),
  stopWorkflow: () => ipcRenderer.invoke("runner:stop"),
  saveImage: (payload) => ipcRenderer.invoke("image:save", payload),
  readImage: (filePath) => ipcRenderer.invoke("image:read", filePath),
  captureMousePosition: () => ipcRenderer.invoke("mouse:capture-position"),
  captureRegion: () => ipcRenderer.invoke("screen:capture-region"),
  setWindowSize: (width, height) => ipcRenderer.invoke("window:set-size", width, height),
  setWindowAlwaysOnTop: (flag) => ipcRenderer.invoke("window:set-always-on-top", flag)
});

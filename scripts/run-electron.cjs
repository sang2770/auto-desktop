const { spawn } = require("node:child_process");
const electron = require("electron");

const DEV_URLS =
  process.argv.slice(2).length > 0
    ? process.argv.slice(2)
    : ["http://localhost:5173", "http://127.0.0.1:5173"];

async function checkUrl(url) {
  try {
    const response = await fetch(url, { method: "GET" });
    return response.status >= 200 && response.status < 500;
  } catch {
    return false;
  }
}

async function waitForRenderer(timeoutMs = 60000) {
  const start = Date.now();

  while (Date.now() - start < timeoutMs) {
    for (const url of DEV_URLS) {
      if (await checkUrl(url)) {
        return url;
      }
    }

    await new Promise((resolve) => setTimeout(resolve, 250));
  }

  throw new Error(
    `Timed out waiting for any dev server URL: ${DEV_URLS.join(", ")}`
  );
}

async function main() {
  const readyUrl = await waitForRenderer();

  const env = {
    ...process.env,
    AUTO_DESKTOP_DEV_SERVER_URL: readyUrl,
  };

  delete env.ELECTRON_RUN_AS_NODE;

  const child = spawn(electron, ["."], {
    stdio: "inherit",
    env,
    windowsHide: false,
  });

  child.on("error", (err) => {
    console.error("[electron] Failed to launch Electron:");
    console.error(err);
    process.exit(1);
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }

    process.exit(code ?? 0);
  });
}

main().catch((error) => {
  console.error("[electron] Failed to start Electron.");
  console.error(error);
  process.exit(1);
});
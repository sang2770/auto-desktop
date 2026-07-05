const { spawn } = require("node:child_process");

const DEV_URLS = ["http://localhost:5173", "http://127.0.0.1:5173"];

async function checkUrl(url) {
  try {
    const response = await fetch(url, { method: "GET" });
    return response.status >= 200 && response.status < 500;
  } catch {
    return false;
  }
}

async function findReadyRendererUrl() {
  for (const url of DEV_URLS) {
    if (await checkUrl(url)) {
      return url;
    }
  }
  return null;
}

function run(command, args) {
  const child = spawn(command, args, {
    stdio: "inherit",
    shell: false,
    env: process.env
  });

  return child;
}

async function main() {
  const readyUrl = await findReadyRendererUrl();

  if (readyUrl) {
    console.log(`[dev] Detected an existing dev server on ${readyUrl}`);
    console.log("[dev] Launching Electron only.");
    const electron = run("npm", ["run", "dev:electron", "--", readyUrl]);
    electron.on("exit", (code) => process.exit(code ?? 0));
    return;
  }

  console.log("[dev] No dev server detected. Launching Vite and Electron together.");
  const concurrent = run("npx", [
    "concurrently",
    "-k",
    "npm:dev:renderer",
    "npm run dev:electron -- http://localhost:5173"
  ]);
  concurrent.on("exit", (code) => process.exit(code ?? 0));
}

main().catch((error) => {
  console.error("[dev] Failed to start development mode.");
  console.error(error);
  process.exit(1);
});

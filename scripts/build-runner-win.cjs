const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const projectRoot = path.join(__dirname, "..");
const outputDir = path.join(projectRoot, "build", "runner", "win");
const workDir = path.join(projectRoot, "build", "pyinstaller", "work");
const specDir = path.join(projectRoot, "build", "pyinstaller", "spec");
const runnerPath = path.join(projectRoot, "runner", "automation_runner.py");

function run(command, args) {
  return spawnSync(command, args, {
    cwd: projectRoot,
    stdio: "inherit",
    shell: false,
    env: process.env
  });
}

function resolvePythonLauncher() {
  if (process.env.PYTHON_PATH) {
    return { command: process.env.PYTHON_PATH, prefixArgs: [] };
  }

  const candidates = process.platform === "win32"
    ? [
        { command: "py", prefixArgs: ["-3"] },
        { command: "python", prefixArgs: [] },
        { command: "python3", prefixArgs: [] }
      ]
    : [
        { command: "python3", prefixArgs: [] },
        { command: "python", prefixArgs: [] }
      ];

  for (const candidate of candidates) {
    const result = spawnSync(candidate.command, [...candidate.prefixArgs, "--version"], {
      cwd: projectRoot,
      stdio: "ignore",
      shell: false,
      env: process.env
    });
    if (result.status === 0) {
      return candidate;
    }
  }

  throw new Error("Python launcher not found. Set PYTHON_PATH or install Python 3.");
}

function ensureWindowsHost() {
  if (process.platform !== "win32") {
    throw new Error("Windows .exe build must be run on Windows because PyInstaller builds for the current OS.");
  }
}

function ensurePyInstaller(python) {
  const result = run(python.command, [...python.prefixArgs, "-m", "PyInstaller", "--version"]);
  if (result.status !== 0) {
    throw new Error(
      "PyInstaller is not installed. Run: python -m pip install -r runner/requirements-build.txt"
    );
  }
}

function main() {
  ensureWindowsHost();
  fs.mkdirSync(outputDir, { recursive: true });
  fs.mkdirSync(workDir, { recursive: true });
  fs.mkdirSync(specDir, { recursive: true });

  const python = resolvePythonLauncher();
  ensurePyInstaller(python);

  const args = [
    ...python.prefixArgs,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name",
    "automation_runner",
    "--distpath",
    outputDir,
    "--workpath",
    workDir,
    "--specpath",
    specDir,
    runnerPath
  ];

  const result = run(python.command, args);
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }

  console.log(`Runner built at ${path.join(outputDir, "automation_runner.exe")}`);
}

try {
  main();
} catch (error) {
  console.error("[build:runner:win]", error.message);
  process.exit(1);
}

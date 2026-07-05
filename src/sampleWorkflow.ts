import type { Workflow } from "./types";

export const sampleWorkflow: Workflow = {
  name: "tiktok-live-start-stop",
  description: "Sample workflow for starting a TikTok Studio live and stopping it later.",
  schedule: {
    enabled: true,
    startAt: "2026-07-04T20:00:00+07:00",
    stopAt: "2026-07-04T23:00:00+07:00",
    timezone: "Asia/Ho_Chi_Minh"
  },
  settings: {
    dryRun: true,
    retryCount: 2,
    captureOnError: true
  },
  startSteps: [
    {
      type: "launch_app",
      name: "Open TikTok Studio",
      command: "open -a 'TikTok Studio'"
    },
    {
      type: "wait",
      name: "Wait for UI",
      ms: 3000
    },
    {
      type: "click",
      name: "Open live connector",
      clickType: "coordinate",
      x: 1180,
      y: 640,
      note: "Replace with the saved screen coordinate."
    },
    {
      type: "wait_for_image",
      name: "Wait for Go Live button",
      image: "assets/go-live-button.png",
      region: [900, 500, 420, 240],
      timeoutMs: 10000,
      confidence: 0.82
    },
    {
      type: "click",
      name: "Click Go Live",
      clickType: "coordinate",
      x: 1224,
      y: 714
    },
    {
      type: "check_text",
      name: "Check live connected",
      text: "LIVE",
      region: [1080, 80, 200, 100],
      timeoutMs: 15000
    }
  ],
  stopSteps: [
    {
      type: "wait",
      name: "Wait before stop sequence",
      ms: 1000
    },
    {
      type: "click",
      name: "Click End Live",
      clickType: "coordinate",
      x: 1220,
      y: 714,
      note: "Replace with the actual stop button coordinate."
    },
    {
      type: "check_text",
      name: "Check live stopped",
      text: "Go Live",
      region: [900, 500, 420, 240],
      timeoutMs: 10000
    }
  ]
};

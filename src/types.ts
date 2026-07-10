export type ClickStep = {
  type: "click";
  name: string;
  clickType: "coordinate" | "image" | "text";
  x?: number;
  y?: number;
  clickMode?: "single" | "random";
  points?: Array<{ x: number; y: number }>;
  image?: string;
  text?: string;
  region?: [number, number, number, number];
  timeoutMs?: number;
  confidence?: number;
  delayBeforeSec?: number;
  delayAfterSec?: number;
  note?: string;
  indexVariable?: string;
};

export type DoubleClickStep = {
  type: "double_click";
  name: string;
  clickType: "coordinate" | "image" | "text";
  x?: number;
  y?: number;
  clickMode?: "single" | "random";
  points?: Array<{ x: number; y: number }>;
  image?: string;
  text?: string;
  region?: [number, number, number, number];
  timeoutMs?: number;
  confidence?: number;
  intervalSec?: number;
  delayBeforeSec?: number;
  delayAfterSec?: number;
  note?: string;
  indexVariable?: string;
};

export type WaitStep = {
  type: "wait";
  name: string;
  ms: number;
};

export type WaitForImageStep = {
  type: "wait_for_image";
  name: string;
  image: string;
  region?: [number, number, number, number];
  timeoutMs: number;
  confidence?: number;
};

export type CheckTextStep = {
  type: "check_text";
  name: string;
  text: string;
  region?: [number, number, number, number];
  timeoutMs: number;
  lang?: string;
  tesseractConfig?: string;
  ocrThreshold?: number;
};

export type LaunchAppStep = {
  type: "launch_app";
  name: string;
  command: string;
};

export type ConditionalStep = {
  type: "conditional";
  name: string;
  conditionType: "image" | "text";
  image?: string;
  confidence?: number;
  text?: string;
  region?: [number, number, number, number];
  actionType: "click" | "click_image" | "double_click" | "double_click_image" | "launch_app" | "wait";
  clickX?: number;
  clickY?: number;
  clickImage?: string;
  clickConfidence?: number;
  intervalSec?: number;
  command?: string;
  waitMs?: number;
};

export type RunWorkflowStep = {
  type: "run_workflow";
  name: string;
  workflowPath: string;
};

export type ConditionalWorkflowStep = {
  type: "conditional_workflow";
  name: string;
  conditionType: "image" | "text";
  image?: string;
  confidence?: number;
  text?: string;
  region?: [number, number, number, number];
  thenWorkflowPath?: string;
  elseWorkflowPath?: string;
};

export type CheckIntervalStep = {
  type: "check_interval";
  name: string;
  intervalId: string;
  intervalSec: number;
  actionWorkflowPath?: string;
  stopConditionType?: "image" | "text";
  stopImage?: string;
  stopConfidence?: number;
  stopText?: string;
  stopRegion?: [number, number, number, number];
};

export type ClearIntervalStep = {
  type: "clear_interval";
  name: string;
  intervalId: string;
};

export type PressKeyStep = {
  type: "press_key";
  name: string;
  key: string;
};

export type AbortIterationStep = {
  type: "abort_iteration";
  name: string;
};

export type SendTelegramStep = {
  type: "send_telegram";
  name: string;
  botToken: string;
  chatId: string;
  message?: string;
  captureScreen?: boolean;
  ocrRevenue?: boolean;
  ocrText?: boolean;
  image?: string;
  region?: [number, number, number, number];
};

export type DragStep = {
  type: "drag";
  name: string;
  startX: number;
  startY: number;
  endX: number;
  endY: number;
  durationSec?: number;
  button?: "left" | "right" | "middle";
  delayBeforeSec?: number;
  delayAfterSec?: number;
};

export type ScrollStep = {
  type: "scroll";
  name: string;
  amount: number;
  x?: number;
  y?: number;
  delayBeforeSec?: number;
  delayAfterSec?: number;
};

export type SetVariableStep = {
  type: "set_variable";
  name: string;
  variableName: string;
  operator: "set" | "add" | "subtract" | "multiply" | "divide";
  value: string;
};

export type ConditionalVariableStep = {
  type: "conditional_variable";
  name: string;
  variableName: string;
  operator: "==" | "!=" | ">" | "<" | ">=" | "<=";
  value: string;
  thenWorkflowPath?: string;
  elseWorkflowPath?: string;
};

export type Step =
  | ClickStep
  | DoubleClickStep
  | WaitStep
  | WaitForImageStep
  | CheckTextStep
  | LaunchAppStep
  | ConditionalStep
  | RunWorkflowStep
  | ConditionalWorkflowStep
  | CheckIntervalStep
  | ClearIntervalStep
  | PressKeyStep
  | AbortIterationStep
  | SendTelegramStep
  | DragStep
  | ScrollStep
  | SetVariableStep
  | ConditionalVariableStep;

export type Workflow = {
  name: string;
  description: string;
  schedule: {
    enabled: boolean;
    startAt: string;
    stopAt: string;
    timezone: string;
  };
  settings: {
    dryRun: boolean;
    retryCount: number;
    captureOnError: boolean;
    stepDelaySec?: number;
    repeat?: {
      enabled: boolean;
      times: number;
      intervalMs: number;
    };
    deviceName?: string;
    telegramBotToken?: string;
    telegramChatId?: string;
    reportStartup?: boolean;
    reportError?: boolean;
    windowLayout?: Array<{
      title: string;
      x: number;
      y: number;
      width: number;
      height: number;
      enabled: boolean;
    }>;
  };
  startSteps: Step[];
  stopSteps: Step[];
};

declare global {
  interface Window {
    desktopApi?: {
      listWorkflows: () => Promise<string[]>;
      loadWorkflow: (filePath: string) => Promise<string>;
      saveWorkflow: (payload: { name: string; content: string; filePath?: string }) => Promise<string>;
      deleteWorkflow: (filePath: string) => Promise<boolean>;
      pickWorkflowFile: () => Promise<string | null>;
      runWorkflow: (payload: { workflow: string }) => Promise<{
        code: number;
        stdout: string;
        stderr: string;
      }>;
      stopWorkflow: () => Promise<boolean>;
      saveImage: (payload: { name: string; base64: string }) => Promise<string>;
      readImage: (filePath: string) => Promise<string>;
      readDebugOcrImage: () => Promise<string>;
      captureMousePosition: () => Promise<{ x: number; y: number } | null>;
      captureRegion: () => Promise<{ x: number; y: number; width: number; height: number; base64: string } | null>;
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
  }
}

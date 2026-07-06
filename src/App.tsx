import React, { useEffect, useMemo, useState } from "react";
import { z } from "zod";
import { desktopApi, isElectronDesktopApi } from "./desktopApi";
import { sampleWorkflow } from "./sampleWorkflow";
import type { Workflow, Step, ClickStep, DoubleClickStep, WaitStep, WaitForImageStep, CheckTextStep, LaunchAppStep, ConditionalStep } from "./types";

const workflowSchema = z.object({
  name: z.string().min(1),
  description: z.string(),
  schedule: z.object({
    enabled: z.boolean(),
    startAt: z.string(),
    stopAt: z.string(),
    timezone: z.string()
  }),
  settings: z.object({
    dryRun: z.boolean(),
    retryCount: z.number().int().min(0),
    captureOnError: z.boolean(),
    stepDelaySec: z.number().min(0).optional(),
    repeat: z.object({
      enabled: z.boolean(),
      times: z.number().int().min(0),
      intervalMs: z.number().int().min(0)
    }).optional(),
    deviceName: z.string().optional(),
    telegramBotToken: z.string().optional(),
    telegramChatId: z.string().optional(),
    reportStartup: z.boolean().optional(),
    reportError: z.boolean().optional(),
    windowLayout: z.array(z.object({
      title: z.string(),
      x: z.number(),
      y: z.number(),
      width: z.number(),
      height: z.number(),
      enabled: z.boolean()
    })).optional()
  }),
  startSteps: z.array(z.record(z.any())),
  stopSteps: z.array(z.record(z.any()))
});

const sampleJson = JSON.stringify({
  ...sampleWorkflow,
  schedule: { enabled: false, startAt: "", stopAt: "", timezone: "Asia/Ho_Chi_Minh" },
  settings: {
    ...sampleWorkflow.settings,
    repeat: { enabled: false, times: 0, intervalMs: 1000 }
  },
  stopSteps: []
}, null, 2);

// Image Preview Component that handles both Base64 and Local paths
function ImagePreview({ filePath }: { filePath?: string }) {
  const [src, setSrc] = useState<string>("");

  useEffect(() => {
    if (!filePath) {
      setSrc("");
      return;
    }
    if (filePath.startsWith("data:") || filePath.startsWith("blob:")) {
      setSrc(filePath);
      return;
    }
    if (isElectronDesktopApi) {
      desktopApi
        .readImage(filePath)
        .then((base64) => setSrc(base64))
        .catch(() => setSrc(""));
    } else {
      setSrc(filePath);
    }
  }, [filePath]);

  if (!filePath) return <div className="no-image-preview">Chưa tải ảnh lên</div>;

  return (
    <div className="image-preview-container">
      {src ? (
        <img src={src} alt="Preview" className="image-preview" />
      ) : (
        <span className="no-image-preview">Đang tải...</span>
      )}
    </div>
  );
}

// Separate Component for Step Editing to manage local card states
function StepCard({
  step,
  index,
  onUpdate,
  onDelete,
  onMoveUp,
  onMoveDown,
  isFirst,
  isLast,
  savedWorkflows,
  workflowNames
}: {
  step: Step;
  index: number;
  onUpdate: (updatedStep: Step) => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  isFirst: boolean;
  isLast: boolean;
  savedWorkflows: string[];
  workflowNames: Record<string, string>;
}) {
  const isSeconds = step.type === "wait" && step.ms % 1000 === 0;
  const [waitUnit, setWaitUnit] = useState<"s" | "ms">(isSeconds ? "s" : "ms");
  const waitValue = step.type === "wait" ? (waitUnit === "s" ? step.ms / 1000 : step.ms) : 0;

  const [hasRegion, setHasRegion] = useState(
    "region" in step && Array.isArray(step.region) && step.region.length === 4
  );

  useEffect(() => {
    setHasRegion("region" in step && Array.isArray(step.region) && step.region.length === 4);
  }, [step]);

  useEffect(() => {
    setHasRegion("region" in step && Array.isArray(step.region) && step.region.length === 4);
  }, [step]);

  const region = "region" in step && step.region ? step.region : [0, 0, 0, 0];

  // Coords Capture
  const [coordsCountdown, setCoordsCountdown] = useState<number | null>(null);

  useEffect(() => {
    if (coordsCountdown === null) return;
    if (coordsCountdown > 0) {
      const timer = setTimeout(() => {
        setCoordsCountdown(coordsCountdown - 1);
      }, 1000);
      return () => clearTimeout(timer);
    } else {
      setCoordsCountdown(null);
      const getPos = isElectronDesktopApi
        ? desktopApi.captureMousePosition()
        : Promise.resolve({ x: 600, y: 400 });

      getPos.then((pos) => {
        if (pos) {
          onUpdate({ ...step, x: pos.x, y: pos.y } as Step);
        }
      });
    }
  }, [coordsCountdown]);

  // Region Capture (top-left & bottom-right)
  const [regionCountdown, setRegionCountdown] = useState<number | null>(null);
  const [regionPhase, setRegionPhase] = useState<"topleft" | "bottomright" | null>(null);
  const [tempTopLeft, setTempTopLeft] = useState<{ x: number; y: number } | null>(null);

  function startRegionCapture() {
    setRegionPhase("topleft");
    setRegionCountdown(3);
  }

  useEffect(() => {
    if (regionCountdown === null) return;
    if (regionCountdown > 0) {
      const timer = setTimeout(() => {
        setRegionCountdown(regionCountdown - 1);
      }, 1000);
      return () => clearTimeout(timer);
    } else {
      setRegionCountdown(null);
      if (regionPhase === "topleft") {
        const getPos = isElectronDesktopApi
          ? desktopApi.captureMousePosition()
          : Promise.resolve({ x: 200, y: 200 });

        getPos.then((pos) => {
          if (pos) {
            setTempTopLeft(pos);
            setRegionPhase("bottomright");
            setRegionCountdown(3);
          } else {
            setRegionPhase(null);
          }
        });
      } else if (regionPhase === "bottomright") {
        const getPos = isElectronDesktopApi
          ? desktopApi.captureMousePosition()
          : Promise.resolve({ x: 800, y: 600 });

        getPos.then((pos) => {
          if (pos && tempTopLeft) {
            const rx = Math.min(tempTopLeft.x, pos.x);
            const ry = Math.min(tempTopLeft.y, pos.y);
            const rw = Math.abs(pos.x - tempTopLeft.x);
            const rh = Math.abs(pos.y - tempTopLeft.y);
            onUpdate({ ...step, region: [rx, ry, rw, rh] } as Step);
          }
          setRegionPhase(null);
          setTempTopLeft(null);
        });
      }
    }
  }, [regionCountdown, regionPhase]);

  // Conditional Click Coords Capture
  const [condClickCountdown, setCondClickCountdown] = useState<number | null>(null);

  useEffect(() => {
    if (condClickCountdown === null) return;
    if (condClickCountdown > 0) {
      const timer = setTimeout(() => {
        setCondClickCountdown(condClickCountdown - 1);
      }, 1000);
      return () => clearTimeout(timer);
    } else {
      setCondClickCountdown(null);
      const getPos = isElectronDesktopApi
        ? desktopApi.captureMousePosition()
        : Promise.resolve({ x: 700, y: 350 });

      getPos.then((pos) => {
        if (pos) {
          onUpdate({ ...step, clickX: pos.x, clickY: pos.y } as Step);
        }
      });
    }
  }, [condClickCountdown]);

  function handleImageUpload(e: React.ChangeEvent<HTMLInputElement>, fieldName: "image" | "clickImage" | "stopImage") {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (event) => {
      const base64 = event.target?.result as string;
      if (isElectronDesktopApi) {
        try {
          const savedPath = await desktopApi.saveImage({ name: file.name, base64 });
          onUpdate({ ...step, [fieldName]: savedPath } as Step);
        } catch (err) {
          console.error("Error saving image:", err);
        }
      } else {
        onUpdate({ ...step, [fieldName]: base64 } as Step);
      }
    };
    reader.readAsDataURL(file);
  }

  const isCoordinateClick = 
    (step.type === "click" && (!step.clickType || step.clickType === "coordinate")) ||
    (step.type === "double_click" && (!step.clickType || step.clickType === "coordinate")) ||
    (step.type === "conditional" && (step.actionType === "click" || step.actionType === "double_click"));

  return (
    <div className={`step-card step-${step.type} ${isCoordinateClick ? "coordinate-highlight" : ""}`}>
      <div className="step-card-header">
        <div className="step-card-title-group">
          <span className="step-card-num">#{String(index + 1).padStart(2, "0")}</span>
          <span className="step-card-badge">
            {step.type === "launch_app" && "Chạy App"}
            {step.type === "wait" && "Chờ đợi"}
            {step.type === "click" && "Click chuột"}
            {step.type === "double_click" && "Double click"}
            {step.type === "wait_for_image" && "Đợi ảnh"}
            {step.type === "check_text" && "Xem chữ"}
            {step.type === "conditional" && "Kiểm tra (IF)"}
            {step.type === "run_workflow" && "Chạy Flow Con"}
            {step.type === "conditional_workflow" && "Rẽ Nhánh Flow"}
            {step.type === "check_interval" && "Lặp Chu Kỳ"}
            {step.type === "clear_interval" && "Dừng Chu Kỳ"}
            {step.type === "press_key" && "Nhấn Phím"}
            {step.type === "abort_iteration" && "Hủy Phiên Live"}
            {step.type === "send_telegram" && "Gửi Telegram"}
          </span>
          <input
            type="text"
            className="step-title-input"
            value={step.name}
            onChange={(e) => onUpdate({ ...step, name: e.target.value })}
            placeholder="Tên bước thực hiện"
            style={{
              background: "transparent",
              border: "none",
              borderBottom: "1px dashed rgba(255,255,255,0.2)",
              color: "#fff",
              fontWeight: 600,
              padding: "2px 6px"
            }}
          />
        </div>
        <div className="step-card-actions">
          <button type="button" onClick={onMoveUp} disabled={isFirst} title="Di chuyển lên">
            ↑
          </button>
          <button type="button" onClick={onMoveDown} disabled={isLast} title="Di chuyển xuống">
            ↓
          </button>
          <button type="button" className="delete-btn" onClick={onDelete} title="Xóa bước">
            Xóa
          </button>
        </div>
      </div>

      <div className="step-card-body">
        {/* Step type selector */}
        <div className="form-group">
          <label>Loại hành động</label>
          <select
            value={step.type}
            onChange={(e) => {
              const newType = e.target.value as Step["type"];
              if (newType === "launch_app") {
                onUpdate({ type: "launch_app", name: step.name, command: "" });
              } else if (newType === "wait") {
                onUpdate({ type: "wait", name: step.name, ms: 1000 });
              } else if (newType === "click") {
                onUpdate({ type: "click", name: step.name, clickType: "coordinate", x: 0, y: 0 });
              } else if (newType === "double_click") {
                onUpdate({ type: "double_click", name: step.name, clickType: "coordinate", x: 0, y: 0 });
              } else if (newType === "wait_for_image") {
                onUpdate({ type: "wait_for_image", name: step.name, image: "", timeoutMs: 5000, confidence: 0.8 });
              } else if (newType === "check_text") {
                onUpdate({ type: "check_text", name: step.name, text: "", timeoutMs: 5000 });
              } else if (newType === "conditional") {
                onUpdate({
                  type: "conditional",
                  name: step.name,
                  conditionType: "image",
                  image: "",
                  confidence: 0.8,
                  actionType: "click",
                  clickX: 0,
                  clickY: 0
                });
              } else if (newType === "run_workflow") {
                onUpdate({ type: "run_workflow", name: step.name, workflowPath: "" });
              } else if (newType === "conditional_workflow") {
                onUpdate({ type: "conditional_workflow", name: step.name, conditionType: "image", image: "", confidence: 0.8, thenWorkflowPath: "", elseWorkflowPath: "" });
              } else if (newType === "check_interval") {
                onUpdate({ type: "check_interval", name: step.name, intervalId: "loop1", intervalSec: 5, actionWorkflowPath: "", stopConditionType: "image", stopImage: "", stopConfidence: 0.8 });
              } else if (newType === "clear_interval") {
                onUpdate({ type: "clear_interval", name: step.name, intervalId: "loop1" });
              } else if (newType === "press_key") {
                onUpdate({ type: "press_key", name: step.name, key: "f5" });
              } else if (newType === "abort_iteration") {
                onUpdate({ type: "abort_iteration", name: step.name });
              } else if (newType === "send_telegram") {
                onUpdate({ type: "send_telegram", name: step.name, botToken: "", chatId: "", message: "Báo cáo kết quả", captureScreen: true, ocrRevenue: false, region: undefined });
              }
            }}
          >
            <option value="launch_app">Mở ứng dụng (Launch App)</option>
            <option value="wait">Chờ đợi (Delay / Wait)</option>
            <option value="click">Click chuột (Click)</option>
            <option value="double_click">Double Click chuột (Double Click)</option>
            <option value="wait_for_image">Chờ hình ảnh xuất hiện (Wait Image)</option>
            <option value="check_text">Kiểm tra chữ trên màn hình (Check Text)</option>
            <option value="conditional">Kiểm tra điều kiện (Nếu xuất hiện thì làm gì...)</option>
            <option value="run_workflow">Chạy workflow con (Sub-flow)</option>
            <option value="conditional_workflow">Rẽ nhánh workflow theo điều kiện (If-Else Flow)</option>
            <option value="check_interval">Kiểm tra lặp chu kỳ (Check Interval)</option>
            <option value="clear_interval">Xoá lặp chu kỳ (Clear Interval)</option>
            <option value="press_key">Nhấn phím bàn phím (Press Key)</option>
            <option value="abort_iteration">Hủy phiên Live hiện tại (Abort Iteration)</option>
            <option value="send_telegram">Gửi báo cáo Telegram (Send Telegram)</option>
          </select>
        </div>


        {/* Dynamic fields based on type */}
        {step.type === "launch_app" && (
          <div className="form-group">
            <label>Lệnh chạy ứng dụng (Command)</label>
            <input
              type="text"
              value={step.command}
              onChange={(e) => onUpdate({ ...step, command: e.target.value })}
              placeholder="ví dụ: open -a 'TikTok Studio'"
            />
          </div>
        )}

        {step.type === "wait" && (
          <div className="form-grid">
            <div className="form-group">
              <label>Thời gian chờ</label>
              <input
                type="number"
                value={waitValue}
                onChange={(e) => {
                  const val = parseFloat(e.target.value) || 0;
                  onUpdate({ ...step, ms: waitUnit === "s" ? val * 1000 : val });
                }}
              />
            </div>
            <div className="form-group">
              <label>Đơn vị</label>
              <select
                value={waitUnit}
                onChange={(e) => {
                  const unit = e.target.value as "s" | "ms";
                  setWaitUnit(unit);
                  onUpdate({
                    ...step,
                    ms: unit === "s" ? step.ms : step.ms
                  });
                }}
              >
                <option value="s">Giây (Seconds)</option>
                <option value="ms">Mili giây (Milliseconds)</option>
              </select>
            </div>
          </div>
        )}

        {(step.type === "click" || step.type === "double_click") && (
          <>
            <div className="form-grid">
              <div className="form-group">
                <label>Cách xác định vị trí click</label>
                <select
                  value={step.clickType || "coordinate"}
                  onChange={(e) => {
                    const clickType = e.target.value as "coordinate" | "image" | "text";
                    if (clickType === "image") {
                      onUpdate({
                        ...step,
                        clickType,
                        image: step.image || "",
                        confidence: step.confidence || 0.8,
                        timeoutMs: step.timeoutMs || 5000,
                        x: undefined,
                        y: undefined,
                        text: undefined
                      });
                    } else if (clickType === "text") {
                      onUpdate({
                        ...step,
                        clickType,
                        text: step.text || "",
                        timeoutMs: step.timeoutMs || 5000,
                        x: undefined,
                        y: undefined,
                        image: undefined,
                        confidence: undefined,
                        region: undefined
                      });
                    } else {
                      onUpdate({
                        ...step,
                        clickType,
                        x: step.x || 0,
                        y: step.y || 0,
                        image: undefined,
                        confidence: undefined,
                        timeoutMs: undefined,
                        region: undefined,
                        text: undefined
                      });
                    }
                  }}
                >
                  <option value="coordinate">Nhập Toạ độ X, Y</option>
                  <option value="image">
                    {step.type === "double_click"
                      ? "Tìm Ảnh rồi Double Click (Khớp hình ảnh)"
                      : "Tìm Ảnh rồi Click (Khớp hình ảnh)"}
                  </option>
                  <option value="text">Tìm Chữ rồi Click (Nhận diện chữ OCR)</option>
                </select>

              </div>
              {step.clickType === "coordinate" && (
                <>
                  <div className="form-group">
                    <label>Toạ độ X</label>
                    <input
                      type="number"
                      value={step.x ?? 0}
                      onChange={(e) => onUpdate({ ...step, x: parseInt(e.target.value) || 0 })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Toạ độ Y</label>
                    <input
                      type="number"
                      value={step.y ?? 0}
                      onChange={(e) => onUpdate({ ...step, y: parseInt(e.target.value) || 0 })}
                    />
                  </div>
                  <div className="form-group" style={{ gridColumn: "span 2", display: "flex", gap: "8px" }}>
                    <div style={{ flex: 1 }}>
                      <label>Lấy toạ độ di chuột</label>
                      <button
                        type="button"
                        onClick={() => setCoordsCountdown(3)}
                        disabled={coordsCountdown !== null}
                        style={{ width: "100%", marginTop: "6px", background: coordsCountdown !== null ? "#c85f1f" : "rgba(255, 255, 255, 0.08)" }}
                      >
                        {coordsCountdown !== null
                          ? `Di chuột... (${coordsCountdown}s)`
                          : "🔍 Di chuột lấy điểm"}
                      </button>
                    </div>
                    <div style={{ flex: 1 }}>
                      <label>Vẽ khoanh vùng</label>
                      <button
                        type="button"
                        onClick={async () => {
                          const res = await desktopApi.captureRegion();
                          if (res) {
                            const cx = res.x + Math.round(res.width / 2);
                            const cy = res.y + Math.round(res.height / 2);
                            onUpdate({ ...step, x: cx, y: cy });
                          }
                        }}
                        style={{ width: "100%", marginTop: "6px", background: "rgba(255, 255, 255, 0.08)" }}
                      >
                        🎯 Vẽ vùng (Lấy Tâm)
                      </button>
                    </div>
                  </div>
                </>
              )}
              {step.clickType === "image" && (
                <>
                  <div className="form-group">
                    <label>Thời gian chờ tối đa (giây)</label>
                    <input
                      type="number"
                      value={((step.timeoutMs || 5000) / 1000)}
                      onChange={(e) => onUpdate({ ...step, timeoutMs: (parseFloat(e.target.value) || 5) * 1000 })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Độ tin cậy khớp ảnh: {step.confidence ?? 0.8}</label>
                    <input
                      type="range"
                      min="0.5"
                      max="1"
                      step="0.05"
                      value={step.confidence ?? 0.8}
                      onChange={(e) => onUpdate({ ...step, confidence: parseFloat(e.target.value) })}
                    />
                  </div>
                </>
              )}
              {step.clickType === "text" && (
                <>
                  <div className="form-group" style={{ gridColumn: "span 2" }}>
                    <label>Chữ cần tìm để click</label>
                    <input
                      type="text"
                      value={step.text ?? ""}
                      onChange={(e) => onUpdate({ ...step, text: e.target.value })}
                      placeholder="Nhập từ hoặc cụm từ cần tìm..."
                    />
                  </div>
                  <div className="form-group">
                    <label>Thời gian chờ tối đa (giây)</label>
                    <input
                      type="number"
                      value={((step.timeoutMs || 5000) / 1000)}
                      onChange={(e) => onUpdate({ ...step, timeoutMs: (parseFloat(e.target.value) || 5) * 1000 })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Khoanh vùng tìm chữ (Region)</label>
                    <button
                      type="button"
                      onClick={async () => {
                        const res = await desktopApi.captureRegion();
                        if (res) {
                          onUpdate({ ...step, region: [res.x, res.y, res.width, res.height] });
                        }
                      }}
                      style={{ width: "100%", marginTop: "6px", background: "rgba(255, 255, 255, 0.08)" }}
                    >
                      {step.region ? `Vùng: [${step.region.join(",")}]` : "🎯 Vẽ vùng tìm kiếm"}
                    </button>
                  </div>
                </>
              )}
            </div>

            {step.clickType === "image" && (
              <div className="image-upload-wrapper form-section" style={{ border: "none", margin: 0, padding: 0 }}>
                <div className="form-group">
                  <label>Ảnh mẫu cần Click (Tải lên hoặc chụp màn hình)</label>
                  <div style={{ display: "flex", gap: "10px", marginTop: "4px" }}>
                    <div className="image-upload-box" style={{ flex: 1 }}>
                      <span className="image-upload-text">📁 Chọn file ảnh</span>
                      <input type="file" accept="image/*" onChange={(e) => handleImageUpload(e, "image")} />
                    </div>
                    <button
                      type="button"
                      onClick={async () => {
                        const res = await desktopApi.captureRegion();
                        if (res) {
                          if (isElectronDesktopApi) {
                            const path = await desktopApi.saveImage({ name: "crop-click.png", base64: res.base64 });
                            onUpdate({ ...step, image: path });
                          } else {
                            onUpdate({ ...step, image: res.base64 });
                          }
                        }
                      }}
                      style={{ background: "rgba(255,255,255,0.06)", border: "1px dashed rgba(255,255,255,0.2)" }}
                    >
                      📷 Chụp trực tiếp
                    </button>
                  </div>
                </div>
                <ImagePreview filePath={step.image} />
              </div>
            )}

            <div className="form-grid" style={{ marginBottom: "10px" }}>
              <div className="form-group">
                <label>Thời gian chờ trước khi click (giây)</label>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={step.delayBeforeSec ?? 0}
                  onChange={(e) => onUpdate({ ...step, delayBeforeSec: parseFloat(e.target.value) || 0 })}
                  placeholder="0"
                />
              </div>
              <div className="form-group">
                <label>Thời gian chờ sau khi click (giây)</label>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={step.delayAfterSec ?? 0}
                  onChange={(e) => onUpdate({ ...step, delayAfterSec: parseFloat(e.target.value) || 0 })}
                  placeholder="0"
                />
              </div>
            </div>

            <div className="form-group">
              <label>Ghi chú / Nhắc nhở (Note)</label>
              <input
                type="text"
                value={step.note || ""}
                onChange={(e) => onUpdate({ ...step, note: e.target.value })}
                placeholder="Ghi chú về vị trí hoặc chức năng nút này..."
              />
            </div>
          </>
        )}

        {step.type === "wait_for_image" && (
          <>
            <div className="image-upload-wrapper">
              <div className="form-group">
                <label>Ảnh mẫu cần chờ (Tải lên hoặc chụp màn hình)</label>
                <div style={{ display: "flex", gap: "10px", marginTop: "4px" }}>
                  <div className="image-upload-box" style={{ flex: 1 }}>
                    <span className="image-upload-text">📁 Chọn file ảnh</span>
                    <input type="file" accept="image/*" onChange={(e) => handleImageUpload(e, "image")} />
                  </div>
                  <button
                    type="button"
                    onClick={async () => {
                      const res = await desktopApi.captureRegion();
                      if (res) {
                        if (isElectronDesktopApi) {
                          const path = await desktopApi.saveImage({ name: "crop-wait.png", base64: res.base64 });
                          onUpdate({ ...step, image: path });
                        } else {
                          onUpdate({ ...step, image: res.base64 });
                        }
                      }
                    }}
                    style={{ background: "rgba(255,255,255,0.06)", border: "1px dashed rgba(255,255,255,0.2)" }}
                  >
                    📷 Chụp trực tiếp
                  </button>
                </div>
              </div>
              <ImagePreview filePath={step.image} />
            </div>

            <div className="form-grid">
              <div className="form-group">
                <label>Thời gian chờ tối đa (giây)</label>
                <input
                  type="number"
                  value={step.timeoutMs / 1000}
                  onChange={(e) => onUpdate({ ...step, timeoutMs: (parseFloat(e.target.value) || 5) * 1000 })}
                />
              </div>
              <div className="form-group">
                <label>Độ tin cậy khớp: {step.confidence ?? 0.8}</label>
                <input
                  type="range"
                  min="0.5"
                  max="1"
                  step="0.05"
                  value={step.confidence ?? 0.8}
                  onChange={(e) => onUpdate({ ...step, confidence: parseFloat(e.target.value) })}
                />
              </div>
            </div>
          </>
        )}

        {step.type === "check_text" && (
          <div className="form-grid">
            <div className="form-group">
              <label>Chữ/Text cần tìm kiếm</label>
              <input
                type="text"
                value={step.text}
                onChange={(e) => onUpdate({ ...step, text: e.target.value })}
                placeholder="ví dụ: LIVE"
              />
            </div>
            <div className="form-group">
              <label>Thời gian chờ tối đa (giây)</label>
              <input
                type="number"
                value={step.timeoutMs / 1000}
                onChange={(e) => onUpdate({ ...step, timeoutMs: (parseFloat(e.target.value) || 5) * 1000 })}
              />
            </div>
          </div>
        )}

        {step.type === "conditional" && (
          <>
            <div className="form-grid">
              <div className="form-group">
                <label>Nếu thấy (Điều kiện)</label>
                <select
                  value={step.conditionType}
                  onChange={(e) => {
                    const condType = e.target.value as "image" | "text";
                    onUpdate({
                      ...step,
                      conditionType: condType,
                      image: condType === "image" ? "" : undefined,
                      confidence: condType === "image" ? 0.8 : undefined,
                      text: condType === "text" ? "" : undefined
                    } as Step);
                  }}
                >
                  <option value="image">Hình ảnh xuất hiện</option>
                  <option value="text">Chữ xuất hiện trên màn hình</option>
                </select>
              </div>

              {step.conditionType === "image" && (
                <div className="form-group">
                  <label>Độ tin cậy khớp: {step.confidence ?? 0.8}</label>
                  <input
                    type="range"
                    min="0.5"
                    max="1"
                    step="0.05"
                    value={step.confidence ?? 0.8}
                    onChange={(e) => onUpdate({ ...step, confidence: parseFloat(e.target.value) } as Step)}
                  />
                </div>
              )}
            </div>

            {step.conditionType === "image" ? (
              <div className="image-upload-wrapper form-section" style={{ border: "none", margin: 0, padding: 0 }}>
                <div className="form-group">
                  <label>Ảnh mẫu điều kiện cần xuất hiện</label>
                  <div style={{ display: "flex", gap: "10px", marginTop: "4px" }}>
                    <div className="image-upload-box" style={{ flex: 1 }}>
                      <span className="image-upload-text">📁 Chọn file ảnh</span>
                      <input type="file" accept="image/*" onChange={(e) => handleImageUpload(e, "image")} />
                    </div>
                    <button
                      type="button"
                      onClick={async () => {
                        const res = await desktopApi.captureRegion();
                        if (res) {
                          if (isElectronDesktopApi) {
                            const path = await desktopApi.saveImage({ name: "crop-cond.png", base64: res.base64 });
                            onUpdate({ ...step, image: path });
                          } else {
                            onUpdate({ ...step, image: res.base64 });
                          }
                        }
                      }}
                      style={{ background: "rgba(255,255,255,0.06)", border: "1px dashed rgba(255,255,255,0.2)" }}
                    >
                      📷 Chụp trực tiếp
                    </button>
                  </div>
                </div>
                <ImagePreview filePath={step.image} />
              </div>
            ) : (
              <div className="form-group">
                <label>Nhập chữ cần tìm kiếm</label>
                <input
                  type="text"
                  value={step.text ?? ""}
                  onChange={(e) => onUpdate({ ...step, text: e.target.value } as Step)}
                  placeholder="e.g. Lỗi kết nối"
                />
              </div>
            )}

            {/* Action Section */}
            <div className="form-grid" style={{ marginTop: "8px", borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: "12px" }}>
              <div className="form-group">
                <label>Thì thực hiện (Hành động)</label>
                <select
                  value={step.actionType}
                  onChange={(e) => {
                    const actType = e.target.value as any;
                    onUpdate({
                      ...step,
                      actionType: actType,
                      clickX: (actType === "click" || actType === "double_click") ? 0 : undefined,
                      clickY: (actType === "click" || actType === "double_click") ? 0 : undefined,
                      clickImage: (actType === "click_image" || actType === "double_click_image") ? "" : undefined,
                      clickConfidence: (actType === "click_image" || actType === "double_click_image") ? 0.8 : undefined,
                      command: actType === "launch_app" ? "" : undefined,
                      waitMs: actType === "wait" ? 1000 : undefined
                    } as Step);
                  }}
                >
                  <option value="click">Click vào Toạ độ X, Y</option>
                  <option value="double_click">Double Click vào Toạ độ X, Y</option>
                  <option value="click_image">Click vào Hình ảnh mẫu</option>
                  <option value="double_click_image">Double Click vào Hình ảnh mẫu</option>
                  <option value="launch_app">Mở ứng dụng khác</option>
                  <option value="wait">Chờ đợi thời gian</option>
                </select>
              </div>

              {(step.actionType === "click" || step.actionType === "double_click") && (
                <>
                  <div className="form-group">
                    <label>Toạ độ X</label>
                    <input
                      type="number"
                      value={step.clickX ?? 0}
                      onChange={(e) => onUpdate({ ...step, clickX: parseInt(e.target.value) || 0 } as Step)}
                    />
                  </div>
                  <div className="form-group">
                    <label>Toạ độ Y</label>
                    <input
                      type="number"
                      value={step.clickY ?? 0}
                      onChange={(e) => onUpdate({ ...step, clickY: parseInt(e.target.value) || 0 } as Step)}
                    />
                  </div>
                  <div className="form-group" style={{ gridColumn: "span 2", display: "flex", gap: "8px" }}>
                    <div style={{ flex: 1 }}>
                      <label>Lấy toạ độ di chuột</label>
                      <button
                        type="button"
                        onClick={() => setCondClickCountdown(3)}
                        disabled={condClickCountdown !== null}
                        style={{ width: "100%", marginTop: "6px", background: condClickCountdown !== null ? "#e91e63" : "rgba(255, 255, 255, 0.08)" }}
                      >
                        {condClickCountdown !== null
                          ? `Di chuột... (${condClickCountdown}s)`
                          : "🔍 Di chuột lấy điểm"}
                      </button>
                    </div>
                    <div style={{ flex: 1 }}>
                      <label>Vẽ khoanh vùng</label>
                      <button
                        type="button"
                        onClick={async () => {
                          const res = await desktopApi.captureRegion();
                          if (res) {
                            const cx = res.x + Math.round(res.width / 2);
                            const cy = res.y + Math.round(res.height / 2);
                            onUpdate({ ...step, clickX: cx, clickY: cy } as Step);
                          }
                        }}
                        style={{ width: "100%", marginTop: "6px", background: "rgba(255, 255, 255, 0.08)" }}
                      >
                        🎯 Vẽ vùng (Lấy Tâm)
                      </button>
                    </div>
                  </div>
                </>
              )}

              {(step.actionType === "click_image" || step.actionType === "double_click_image") && (
                <div className="form-group">
                  <label>Độ khớp ảnh click: {step.clickConfidence ?? 0.8}</label>
                  <input
                    type="range"
                    min="0.5"
                    max="1"
                    step="0.05"
                    value={step.clickConfidence ?? 0.8}
                    onChange={(e) => onUpdate({ ...step, clickConfidence: parseFloat(e.target.value) } as Step)}
                  />
                </div>
              )}

              {step.actionType === "launch_app" && (
                <div className="form-group" style={{ gridColumn: "span 2" }}>
                  <label>Lệnh chạy Command</label>
                  <input
                    type="text"
                    value={step.command ?? ""}
                    onChange={(e) => onUpdate({ ...step, command: e.target.value } as Step)}
                    placeholder="e.g. open -a 'TikTok Studio'"
                  />
                </div>
              )}

              {step.actionType === "wait" && (
                <div className="form-group">
                  <label>Thời gian chờ (giây)</label>
                  <input
                    type="number"
                    value={(step.waitMs ?? 1000) / 1000}
                    onChange={(e) => onUpdate({ ...step, waitMs: (parseFloat(e.target.value) || 1) * 1000 } as Step)}
                  />
                </div>
              )}
            </div>

            {(step.actionType === "click_image" || step.actionType === "double_click_image") && (
              <div className="image-upload-wrapper form-section" style={{ border: "none", margin: 0, padding: 0 }}>
                <div className="form-group">
                  <label>Ảnh mẫu click (Tải lên hoặc chụp màn hình)</label>
                  <div style={{ display: "flex", gap: "10px", marginTop: "4px" }}>
                    <div className="image-upload-box" style={{ flex: 1 }}>
                      <span className="image-upload-text">📁 Chọn file ảnh</span>
                      <input type="file" accept="image/*" onChange={(e) => handleImageUpload(e, "clickImage")} />
                    </div>
                    <button
                      type="button"
                      onClick={async () => {
                        const res = await desktopApi.captureRegion();
                        if (res) {
                          if (isElectronDesktopApi) {
                            const path = await desktopApi.saveImage({ name: "crop-clickaction.png", base64: res.base64 });
                            onUpdate({ ...step, clickImage: path });
                          } else {
                            onUpdate({ ...step, clickImage: res.base64 });
                          }
                        }
                      }}
                      style={{ background: "rgba(255,255,255,0.06)", border: "1px dashed rgba(255,255,255,0.2)" }}
                    >
                      📷 Chụp trực tiếp
                    </button>
                  </div>
                </div>
                <ImagePreview filePath={step.clickImage} />
              </div>
            )}

          </>
        )}

        {step.type === "run_workflow" && (
          <div className="form-group">
            <label>Chọn workflow con để chạy</label>
            <select
              value={step.workflowPath}
              onChange={(e) => onUpdate({ ...step, workflowPath: e.target.value })}
            >
              <option value="">-- Chọn workflow --</option>
              {savedWorkflows.map((path) => (
                <option key={path} value={path}>
                  {workflowNames[path] || path.split(/[/\\]/).pop() || path}
                </option>
              ))}
            </select>
          </div>
        )}

        {step.type === "conditional_workflow" && (
          <>
            <div className="form-grid">
              <div className="form-group">
                <label>Nếu thấy (Điều kiện)</label>
                <select
                  value={step.conditionType}
                  onChange={(e) => {
                    const condType = e.target.value as "image" | "text";
                    onUpdate({
                      ...step,
                      conditionType: condType,
                      image: condType === "image" ? "" : undefined,
                      confidence: condType === "image" ? 0.8 : undefined,
                      text: condType === "text" ? "" : undefined
                    } as Step);
                  }}
                >
                  <option value="image">Hình ảnh xuất hiện</option>
                  <option value="text">Chữ xuất hiện trên màn hình</option>
                </select>
              </div>

              {step.conditionType === "image" && (
                <div className="form-group">
                  <label>Độ tin cậy khớp: {step.confidence ?? 0.8}</label>
                  <input
                    type="range"
                    min="0.5"
                    max="1"
                    step="0.05"
                    value={step.confidence ?? 0.8}
                    onChange={(e) => onUpdate({ ...step, confidence: parseFloat(e.target.value) } as Step)}
                  />
                </div>
              )}
            </div>

            {step.conditionType === "image" ? (
              <div className="image-upload-wrapper form-section" style={{ border: "none", margin: 0, padding: 0 }}>
                <div className="form-group">
                  <label>Ảnh mẫu điều kiện cần xuất hiện</label>
                  <div style={{ display: "flex", gap: "10px", marginTop: "4px" }}>
                    <div className="image-upload-box" style={{ flex: 1 }}>
                      <span className="image-upload-text">📁 Chọn file ảnh</span>
                      <input type="file" accept="image/*" onChange={(e) => handleImageUpload(e, "image")} />
                    </div>
                    <button
                      type="button"
                      onClick={async () => {
                        const res = await desktopApi.captureRegion();
                        if (res) {
                          if (isElectronDesktopApi) {
                            const path = await desktopApi.saveImage({ name: "crop-cond-flow.png", base64: res.base64 });
                            onUpdate({ ...step, image: path });
                          } else {
                            onUpdate({ ...step, image: res.base64 });
                          }
                        }
                      }}
                      style={{ background: "rgba(255,255,255,0.06)", border: "1px dashed rgba(255,255,255,0.2)" }}
                    >
                      📷 Chụp trực tiếp
                    </button>
                  </div>
                </div>
                <ImagePreview filePath={step.image} />
              </div>
            ) : (
              <div className="form-group">
                <label>Nhập chữ cần tìm kiếm</label>
                <input
                  type="text"
                  value={step.text ?? ""}
                  onChange={(e) => onUpdate({ ...step, text: e.target.value } as Step)}
                  placeholder="e.g. Lỗi kết nối"
                />
              </div>
            )}

            <div className="form-grid" style={{ marginTop: "12px", borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: "12px" }}>
              <div className="form-group">
                <label>Nếu ĐÚNG (Thì chạy Flow)</label>
                <select
                  value={step.thenWorkflowPath ?? ""}
                  onChange={(e) => onUpdate({ ...step, thenWorkflowPath: e.target.value })}
                >
                  <option value="">-- Chọn workflow --</option>
                  {savedWorkflows.map((path) => (
                    <option key={path} value={path}>
                      {workflowNames[path] || path.split(/[/\\]/).pop() || path}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Nếu SAI (Thì chạy Flow - Không bắt buộc)</label>
                <select
                  value={step.elseWorkflowPath ?? ""}
                  onChange={(e) => onUpdate({ ...step, elseWorkflowPath: e.target.value })}
                >
                  <option value="">-- Chọn workflow (bỏ qua nếu không cần) --</option>
                  {savedWorkflows.map((path) => (
                    <option key={path} value={path}>
                      {workflowNames[path] || path.split(/[/\\]/).pop() || path}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </>
        )}

        {step.type === "check_interval" && (
          <>
            <div className="form-grid">
              <div className="form-group">
                <label>Mã chu kỳ (Interval ID)</label>
                <input
                  type="text"
                  value={step.intervalId}
                  onChange={(e) => onUpdate({ ...step, intervalId: e.target.value })}
                  placeholder="e.g. check_popup"
                />
              </div>

              <div className="form-group">
                <label>Chu kỳ kiểm tra (giây)</label>
                <input
                  type="number"
                  value={step.intervalSec}
                  onChange={(e) => onUpdate({ ...step, intervalSec: parseFloat(e.target.value) || 5 })}
                />
              </div>
            </div>

            <div className="form-group" style={{ marginTop: "8px" }}>
              <label>Workflow thực hiện trong chu kỳ</label>
              <select
                value={step.actionWorkflowPath ?? ""}
                onChange={(e) => onUpdate({ ...step, actionWorkflowPath: e.target.value })}
              >
                <option value="">-- Chọn workflow thực hiện --</option>
                {savedWorkflows.map((path) => (
                  <option key={path} value={path}>
                    {workflowNames[path] || path.split(/[/\\]/).pop() || path}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-grid" style={{ marginTop: "12px", borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: "12px" }}>
              <div className="form-group">
                <label>Điều kiện TỰ ĐỘNG DỪNG (Clear Interval)</label>
                <select
                  value={step.stopConditionType ?? "image"}
                  onChange={(e) => {
                    const condType = e.target.value as "image" | "text";
                    onUpdate({
                      ...step,
                      stopConditionType: condType,
                      stopImage: condType === "image" ? "" : undefined,
                      stopConfidence: condType === "image" ? 0.8 : undefined,
                      stopText: condType === "text" ? "" : undefined
                    } as Step);
                  }}
                >
                  <option value="image">Khi thấy hình ảnh</option>
                  <option value="text">Khi thấy chữ xuất hiện</option>
                </select>
              </div>

              {step.stopConditionType === "image" && (
                <div className="form-group">
                  <label>Độ tin cậy khớp dừng: {step.stopConfidence ?? 0.8}</label>
                  <input
                    type="range"
                    min="0.5"
                    max="1"
                    step="0.05"
                    value={step.stopConfidence ?? 0.8}
                    onChange={(e) => onUpdate({ ...step, stopConfidence: parseFloat(e.target.value) } as Step)}
                  />
                </div>
              )}
            </div>

            {step.stopConditionType === "image" ? (
              <div className="image-upload-wrapper form-section" style={{ border: "none", margin: 0, padding: 0 }}>
                <div className="form-group">
                  <label>Ảnh mẫu điều kiện dừng</label>
                  <div style={{ display: "flex", gap: "10px", marginTop: "4px" }}>
                    <div className="image-upload-box" style={{ flex: 1 }}>
                      <span className="image-upload-text">📁 Chọn file ảnh</span>
                      <input type="file" accept="image/*" onChange={(e) => handleImageUpload(e, "stopImage")} />
                    </div>
                    <button
                      type="button"
                      onClick={async () => {
                        const res = await desktopApi.captureRegion();
                        if (res) {
                          if (isElectronDesktopApi) {
                            const path = await desktopApi.saveImage({ name: "crop-stop-interval.png", base64: res.base64 });
                            onUpdate({ ...step, stopImage: path });
                          } else {
                            onUpdate({ ...step, stopImage: res.base64 });
                          }
                        }
                      }}
                      style={{ background: "rgba(255,255,255,0.06)", border: "1px dashed rgba(255,255,255,0.2)" }}
                    >
                      📷 Chụp trực tiếp
                    </button>
                  </div>
                </div>
                <ImagePreview filePath={step.stopImage} />
              </div>
            ) : (
              <div className="form-group">
                <label>Nhập chữ điều kiện dừng</label>
                <input
                  type="text"
                  value={step.stopText ?? ""}
                  onChange={(e) => onUpdate({ ...step, stopText: e.target.value } as Step)}
                  placeholder="e.g. Thành công"
                />
              </div>
            )}
          </>
        )}

        {step.type === "clear_interval" && (
          <div className="form-group">
            <label>Mã chu kỳ cần dừng (Interval ID)</label>
            <input
              type="text"
              value={step.intervalId}
              onChange={(e) => onUpdate({ ...step, intervalId: e.target.value })}
              placeholder="e.g. check_popup, nhập 'all' để dừng toàn bộ"
            />
          </div>
        )}

        {step.type === "press_key" && (
          <div className="form-grid">
            <div className="form-group">
              <label>Phím cần nhấn</label>
              <select
                value={["f5", "enter", "space", "escape", "tab", "backspace"].includes(step.key.toLowerCase()) ? step.key.toLowerCase() : "custom"}
                onChange={(e) => {
                  const val = e.target.value;
                  onUpdate({ ...step, key: val === "custom" ? "" : val });
                }}
              >
                <option value="f5">F5 (Reload/Refresh)</option>
                <option value="enter">Enter</option>
                <option value="space">Space (Khoảng trắng)</option>
                <option value="escape">Escape (ESC)</option>
                <option value="tab">Tab</option>
                <option value="backspace">Backspace (Xoá ngược)</option>
                <option value="custom">Tự nhập phím khác...</option>
              </select>
            </div>

            {/* Custom key input if custom is selected */}
            {!["f5", "enter", "space", "escape", "tab", "backspace"].includes(step.key.toLowerCase()) && (
              <div className="form-group">
                <label>Nhập tên phím (e.g. f11, a, ctrl, shift)</label>
                <input
                  type="text"
                  value={step.key}
                  onChange={(e) => onUpdate({ ...step, key: e.target.value })}
                  placeholder="e.g. f11, a, alt"
                />
              </div>
            )}
          </div>
        )}

        {step.type === "send_telegram" && (
          <>
            <div className="form-grid">
              <div className="form-group">
                <label>Token Bot Telegram (botToken)</label>
                <input
                  type="text"
                  value={step.botToken}
                  onChange={(e) => onUpdate({ ...step, botToken: e.target.value } as Step)}
                  placeholder="Nhập Token Telegram Bot"
                />
              </div>
              <div className="form-group">
                <label>Chat ID nhận tin (chatId)</label>
                <input
                  type="text"
                  value={step.chatId}
                  onChange={(e) => onUpdate({ ...step, chatId: e.target.value } as Step)}
                  placeholder="Nhập ID cuộc trò chuyện hoặc group"
                />
              </div>
            </div>

            <div className="form-group">
              <label>Nội dung tin nhắn (message)</label>
              <textarea
                value={step.message || ""}
                onChange={(e) => onUpdate({ ...step, message: e.target.value } as Step)}
                placeholder={step.ocrRevenue ? "Doanh thu phiên live: {current}đ. Tổng tích lũy từ đầu: {total}đ" : "Nhập nội dung thông báo kèm theo..."}
                rows={2}
                style={{
                  width: "100%",
                  background: "rgba(0,0,0,0.2)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: "4px",
                  color: "#fff",
                  padding: "8px",
                  fontSize: "14px",
                  fontFamily: "inherit"
                }}
              />
              {step.ocrRevenue && (
                <div style={{ fontSize: "0.8rem", color: "rgba(255,255,255,0.4)", marginTop: "4px", fontStyle: "italic" }}>
                  * Sử dụng {"{current}"} cho doanh thu phiên hiện tại và {"{total}"} cho tổng tích luỹ trong nội dung tin nhắn.
                </div>
              )}
            </div>

            <div className="form-group-checkbox">
              <input
                type="checkbox"
                id={`telegram-ocr-${index}`}
                checked={step.ocrRevenue === true}
                onChange={(e) => {
                  const checked = e.target.checked;
                  onUpdate({
                    ...step,
                    ocrRevenue: checked,
                    captureScreen: checked ? false : step.captureScreen,
                    image: checked ? undefined : step.image
                  } as Step);
                }}
              />
              <label htmlFor={`telegram-ocr-${index}`}>Nhận diện doanh thu bằng OCR (OCR Revenue)</label>
            </div>

            {!step.ocrRevenue && (
              <>
                <div className="form-group-checkbox" style={{ marginTop: "8px" }}>
                  <input
                    type="checkbox"
                    id={`telegram-capture-${index}`}
                    checked={step.captureScreen !== false}
                    onChange={(e) => {
                      const checked = e.target.checked;
                      onUpdate({
                        ...step,
                        captureScreen: checked,
                        image: checked ? undefined : step.image
                      } as Step);
                    }}
                  />
                  <label htmlFor={`telegram-capture-${index}`}>Chụp ảnh màn hình đính kèm (chụp tại thời điểm chạy)</label>
                </div>

                {step.captureScreen === false && (
                  <div className="image-upload-wrapper form-section" style={{ border: "none", margin: "10px 0 0 0", padding: 0 }}>
                    <div className="form-group">
                      <label>Ảnh đính kèm tĩnh (Tải lên hoặc chụp màn hình trước)</label>
                      <div style={{ display: "flex", gap: "10px", marginTop: "4px" }}>
                        <div className="image-upload-box" style={{ flex: 1 }}>
                          <span className="image-upload-text">📁 Chọn file ảnh</span>
                          <input type="file" accept="image/*" onChange={(e) => handleImageUpload(e, "image")} />
                        </div>
                        <button
                          type="button"
                          onClick={async () => {
                            const res = await desktopApi.captureRegion();
                            if (res) {
                              if (isElectronDesktopApi) {
                                const path = await desktopApi.saveImage({ name: "crop-telegram.png", base64: res.base64 });
                                onUpdate({ ...step, image: path } as Step);
                              } else {
                                onUpdate({ ...step, image: res.base64 } as Step);
                              }
                            }
                          }}
                          style={{ background: "rgba(255,255,255,0.06)", border: "1px dashed rgba(255,255,255,0.2)" }}
                        >
                          📷 Chụp trực tiếp
                        </button>
                      </div>
                    </div>
                    <ImagePreview filePath={step.image} />
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* Region config common helper for visual steps */}
        {("region" in step || ["send_telegram", "wait_for_image", "check_text", "click", "double_click", "conditional", "conditional_workflow", "check_interval"].includes(step.type)) && (
          <div className="form-section" style={{ border: "none", margin: 0, padding: 0 }}>
            <div className="form-group-checkbox">
              <input
                type="checkbox"
                id={`check-region-${index}`}
                checked={hasRegion}
                onChange={(e) => {
                  const checked = e.target.checked;
                  setHasRegion(checked);
                  if (checked) {
                    onUpdate({ ...step, region: [0, 0, 1920, 1080] } as Step);
                  } else {
                    const stepCopy = { ...step };
                    // @ts-ignore
                    delete stepCopy.region;
                    onUpdate(stepCopy as Step);
                  }
                }}
              />
              <label htmlFor={`check-region-${index}`}>Giới hạn vùng quét màn hình (Region)</label>
            </div>

            {hasRegion && (
              <div className="form-grid" style={{ marginTop: "4px" }}>
                <div className="form-group">
                  <label>X bắt đầu</label>
                  <input
                    type="number"
                    value={region[0]}
                    onChange={(e) =>
                      onUpdate({
                        ...step,
                        region: [parseInt(e.target.value) || 0, region[1], region[2], region[3]]
                      } as Step)
                    }
                  />
                </div>
                <div className="form-group">
                  <label>Y bắt đầu</label>
                  <input
                    type="number"
                    value={region[1]}
                    onChange={(e) =>
                      onUpdate({
                        ...step,
                        region: [region[0], parseInt(e.target.value) || 0, region[2], region[3]]
                      } as Step)
                    }
                  />
                </div>
                <div className="form-group">
                  <label>Chiều rộng</label>
                  <input
                    type="number"
                    value={region[2]}
                    onChange={(e) =>
                      onUpdate({
                        ...step,
                        region: [region[0], region[1], parseInt(e.target.value) || 0, region[3]]
                      } as Step)
                    }
                  />
                </div>
                <div className="form-group">
                  <label>Chiều cao</label>
                  <input
                    type="number"
                    value={region[3]}
                    onChange={(e) =>
                      onUpdate({
                        ...step,
                        region: [region[0], region[1], region[2], parseInt(e.target.value) || 0]
                      } as Step)
                    }
                  />
                </div>
                <div className="form-group" style={{ gridColumn: "span 4", display: "flex", gap: "8px" }}>
                  <div style={{ flex: 1 }}>
                    <label>Lấy vùng quét di chuột</label>
                    <button
                      type="button"
                      onClick={startRegionCapture}
                      disabled={regionCountdown !== null}
                      style={{ width: "100%", marginTop: "6px", background: regionCountdown !== null ? "#3b82f6" : "rgba(255, 255, 255, 0.08)" }}
                    >
                      {regionCountdown !== null
                        ? (regionPhase === "topleft"
                          ? `Góc TRÊN - TRÁI... (${regionCountdown}s)`
                          : `Góc DƯỚI - PHẢI... (${regionCountdown}s)`)
                        : "🔍 Di chuột 2 góc"}
                    </button>
                  </div>
                  <div style={{ flex: 1 }}>
                    <label>Vẽ vùng quét trực quan</label>
                    <button
                      type="button"
                      onClick={async () => {
                        const res = await desktopApi.captureRegion();
                        if (res) {
                          onUpdate({
                            ...step,
                            region: [res.x, res.y, res.width, res.height]
                          } as Step);
                        }
                      }}
                      style={{ width: "100%", marginTop: "6px", background: "rgba(255, 255, 255, 0.08)" }}
                    >
                      🎯 Vẽ vùng quét (Lightshot)
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function App() {
  const [isCompact, setIsCompact] = useState<boolean>(false);
  const [alwaysOnTop, setAlwaysOnTop] = useState<boolean>(false);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [currentStepIdx, setCurrentStepIdx] = useState<number | null>(null);
  const [failedStepIdx, setFailedStepIdx] = useState<number | null>(null);

  const [workflowText, setWorkflowText] = useState(sampleJson);
  const [loadedPath, setLoadedPath] = useState<string>("");
  const [status, setStatus] = useState<string>("Sẵn sàng");
  const [logs, setLogs] = useState<string[]>([
    "Khởi tạo trình quản lý workflow.",
    "Workflow mẫu được tải ở chế độ chạy thử (dry-run)."
  ]);
  const [savedWorkflows, setSavedWorkflows] = useState<string[]>([]);
  const [workflowNames, setWorkflowNames] = useState<Record<string, string>>({});
  const [activeTab, setActiveTab] = useState<"visual" | "json">("visual");
  const [rightPanelTab, setRightPanelTab] = useState<"summary" | "logs">("summary");


  useEffect(() => {
    async function loadNames() {
      const names: Record<string, string> = {};
      for (const path of savedWorkflows) {
        try {
          const content = await desktopApi.loadWorkflow(path);
          const parsed = JSON.parse(content);
          if (parsed && parsed.name) {
            names[path] = parsed.name;
          } else {
            const filename = path.split(/[/\\]/).pop() || path;
            names[path] = filename.replace(".json", "");
          }
        } catch (err) {
          const filename = path.split(/[/\\]/).pop() || path;
          names[path] = filename.replace(".json", "");
        }
      }
      setWorkflowNames(names);
    }
    if (savedWorkflows.length > 0) {
      loadNames();
    }
  }, [savedWorkflows]);

  useEffect(() => {
    desktopApi
      .listWorkflows()
      .then(setSavedWorkflows)
      .catch(() => {
        setSavedWorkflows([]);
      });
  }, []);

  useEffect(() => {
    if (!isElectronDesktopApi) {
      setStatus("Chạy trên trình duyệt");
      setLogs((current) => [
        "Chế độ Web: Các chức năng thiết kế hoạt động bình thường, nhưng tự động hóa màn hình thực tế cần chạy trên Electron.",
        ...current
      ]);
    }
  }, []);

  useEffect(() => {
    if (!isElectronDesktopApi) return;

    let cleanupStatus = () => {};
    let cleanupLog = () => {};

    if (desktopApi.onStatusChange) {
      cleanupStatus = desktopApi.onStatusChange((status) => {
        if (status === "paused") {
          setIsPaused(true);
          setStatus("⏸️ Tạm dừng (Chờ người dùng dừng thao tác)...");
        } else if (status === "running") {
          setIsPaused(false);
          setStatus("Đang chạy tự động...");
        }
      });
    }

    if (desktopApi.onLog) {
      cleanupLog = desktopApi.onLog((logLine) => {
        setLogs((current) => [logLine, ...current]);
        
        const match = logLine.match(/Step (\d+)\/\d+:/);
        if (match) {
          const stepIdx = parseInt(match[1], 10) - 1;
          setCurrentStepIdx(stepIdx);
        }
        
        if (logLine.includes("ERROR:") || logLine.includes("Traceback") || logLine.includes("TimeoutError") || logLine.includes("RuntimeError")) {
          setCurrentStepIdx((curr) => {
            if (curr !== null) {
              setFailedStepIdx(curr);
            }
            return curr;
          });
        }
      });
    }

    return () => {
      cleanupStatus();
      cleanupLog();
    };
  }, []);

  const toggleCompact = async () => {
    const nextCompact = !isCompact;
    setIsCompact(nextCompact);
    if (nextCompact) {
      if (desktopApi.setWindowSize) {
        await desktopApi.setWindowSize(380, 320);
      }
      setAlwaysOnTop(true);
      if (desktopApi.setWindowAlwaysOnTop) {
        await desktopApi.setWindowAlwaysOnTop(true);
      }
    } else {
      if (desktopApi.setWindowSize) {
        await desktopApi.setWindowSize(1100, 920);
      }
      setAlwaysOnTop(false);
      if (desktopApi.setWindowAlwaysOnTop) {
        await desktopApi.setWindowAlwaysOnTop(false);
      }
    }
  };

  const handleAlwaysOnTopToggle = async (checked: boolean) => {
    setAlwaysOnTop(checked);
    if (desktopApi.setWindowAlwaysOnTop) {
      await desktopApi.setWindowAlwaysOnTop(checked);
    }
  };

  const parsed = useMemo(() => {
    try {
      const json = JSON.parse(workflowText);

      // Auto fill loop properties if not present
      if (json.settings && !json.settings.repeat) {
        json.settings.repeat = { enabled: false, times: 0, intervalMs: 1000 };
      }

      // Ensure schedule is present to satisfy schema but disabled
      if (!json.schedule) {
        json.schedule = { enabled: false, startAt: "", stopAt: "", timezone: "Asia/Ho_Chi_Minh" };
      }
      if (!json.stopSteps) {
        json.stopSteps = [];
      }

      const result = workflowSchema.safeParse(json);
      if (!result.success) {
        return { ok: false as const, error: result.error.issues[0]?.message ?? "Workflow không hợp lệ." };
      }
      return { ok: true as const, value: json as Workflow };
    } catch (error) {
      return { ok: false as const, error: error instanceof Error ? error.message : "Lỗi cú pháp JSON." };
    }
  }, [workflowText]);

  function updateWorkflow(newWorkflow: Workflow) {
    setWorkflowText(JSON.stringify(newWorkflow, null, 2));
  }

  const workflow = parsed.ok ? parsed.value : null;

  function updateSettings<K extends keyof Workflow["settings"]>(field: K, value: Workflow["settings"][K]) {
    if (!workflow) return;
    updateWorkflow({
      ...workflow,
      settings: { ...workflow.settings, [field]: value }
    });
  }

  function updateWorkflowField<K extends keyof Workflow>(field: K, value: Workflow[K]) {
    if (!workflow) return;
    updateWorkflow({
      ...workflow,
      [field]: value
    });
  }

  function updateStep(index: number, updatedStep: Step) {
    if (!workflow) return;
    const newSteps = [...workflow.startSteps];
    newSteps[index] = updatedStep;
    updateWorkflow({ ...workflow, startSteps: newSteps, stopSteps: [] });
  }

  function handleAddStep(type: Step["type"]) {
    if (!workflow) return;
    let newStep: Step;

    if (type === "launch_app") {
      newStep = { type: "launch_app", name: "Mở ứng dụng", command: "" };
    } else if (type === "wait") {
      newStep = { type: "wait", name: "Chờ 1 giây", ms: 1000 };
    } else if (type === "click") {
      newStep = { type: "click", name: "Click chuột", clickType: "coordinate", x: 0, y: 0, delayBeforeSec: 0, delayAfterSec: 0 };
    } else if (type === "double_click") {
      newStep = { type: "double_click", name: "Double click chuột", clickType: "coordinate", x: 0, y: 0, delayBeforeSec: 0, delayAfterSec: 0 };
    } else if (type === "wait_for_image") {

      newStep = { type: "wait_for_image", name: "Đợi ảnh mẫu xuất hiện", image: "", timeoutMs: 5000, confidence: 0.8 };
    } else if (type === "check_text") {
      newStep = { type: "check_text", name: "Kiểm tra chữ màn hình", text: "", timeoutMs: 5000 };
    } else if (type === "run_workflow") {
      newStep = { type: "run_workflow", name: "Chạy workflow con", workflowPath: "" };
    } else if (type === "conditional_workflow") {
      newStep = { type: "conditional_workflow", name: "Rẽ nhánh workflow", conditionType: "image", image: "", confidence: 0.8, thenWorkflowPath: "", elseWorkflowPath: "" };
    } else if (type === "check_interval") {
      newStep = { type: "check_interval", name: "Lặp chu kỳ kiểm tra", intervalId: "loop_" + Math.random().toString(36).substr(2, 5), intervalSec: 5, actionWorkflowPath: "", stopConditionType: "image", stopImage: "", stopConfidence: 0.8 };
    } else if (type === "clear_interval") {
      newStep = { type: "clear_interval", name: "Dừng lặp chu kỳ", intervalId: "" };
    } else if (type === "press_key") {
      newStep = { type: "press_key", name: "Nhấn phím bàn phím", key: "f5" };
    } else if (type === "send_telegram") {
      newStep = { type: "send_telegram", name: "Gửi báo cáo Telegram", botToken: "", chatId: "", message: "Báo cáo kết quả", captureScreen: true, ocrRevenue: false, region: undefined };
    } else {
      newStep = {
        type: "conditional",
        name: "Kiểm tra điều kiện (IF)",
        conditionType: "image",
        image: "",
        confidence: 0.8,
        actionType: "click",
        clickX: 0,
        clickY: 0
      };
    }

    updateWorkflow({ ...workflow, startSteps: [...workflow.startSteps, newStep], stopSteps: [] });
    setLogs((current) => [`Đã thêm bước mới [${type}].`, ...current]);
  }

  function handleDeleteStep(index: number) {
    if (!workflow) return;
    const newSteps = workflow.startSteps.filter((_, i) => i !== index);
    updateWorkflow({ ...workflow, startSteps: newSteps, stopSteps: [] });
    setLogs((current) => [`Đã xoá bước thứ ${index + 1}.`, ...current]);
  }

  function handleMoveStep(index: number, direction: "up" | "down") {
    if (!workflow) return;
    const newSteps = [...workflow.startSteps];
    const targetIndex = direction === "up" ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= newSteps.length) return;

    const temp = newSteps[index];
    newSteps[index] = newSteps[targetIndex];
    newSteps[targetIndex] = temp;
    updateWorkflow({ ...workflow, startSteps: newSteps, stopSteps: [] });
  }

  async function handleSave() {
    if (!parsed.ok) {
      setStatus(`Không thể lưu: ${parsed.error}`);
      return;
    }

    try {
      const oldFilename = loadedPath ? loadedPath.split(/[/\\]/).pop() || "" : "";
      const newSafeName = parsed.value.name.replace(/[^a-z0-9-_]+/gi, "-").toLowerCase() + ".json";
      
      let filePathToSave = loadedPath || undefined;
      let oldFileToDelete = null;

      if (loadedPath && oldFilename && !loadedPath.startsWith("browser://") && oldFilename.toLowerCase() !== newSafeName.toLowerCase()) {
        const separator = loadedPath.includes("\\") ? "\\" : "/";
        const parts = loadedPath.split(separator);
        parts.pop();
        filePathToSave = [...parts, newSafeName].join(separator);
        oldFileToDelete = loadedPath;
      }

      const path = await desktopApi.saveWorkflow({
        name: parsed.value.name,
        content: workflowText,
        filePath: filePathToSave
      });

      if (path) {
        if (oldFileToDelete) {
          try {
            const success = isElectronDesktopApi
              ? await window.desktopApi?.deleteWorkflow(oldFileToDelete)
              : await desktopApi.deleteWorkflow(oldFileToDelete);
            if (success) {
              setLogs((current) => [`Đã dọn dẹp file cũ: ${oldFileToDelete}`, ...current]);
            }
          } catch (delErr) {
            console.error("Failed to delete old file during rename:", delErr);
          }
        }
        setLoadedPath(path);
        setSavedWorkflows(await desktopApi.listWorkflows());

        const relativePath = path.replace(window.location.origin, "");
        setStatus(`Đã lưu tại ${relativePath}`);
        setLogs((current) => [`Lưu thành công tại ${relativePath}`, ...current]);
      } else {
        setStatus("Không thể lưu quy trình.");
      }
    } catch (err) {
      console.error("Error saving workflow:", err);
      setStatus("Lỗi khi lưu quy trình.");
    }
  }


  async function handleLoad(filePath?: string) {
    const target = filePath ?? (await desktopApi.pickWorkflowFile());
    if (!target) {
      if (!isElectronDesktopApi) {
        setStatus("Chức năng chỉ hoạt động trên Electron");
      }
      return;
    }
    const content = await desktopApi.loadWorkflow(target);
    setWorkflowText(content);
    setLoadedPath(target);
    setStatus(`Đã tải ${target}`);
    setLogs((current) => [`Đã tải workflow từ ${target}.`, ...current]);
  }

  function handleCreateNewWorkflow() {
    const newWorkflow: Workflow = {
      name: "Quy trình mới",
      description: "Quy trình tự động hóa mới.",
      schedule: { enabled: false, startAt: "", stopAt: "", timezone: "Asia/Ho_Chi_Minh" },
      settings: {
        dryRun: true,
        retryCount: 0,
        captureOnError: true,
        stepDelaySec: 0,
        repeat: { enabled: false, times: 0, intervalMs: 1000 }
      },
      startSteps: [],
      stopSteps: []
    };
    setWorkflowText(JSON.stringify(newWorkflow, null, 2));
    setLoadedPath("");
    setStatus("Đã tạo quy trình mới (chưa lưu)");
    setLogs((current) => ["Tạo quy trình mới thành công.", ...current]);
  }

  async function handleDeleteWorkflow(filePath: string) {
    if (!window.confirm("Bạn có chắc chắn muốn xóa quy trình này?")) {
      return;
    }

    try {
      const success = isElectronDesktopApi
        ? await window.desktopApi?.deleteWorkflow(filePath)
        : await desktopApi.deleteWorkflow(filePath);
      
      if (success) {
        setLogs((current) => [`Đã xóa quy trình: ${filePath}`, ...current]);
        setStatus("Xóa quy trình thành công");
        
        // Refresh list
        const updated = await desktopApi.listWorkflows();
        setSavedWorkflows(updated);

        if (loadedPath === filePath) {
          handleCreateNewWorkflow();
        }
      } else {
        setStatus("Không thể xóa quy trình.");
      }
    } catch (err) {
      console.error("Error deleting workflow:", err);
      setStatus("Lỗi khi xóa quy trình.");
    }
  }


  async function handleRun() {
    if (!parsed.ok) {
      setStatus(`Không thể chạy: ${parsed.error}`);
      return;
    }

    setIsRunning(true);
    setIsPaused(false);
    setCurrentStepIdx(null);
    setFailedStepIdx(null);
    setStatus("Đang chạy tự động...");
    setLogs((current) => [`Trình chạy bắt đầu lúc ${new Date().toLocaleTimeString()}.`, ...current]);
    try {
      const result = await desktopApi.runWorkflow({ workflow: workflowText });
      if (!isElectronDesktopApi) {
        const chunks = [result.stdout.trim(), result.stderr.trim()].filter(Boolean);
        setLogs((current) => [...chunks.reverse(), ...current]);
      }
      setStatus(result.code === 0 ? "Chạy hoàn tất thành công" : `Lỗi runner, mã thoát: ${result.code}`);
    } catch (err) {
      setStatus(`Lỗi: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setIsRunning(false);
      setIsPaused(false);
    }
  }

  async function handleStop() {
    try {
      setStatus("Đang dừng quy trình...");
      const success = isElectronDesktopApi
        ? await window.desktopApi?.stopWorkflow()
        : await desktopApi.stopWorkflow();
      if (success) {
        setStatus("Quy trình đã dừng.");
        setLogs((current) => ["Đã dừng quy trình theo yêu cầu.", ...current]);
      } else {
        setStatus("Không thể dừng quy trình (hoặc quy trình đã kết thúc).");
      }
    } catch (err) {
      setStatus(`Lỗi khi dừng: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  if (isCompact) {
    const latestLog = logs[0] || "Chưa có nhật ký hoạt động nào.";
    const statusDotClass = isRunning 
      ? (isPaused ? "paused" : "running") 
      : status.includes("Lỗi") 
      ? "error" 
      : status.includes("thành công") 
      ? "success" 
      : "idle";

    return (
      <div className="compact-container">
        <header className="compact-header">
          <h3>🤖 Auto Mini</h3>
          <div className="compact-header-actions">
            <button className="compact-btn expand-btn" onClick={toggleCompact}>
              🗖 Phóng to
            </button>
          </div>
        </header>
        <div className="compact-body">
          <div className="compact-row">
            <label>Quy trình chạy</label>
            <select
              className="compact-select"
              value={loadedPath}
              onChange={(e) => handleLoad(e.target.value)}
            >
              <option value="" disabled>-- Chọn quy trình --</option>
              {savedWorkflows.map((path) => {
                const filename = path.split(/[/\\]/).pop() || path;
                const displayName = workflowNames[path] || filename.replace(".json", "");
                return (
                  <option key={path} value={path}>
                    {displayName}
                  </option>
                );
              })}
            </select>
          </div>

          <div className="compact-options-grid">
            <label className="compact-checkbox-label">
              <input
                type="checkbox"
                checked={workflow?.settings.dryRun ?? false}
                disabled={!workflow}
                onChange={(e) => updateSettings("dryRun", e.target.checked)}
              />
              Chạy thử
            </label>
            <label className="compact-checkbox-label">
              <input
                type="checkbox"
                checked={alwaysOnTop}
                onChange={(e) => handleAlwaysOnTopToggle(e.target.checked)}
              />
              Ghim cửa sổ
            </label>
          </div>

          <div>
            {isRunning ? (
              <button 
                className={`compact-action-btn stop-btn ${isPaused ? "paused" : ""}`} 
                onClick={handleStop} 
                style={{ 
                  backgroundColor: isPaused ? "#f59e0b" : "#dc3545", 
                  color: "#fff",
                  transition: "all 0.3s ease"
                }}
              >
                {isPaused ? "⏸️ Tạm dừng (Dừng)" : "🛑 Dừng quy trình"}
              </button>
            ) : (
              <button className="compact-action-btn run-btn" onClick={handleRun} disabled={!workflow}>
                ▶ Chạy quy trình
              </button>
            )}
          </div>

          <div className="compact-status-panel">
            <div className="compact-status-header">
              <div className="compact-status-indicator">
                <span className={`compact-status-dot ${statusDotClass}`}></span>
                <span>{status}</span>
              </div>
            </div>
            <div className="compact-log-title">Log mới nhất:</div>
            <div className="compact-log-box">
              {latestLog}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      {/* Sidebar (Left column) */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h2>📂 Quy trình</h2>
          <button className="create-btn" onClick={handleCreateNewWorkflow} title="Tạo quy trình mới">
            +
          </button>
        </div>
        <div className="sidebar-content">
          <ul className="workflow-list">
            {savedWorkflows.map((path) => {
              const filename = path.split(/[/\\]/).pop() || path;
              const isActive = loadedPath === path;
              const displayName = path === loadedPath && workflow 
                ? workflow.name 
                : (workflowNames[path] || filename.replace(".json", ""));
              return (
                <li key={path} className={`workflow-item ${isActive ? "active" : ""}`}>
                  <span className="workflow-name" onClick={() => handleLoad(path)} title={path}>
                    📄 {displayName}
                  </span>
                  <button className="delete-item-btn" onClick={(e) => { e.stopPropagation(); handleDeleteWorkflow(path); }} title="Xóa quy trình">
                    🗑️
                  </button>
                </li>
              );
            })}
            {savedWorkflows.length === 0 && (
              <div className="no-workflows">Chưa có quy trình nào</div>
            )}
          </ul>
        </div>
        <div className="sidebar-footer">
          <button className="import-btn" onClick={() => handleLoad()}>📁 Nhập file JSON</button>
        </div>
      </aside>

      {/* Main Workspace (Editor + Console) */}
      <main className="workspace">
        {/* Editor (Middle panel) */}
        <section className="editor-panel">
          <div className="panelHeader">
            <div>
              {workflow ? (
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <input
                    type="text"
                    value={workflow.name}
                    onChange={(e) => updateWorkflowField("name", e.target.value)}
                    className="workflow-name-header-input"
                    style={{
                      background: "transparent",
                      border: "none",
                      borderBottom: "1px dashed rgba(255,255,255,0.3)",
                      color: "#fff",
                      fontSize: "1.5rem",
                      fontWeight: "bold",
                      padding: "2px 4px",
                      margin: 0,
                      outline: "none",
                      width: "350px"
                    }}
                    placeholder="Nhập tên quy trình..."
                  />
                </div>
              ) : (
                <h2>Thiết kế Quy trình</h2>
              )}
              <p style={{ margin: "2px 0 0", opacity: 0.6, fontSize: "0.85rem" }}>
                {loadedPath ? `Đường dẫn: ${loadedPath.replace(window.location.origin, "")}` : "Tệp cấu hình chưa lưu"}
              </p>
            </div>
            <div className="actions">
              <button onClick={toggleCompact} title="Chuyển sang giao diện Mini thu nhỏ">🗕 Giao diện Mini</button>
              <button onClick={() => setWorkflowText(sampleJson)}>Reset Mẫu</button>
              <button className="primary" onClick={handleSave}>
                Lưu
              </button>
              {isRunning ? (
                <button 
                  className={`stop-btn ${isPaused ? "paused" : ""}`} 
                  onClick={handleStop} 
                  style={{ 
                    backgroundColor: isPaused ? "#f59e0b" : "#dc3545", 
                    color: "#fff",
                    transition: "all 0.3s ease"
                  }}
                >
                  {isPaused ? "⏸️ Tạm dừng (Dừng)" : "Dừng"}
                </button>
              ) : (
                <button className="accent" onClick={handleRun}>
                  Chạy
                </button>
              )}
            </div>
          </div>

          {/* Main Tabs Navigation */}
          <div className="tabs-nav">
            <button
              className={`tab-btn ${activeTab === "visual" ? "active" : ""}`}
              onClick={() => setActiveTab("visual")}
            >
              🛠️ Thiết kế trực quan
            </button>
            <button
              className={`tab-btn ${activeTab === "json" ? "active" : ""}`}
              onClick={() => setActiveTab("json")}
            >
              {`{ }`} Mã JSON Cấu hình
            </button>
          </div>

          {/* Tab contents */}
          <div className="editor-content-wrapper">
            {activeTab === "json" ? (
              <textarea
                className="editor"
                value={workflowText}
                onChange={(event) => setWorkflowText(event.target.value)}
                spellCheck={false}
              />
            ) : !workflow ? (
              <div className="card panel" style={{ border: "1px dashed #ef4444", textAlign: "center", padding: "30px" }}>
                <h3 style={{ color: "#ef4444", margin: "0 0 10px" }}>Cú pháp JSON bị lỗi</h3>
                <p style={{ color: "rgba(255,255,255,0.7)", fontSize: "0.9rem" }}>
                  Bản dựng trực quan không thể hiển thị vì mã JSON hiện tại không hợp lệ.
                </p>
                <p style={{ color: "#ff9e9e", fontSize: "0.85rem", background: "rgba(0,0,0,0.2)", padding: "10px", borderRadius: "8px" }}>
                  {parsed.error}
                </p>
                <div style={{ marginTop: "20px" }}>
                  <button onClick={() => setActiveTab("json")} style={{ marginRight: "10px" }}>
                    Sửa mã JSON
                  </button>
                  <button className="accent" onClick={() => setWorkflowText(sampleJson)}>
                    Reset về mẫu chuẩn
                  </button>
                </div>
              </div>
            ) : (
              <div className="visual-editor-scroll">
                {/* General Mode Settings */}
                <div className="form-section">
                  <h3 className="form-section-title">⚙️ Cấu hình chung</h3>
                  <div className="form-grid">
                    <div className="form-group" style={{ gridColumn: "span 2" }}>
                      <label>Tên quy trình</label>
                      <input
                        type="text"
                        value={workflow.name}
                        onChange={(e) => updateWorkflowField("name", e.target.value)}
                        placeholder="Nhập tên quy trình"
                      />
                    </div>
                    <div className="form-group" style={{ gridColumn: "span 2" }}>
                      <label>Mô tả quy trình</label>
                      <textarea
                        value={workflow.description ?? ""}
                        onChange={(e) => updateWorkflowField("description", e.target.value)}
                        placeholder="Nhập mô tả quy trình"
                        style={{ minHeight: "60px", resize: "vertical" }}
                      />
                    </div>
                    <div className="form-group">
                      <label>Chế độ chạy thử (Dry Run)</label>
                      <select
                        value={workflow.settings.dryRun ? "true" : "false"}
                        onChange={(e) => updateSettings("dryRun", e.target.value === "true")}
                      >
                        <option value="true">Bật (Chỉ mô phỏng hành động, an toàn)</option>
                        <option value="false">Tắt (Thực hiện CLICK chuột và MỞ APP thật)</option>
                      </select>
                    </div>
                    <div className="form-group">
                      <label>Số lần thử lại khi lỗi</label>
                      <input
                        type="number"
                        min="0"
                        max="10"
                        value={workflow.settings.retryCount}
                        onChange={(e) => updateSettings("retryCount", parseInt(e.target.value) || 0)}
                      />
                    </div>
                    <div className="form-group">
                      <label>Thời gian trễ giữa các bước (giây)</label>
                      <input
                        type="number"
                        min="0"
                        step="0.1"
                        value={workflow.settings.stepDelaySec ?? 0}
                        onChange={(e) => updateSettings("stepDelaySec", parseFloat(e.target.value) || 0)}
                      />
                    </div>
                  </div>
                </div>

                {/* Looping / Repeat settings */}
                <div className="form-section">
                  <h3 className="form-section-title">🔁 Lặp lại quy trình (Loop)</h3>
                  <div className="form-group-checkbox">
                    <input
                      type="checkbox"
                      id="repeat-enabled"
                      checked={workflow.settings.repeat?.enabled ?? false}
                      onChange={(e) => {
                        const enabled = e.target.checked;
                        const currentRepeat = workflow.settings.repeat || { enabled: false, times: 0, intervalMs: 1000 };
                        updateSettings("repeat", { ...currentRepeat, enabled });
                      }}
                    />
                    <label htmlFor="repeat-enabled" style={{ fontSize: "1rem", fontWeight: "bold" }}>
                      Chạy lặp lại liên tục quy trình này
                    </label>
                  </div>

                  {(workflow.settings.repeat?.enabled) && (
                    <div className="form-grid" style={{ marginTop: "12px" }}>
                      <div className="form-group">
                        <label>Số lần lặp lại (Nhập 0 để lặp vô tận)</label>
                        <input
                          type="number"
                          min="0"
                          value={workflow.settings.repeat?.times ?? 0}
                          onChange={(e) => {
                            const times = parseInt(e.target.value) || 0;
                            const currentRepeat = workflow.settings.repeat || { enabled: true, times: 0, intervalMs: 1000 };
                            updateSettings("repeat", { ...currentRepeat, times });
                          }}
                        />
                      </div>
                      <div className="form-group">
                        <label>Thời gian nghỉ giữa các lần lặp (giây)</label>
                        <input
                          type="number"
                          min="1"
                          value={(workflow.settings.repeat?.intervalMs ?? 1000) / 1000}
                          onChange={(e) => {
                            const sec = parseFloat(e.target.value) || 1;
                            const currentRepeat = workflow.settings.repeat || { enabled: true, times: 0, intervalMs: 1000 };
                            updateSettings("repeat", { ...currentRepeat, intervalMs: sec * 1000 });
                          }}
                        />
                      </div>
                    </div>
                  )}
                </div>

                {/* Global Telegram Alerts settings */}
                <div className="form-section">
                  <h3 className="form-section-title">📢 Báo cáo trạng thái qua Telegram</h3>
                  
                  <div className="form-grid">
                    <div className="form-group">
                      <label>Tên máy này (deviceName)</label>
                      <input
                        type="text"
                        value={workflow.settings.deviceName || ""}
                        onChange={(e) => updateSettings("deviceName", e.target.value)}
                        placeholder="Ví dụ: máy 1"
                      />
                    </div>
                    <div className="form-group">
                      <label>Token Bot Telegram</label>
                      <input
                        type="text"
                        value={workflow.settings.telegramBotToken || ""}
                        onChange={(e) => updateSettings("telegramBotToken", e.target.value)}
                        placeholder="Token của Bot nhận tin nhắn"
                      />
                    </div>
                    <div className="form-group">
                      <label>Chat ID nhận báo cáo</label>
                      <input
                        type="text"
                        value={workflow.settings.telegramChatId || ""}
                        onChange={(e) => updateSettings("telegramChatId", e.target.value)}
                        placeholder="ID cuộc trò chuyện hoặc group"
                      />
                    </div>
                  </div>

                  <div className="form-grid" style={{ marginTop: "10px", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
                    <div className="form-group-checkbox">
                      <input
                        type="checkbox"
                        id="setting-report-startup"
                        checked={workflow.settings.reportStartup ?? false}
                        onChange={(e) => updateSettings("reportStartup", e.target.checked)}
                      />
                      <label htmlFor="setting-report-startup" style={{ marginLeft: "6px" }}>Báo Telegram khi BẮT ĐẦU chạy tool</label>
                    </div>
                    <div className="form-group-checkbox">
                      <input
                        type="checkbox"
                        id="setting-report-error"
                        checked={workflow.settings.reportError ?? false}
                        onChange={(e) => updateSettings("reportError", e.target.checked)}
                      />
                      <label htmlFor="setting-report-error" style={{ marginLeft: "6px" }}>Báo Telegram khi xảy ra LỖI trong quá trình chạy</label>
                    </div>
                  </div>
                </div>

                {/* Window Layout settings */}
                <div className="form-section">
                  <h3 className="form-section-title">🖥️ Cố định vị trí cửa sổ (Window Layout)</h3>
                  <p style={{ fontSize: "0.82rem", color: "rgba(255,255,255,0.5)", margin: "0 0 10px 0" }}>
                    Chụp lại vị trí và kích thước của các cửa sổ ứng dụng (trừ chính tool này) để khi chạy tool sẽ tự động khôi phục lại vị trí cũ, giúp click toạ độ chuẩn xác tuyệt đối.
                  </p>
                  
                  <div style={{ marginBottom: "12px" }}>
                    <button
                      type="button"
                      onClick={async () => {
                        if (desktopApi.captureWindowLayout) {
                          setStatus("Đang quét các cửa sổ...");
                          try {
                            const layout = await desktopApi.captureWindowLayout();
                            updateSettings("windowLayout", layout);
                            setStatus(`Đã lưu bố cục của ${layout.length} cửa sổ`);
                            setLogs((current) => [`Đã chụp bố cục cửa sổ hiện tại (${layout.length} cửa sổ).`, ...current]);
                          } catch (err) {
                            console.error("Lỗi khi chụp bố cục cửa sổ:", err);
                            setStatus("Lỗi khi chụp bố cục cửa sổ.");
                          }
                        }
                      }}
                      style={{ background: "rgba(20, 184, 166, 0.15)", borderColor: "#14b8a6", color: "#14b8a6" }}
                    >
                      📷 Chụp & Lưu Vị Trí Cửa Sổ Hiện Tại
                    </button>
                  </div>

                  {workflow.settings.windowLayout && workflow.settings.windowLayout.length > 0 ? (
                    <div style={{ background: "rgba(0,0,0,0.2)", borderRadius: "8px", padding: "10px", border: "1px solid rgba(255,255,255,0.05)", overflowX: "auto" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
                        <thead>
                          <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.1)", textAlign: "left" }}>
                            <th style={{ padding: "6px" }}>Bật</th>
                            <th style={{ padding: "6px" }}>Tên Cửa Sổ (Title)</th>
                            <th style={{ padding: "6px" }}>Toạ độ (X, Y)</th>
                            <th style={{ padding: "6px" }}>Kích thước (W x H)</th>
                            <th style={{ padding: "6px" }}>Hành động</th>
                          </tr>
                        </thead>
                        <tbody>
                          {workflow.settings.windowLayout.map((win, idx) => (
                            <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                              <td style={{ padding: "6px" }}>
                                <input
                                  type="checkbox"
                                  checked={win.enabled}
                                  onChange={(e) => {
                                    const nextLayout = [...(workflow.settings.windowLayout || [])];
                                    nextLayout[idx] = { ...win, enabled: e.target.checked };
                                    updateSettings("windowLayout", nextLayout);
                                  }}
                                  style={{ cursor: "pointer" }}
                                />
                              </td>
                              <td style={{ padding: "6px" }}>
                                <input
                                  type="text"
                                  value={win.title}
                                  onChange={(e) => {
                                    const nextLayout = [...(workflow.settings.windowLayout || [])];
                                    nextLayout[idx] = { ...win, title: e.target.value };
                                    updateSettings("windowLayout", nextLayout);
                                  }}
                                  style={{
                                    background: "transparent",
                                    border: "none",
                                    borderBottom: "1px dashed rgba(255,255,255,0.2)",
                                    color: win.enabled ? "#fff" : "rgba(255,255,255,0.4)",
                                    fontSize: "0.82rem",
                                    width: "100%",
                                    padding: "2px"
                                  }}
                                />
                              </td>
                              <td style={{ padding: "6px", color: win.enabled ? "#14b8a6" : "rgba(255,255,255,0.4)" }}>
                                {win.x}, {win.y}
                              </td>
                              <td style={{ padding: "6px", color: win.enabled ? "#14b8a6" : "rgba(255,255,255,0.4)" }}>
                                {win.width} x {win.height}
                              </td>
                              <td style={{ padding: "6px" }}>
                                <button
                                  type="button"
                                  onClick={() => {
                                    const nextLayout = (workflow.settings.windowLayout || []).filter((_, i) => i !== idx);
                                    updateSettings("windowLayout", nextLayout);
                                  }}
                                  style={{ background: "transparent", border: "none", color: "#ef4444", padding: "0 4px", fontSize: "0.8rem" }}
                                >
                                  Xoá
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div style={{ fontStyle: "italic", color: "rgba(255,255,255,0.3)", fontSize: "0.8rem", textAlign: "center", padding: "10px", border: "1px dashed rgba(255,255,255,0.1)", borderRadius: "8px" }}>
                      Chưa lưu bố cục cửa sổ nào.
                    </div>
                  )}
                </div>

                {/* Steps Section */}
                <div>
                  <h3 className="form-section-title">🛠️ Danh sách các bước thực hiện</h3>
                  <div className="steps-container">
                    {workflow.startSteps.map((step, idx) => (
                      <StepCard
                        key={`${step.type}-${idx}`}
                        step={step}
                        index={idx}
                        onUpdate={(updated) => updateStep(idx, updated)}
                        onDelete={() => handleDeleteStep(idx)}
                        onMoveUp={() => handleMoveStep(idx, "up")}
                        onMoveDown={() => handleMoveStep(idx, "down")}
                        isFirst={idx === 0}
                        isLast={idx === workflow.startSteps.length - 1}
                        savedWorkflows={savedWorkflows}
                        workflowNames={workflowNames}
                      />
                    ))}

                    {/* Step list is empty */}
                    {workflow.startSteps.length === 0 && (
                      <div style={{ textAlign: "center", padding: "20px", color: "rgba(255,255,255,0.4)", border: "1px dashed rgba(255,255,255,0.1)", borderRadius: "12px" }}>
                        Chưa có hành động nào. Vui lòng chọn một hành động bên dưới để thêm.
                      </div>
                    )}

                    {/* Add action selectors */}
                    <div className="step-card-add-actions">
                      <button type="button" onClick={() => handleAddStep("launch_app")}>
                        + Mở ứng dụng
                      </button>
                      <button type="button" onClick={() => handleAddStep("wait")}>
                        + Chờ thời gian
                      </button>
                      <button type="button" onClick={() => handleAddStep("click")}>
                        + Click chuột
                      </button>
                      <button type="button" onClick={() => handleAddStep("double_click")}>
                        + Double click
                      </button>

                      <button type="button" onClick={() => handleAddStep("wait_for_image")}>
                        + Đợi ảnh mẫu
                      </button>
                      <button type="button" onClick={() => handleAddStep("check_text")}>
                        + Kiểm tra chữ
                      </button>
                      <button type="button" onClick={() => handleAddStep("conditional")} style={{ background: "rgba(233, 30, 99, 0.15)", borderColor: "rgba(233, 30, 99, 0.3)" }}>
                        + Kiểm tra (IF)
                      </button>
                      <button type="button" onClick={() => handleAddStep("run_workflow")} style={{ background: "rgba(168, 85, 247, 0.15)", borderColor: "rgba(168, 85, 247, 0.3)" }}>
                        + Chạy Flow Con
                      </button>
                      <button type="button" onClick={() => handleAddStep("conditional_workflow")} style={{ background: "rgba(219, 39, 119, 0.15)", borderColor: "rgba(219, 39, 119, 0.3)" }}>
                        + Rẽ Nhánh Flow
                      </button>
                      <button type="button" onClick={() => handleAddStep("check_interval")} style={{ background: "rgba(6, 182, 212, 0.15)", borderColor: "rgba(6, 182, 212, 0.3)" }}>
                        + Lặp Chu Kỳ
                      </button>
                      <button type="button" onClick={() => handleAddStep("clear_interval")} style={{ background: "rgba(239, 68, 68, 0.15)", borderColor: "rgba(239, 68, 68, 0.3)" }}>
                        + Dừng Chu Kỳ
                      </button>
                      <button type="button" onClick={() => handleAddStep("press_key")} style={{ background: "rgba(249, 115, 22, 0.15)", borderColor: "rgba(249, 115, 22, 0.3)" }}>
                        + Nhấn Phím
                      </button>
                      <button type="button" onClick={() => handleAddStep("send_telegram")} style={{ background: "rgba(16, 185, 129, 0.15)", borderColor: "rgba(16, 185, 129, 0.3)" }}>
                        + Gửi Telegram
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* Console / Right Panel (Combined logs & summary with switcher) */}
        <aside className="console-panel">
          <div className="console-tabs">
            <button
              className={`console-tab-btn ${rightPanelTab === "summary" ? "active" : ""}`}
              onClick={() => setRightPanelTab("summary")}
            >
              📋 Tóm tắt luồng
            </button>
            <button
              className={`console-tab-btn ${rightPanelTab === "logs" ? "active" : ""}`}
              onClick={() => setRightPanelTab("logs")}
            >
              🖥️ Nhật ký (Logs)
            </button>
          </div>

          <div className="console-content">
            {rightPanelTab === "summary" ? (
              <div className="summary-tab-content">
                {parsed.ok ? (
                  <>
                    <div className="summaryGrid">
                      <div>
                        <strong>Chế độ chạy</strong>
                        <span>{parsed.value.settings.dryRun ? "Dry Run (Mô phỏng)" : "Live (Thực tế)"}</span>
                      </div>
                      <div>
                        <strong>Lặp lại</strong>
                        <span>
                          {parsed.value.settings.repeat?.enabled
                            ? `Lặp ${parsed.value.settings.repeat.times === 0 ? "vô hạn" : `${parsed.value.settings.repeat.times} lần`} (Nghỉ ${(parsed.value.settings.repeat.intervalMs / 1000)}s)`
                            : "Tắt lặp"}
                        </span>
                      </div>
                    </div>
                    <div style={{ fontWeight: "bold", margin: "14px 0 8px", fontSize: "0.9rem" }}>
                      Trình tự ({parsed.value.startSteps.length} bước):
                    </div>
                    <ul className="stepList">
                      {parsed.value.startSteps.map((step, index) => {
                        const isStepCoord = 
                          (step.type === "click" && (!step.clickType || step.clickType === "coordinate")) ||
                          (step.type === "double_click" && (!step.clickType || step.clickType === "coordinate")) ||
                          (step.type === "conditional" && (step.actionType === "click" || step.actionType === "double_click"));
                        
                        const isCurrent = index === currentStepIdx;
                        const isFailed = index === failedStepIdx;
                        
                        let liClass = "";
                        if (isCurrent) liClass = "step-running";
                        else if (isFailed) liClass = "step-failed";
                        else if (isStepCoord) liClass = "coordinate-warning";

                        return (
                          <li key={`${step.type}-${index}`} className={liClass}>
                            <span 
                              className="stepIndex"
                              style={{
                                background: isFailed ? "#ef4444" : isCurrent ? "#14b8a6" : undefined,
                                color: isFailed || isCurrent ? "#080908" : undefined
                              }}
                            >
                              {String(index + 1).padStart(2, "0")}
                            </span>
                            <div>
                              <strong>{step.name}</strong>
                              {isStepCoord && (
                                <span style={{ color: "#f59e0b", fontSize: "0.78rem", fontWeight: "bold", marginLeft: "6px" }}>
                                  ⚠️ Cần sửa
                                </span>
                              )}
                            <p style={{ textTransform: "capitalize", fontSize: "0.82rem", margin: "2px 0 0", opacity: 0.7 }}>
                              {step.type === "launch_app" && "Chạy App"}
                              {step.type === "wait" && `Chờ ${(step.ms / 1000)}s`}
                              {step.type === "click" && `Click (${(step.clickType || "coordinate") === "coordinate" ? `Toạ độ ${step.x},${step.y}` : (step.clickType === "text" ? `Chữ: "${step.text}"` : "Khớp hình ảnh")})`}
                              {step.type === "double_click" && `Double Click (${(step.clickType || "coordinate") === "coordinate" ? `Toạ độ ${step.x},${step.y}` : (step.clickType === "text" ? `Chữ: "${step.text}"` : "Khớp hình ảnh")})`}
                              {step.type === "wait_for_image" && "Đợi hình ảnh"}
                              {step.type === "check_text" && `Kiểm tra chữ: "${step.text}"`}
                              {step.type === "conditional" && `Kiểm tra: Nếu thấy ${step.conditionType === "image" ? "ảnh" : `chữ "${step.text}"`} thì ${step.actionType}`}
                              {step.type === "run_workflow" && `Chạy Flow Con: ${step.workflowPath ? (step.workflowPath.split(/[/\\]/).pop() || step.workflowPath) : "(Chưa chọn)"}`}
                              {step.type === "conditional_workflow" && `Rẽ Nhánh Flow: Nếu thấy ${step.conditionType === "image" ? "ảnh" : `chữ "${step.text}"`} thì chạy Flow Con`}
                              {step.type === "check_interval" && `Lặp Chu Kỳ: Chạy mỗi ${step.intervalSec}s cho đến khi dừng`}
                              {step.type === "clear_interval" && `Dừng Chu Kỳ: ${step.intervalId || "(Chưa nhập ID)"}`}
                              {step.type === "press_key" && `Nhấn phím: ${step.key.toUpperCase()}`}
                            </p>
                          </div>
                        </li>
                      )})}
                      {parsed.value.startSteps.length === 0 && (
                        <p style={{ color: "rgba(255,255,255,0.4)", fontSize: "0.85rem" }}>Chưa có hành động nào.</p>
                      )}
                    </ul>
                  </>
                ) : (
                  <p className="errorText">{parsed.error}</p>
                )}
              </div>
            ) : (
              <div className="logBox">
                {logs.map((line, index) => (
                  <pre key={`${line}-${index}`}>{line}</pre>
                ))}
              </div>
            )}
          </div>
        </aside>
      </main>

      {/* Bottom Status bar */}
      <footer className="status-bar">
        <span className="status-text">👉 Trạng thái: {status}</span>
        <span className={`validity-indicator ${parsed.ok ? "valid" : "invalid"}`}>
          {parsed.ok ? "🟢 Cấu hình hợp lệ" : `🔴 Lỗi: ${parsed.error}`}
        </span>
      </footer>
    </div>
  );
}

export default App;

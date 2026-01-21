import { createSignal, createEffect, onMount, onCleanup, Show } from "solid-js";
import type { Emoji, CapturedEmoji, Settings } from "../lib/api";
import { previewCapture, saveCapture, deleteCapture } from "../lib/api";
import { startWebcam, stopWebcam, captureFrame } from "../lib/webcam";

interface CaptureModalProps {
  sessionId: string;
  emoji: Emoji;
  existingCapture?: CapturedEmoji;
  emojis: Emoji[];
  isCustom?: boolean;
  settings: Settings;
  onSettingsChange: (settings: Settings) => void;
  onComplete: () => void;
  onClose: () => void;
  onNext?: () => void;
}

type CaptureState = "webcam" | "preview" | "processing";

function CaptureModal(props: CaptureModalProps) {
  let videoRef: HTMLVideoElement | undefined;
  let stream: MediaStream | undefined;
  let fileInputRef: HTMLInputElement | undefined;
  let referenceContainerRef: HTMLDivElement | undefined;

  const [referenceWidth, setReferenceWidth] = createSignal(200);

  const [state, setState] = createSignal<CaptureState>(
    props.existingCapture ? "preview" : "webcam",
  );
  const [processedImage, setProcessedImage] = createSignal<string | null>(
    props.existingCapture?.image_data ?? null,
  );
  const [error, setError] = createSignal<string | null>(null);
  // Store the captured frame to display during processing
  const [capturedFrame, setCapturedFrame] = createSignal<string | null>(null);
  // Track whether we're viewing an existing capture (vs a newly taken one)
  const [viewingExisting, setViewingExisting] = createSignal(
    !!props.existingCapture,
  );
  // Custom emoji input
  const [customEmojiInput, setCustomEmojiInput] = createSignal(
    props.emoji.emoji,
  );

  // Extract the first valid emoji from a string, or return empty string
  const extractFirstEmoji = (str: string): string => {
    if (!str) return "";

    // Use Intl.Segmenter to split into grapheme clusters
    const segmenter = new Intl.Segmenter("en", { granularity: "grapheme" });
    const segments = [...segmenter.segment(str)];

    // Check if it's an emoji using Unicode Extended_Pictographic property
    const emojiRegex = /\p{Extended_Pictographic}/u;

    // Find the first grapheme that is an emoji
    for (const segment of segments) {
      if (emojiRegex.test(segment.segment)) {
        return segment.segment;
      }
    }

    return "";
  };

  // Validate that input is exactly one emoji grapheme
  const isValidEmoji = (str: string): boolean => {
    return str !== "" && str === extractFirstEmoji(str);
  };

  // Handle emoji input - only allow valid emojis
  const handleEmojiInput = (e: InputEvent & { currentTarget: HTMLInputElement }) => {
    const emoji = extractFirstEmoji(e.currentTarget.value);
    e.currentTarget.value = emoji; // Force input value to sanitized emoji
    setCustomEmojiInput(emoji);
  };

  // Get current emoji (either from props or custom input for new custom emojis)
  const currentEmoji = () =>
    props.isCustom && !props.existingCapture
      ? customEmojiInput()
      : props.emoji.emoji;

  // Check if capture should be disabled (custom emoji mode with invalid emoji)
  const captureDisabled = () =>
    props.isCustom && !props.existingCapture && !isValidEmoji(customEmojiInput());

  // Countdown for delayed capture
  const [countdown, setCountdown] = createSignal<number | null>(null);
  let countdownInterval: number | undefined;

  // Settings accessors from props
  const padding = () => props.settings.padding;
  const keepBackground = () => props.settings.keep_background;
  const keepClothes = () => props.settings.keep_clothes;
  const keepAccessories = () => props.settings.keep_accessories;

  // Handle settings change - update parent which handles persistence
  const handlePaddingChange = (value: number) => {
    const newSettings = { ...props.settings, padding: value };
    props.onSettingsChange(newSettings);
  };

  const handleKeepBackgroundChange = (value: boolean) => {
    props.onSettingsChange({ ...props.settings, keep_background: value });
  };

  const handleKeepClothesChange = (value: boolean) => {
    props.onSettingsChange({ ...props.settings, keep_clothes: value });
  };

  const handleKeepAccessoriesChange = (value: boolean) => {
    props.onSettingsChange({ ...props.settings, keep_accessories: value });
  };

  const initWebcam = async () => {
    if (videoRef) {
      try {
        stream = await startWebcam(videoRef);
        videoRef.style.transform = "scaleX(-1)";
      } catch (err: any) {
        const isFirefox = navigator.userAgent.toLowerCase().includes("firefox");
        const isSecure = window.location.protocol === "https:" || window.location.hostname === "localhost";

        if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError" || err.name === "SecurityError") {
          if (!isSecure) {
            setError("Camera access requires HTTPS. Please access this site over a secure connection.");
          } else if (isFirefox) {
            setError("Camera permission denied. On Firefox, tap the lock icon in the address bar and allow camera access, then reload the page.");
          } else {
            setError("Camera permission denied. Please grant camera access in your browser settings.");
          }
        } else if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
          setError("No camera found. Please connect a camera or use the upload option.");
        } else if (err.name === "NotReadableError" || err.name === "TrackStartError") {
          setError("Camera is in use by another application. Please close other apps using the camera.");
        } else if (err.name === "AbortError") {
          setError("Camera access was interrupted. Please try again.");
        } else if (err.name === "OverconstrainedError") {
          setError("Camera doesn't support the requested settings. Please try again or use the upload option.");
        } else {
          setError(`Failed to access webcam: ${err.message || "Unknown error"}. Try using the upload option instead.`);
        }
      }
    }
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    // Ignore if user is interacting with form elements
    if (
      e.target instanceof HTMLInputElement ||
      e.target instanceof HTMLTextAreaElement
    ) {
      return;
    }

    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      e.stopPropagation();

      const currentState = state();
      if (currentState === "webcam" && !error()?.match(/camera|webcam/i)) {
        handleCapture();
      } else if (currentState === "preview" && !viewingExisting()) {
        if (props.onNext) {
          handleAcceptAndNext();
        } else {
          handleAccept();
        }
      }
    } else if (e.key === "Delete" || e.key === "Backspace") {
      // Only handle delete for existing captures (to delete them)
      if (state() === "preview" && viewingExisting()) {
        e.preventDefault();
        e.stopPropagation();
        handleDelete();
      }
    }
  };

  let resizeObserver: ResizeObserver | undefined;

  onMount(() => {
    if (!props.existingCapture) {
      initWebcam();
    }
    window.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";

    if (referenceContainerRef) {
      resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          setReferenceWidth(entry.contentRect.width);
        }
      });
      resizeObserver.observe(referenceContainerRef);
    }
  });

  // Reset state when emoji changes (e.g., when clicking "Next")
  createEffect(() => {
    // Track the emoji to trigger on changes
    const _ = props.emoji.emoji;
    // Check if there's an existing capture for this emoji
    if (props.existingCapture) {
      setState("preview");
      setProcessedImage(props.existingCapture.image_data);
      setViewingExisting(true);
    } else {
      setState("webcam");
      setProcessedImage(null);
      setViewingExisting(false);
    }
    setCapturedFrame(null);
    setError(null);
  });

  onCleanup(() => {
    if (stream) {
      stopWebcam(stream);
    }
    if (countdownInterval) {
      clearInterval(countdownInterval);
    }
    if (resizeObserver) {
      resizeObserver.disconnect();
    }
    window.removeEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "";
  });

  const handleCapture = () => {
    if (!videoRef) return;

    // Capture frame
    const frame = captureFrame(videoRef);
    setCapturedFrame(frame);
    setState("processing");
    setError(null);

    // Send to backend for face detection (preview only, don't save yet)
    previewCapture(props.sessionId, currentEmoji(), {
      image: frame,
      padding: padding(),
      keep_background: keepBackground(),
      keep_clothes: keepClothes(),
      keep_accessories: keepAccessories(),
    })
      .then((result) => {
        setProcessedImage(result.preview_image);
        setState("preview");
      })
      .catch((err) => {
        setError(err.message || "Face detection failed");
        setCapturedFrame(null);
        setState("webcam");
      });
  };

  const handleUpload = (file: File) => {
    setError(null);

    const reader = new FileReader();
    reader.onload = () => {
      const base64 = reader.result as string;
      setCapturedFrame(base64);
      setState("processing");
      previewCapture(props.sessionId, currentEmoji(), {
        image: base64,
        padding: padding(),
        keep_background: keepBackground(),
        keep_clothes: keepClothes(),
        keep_accessories: keepAccessories(),
      })
        .then((result) => {
          setProcessedImage(result.preview_image);
          setState("preview");
        })
        .catch((err) => {
          setError(err.message || "Face detection failed");
          setCapturedFrame(null);
          setState("webcam");
        });
    };
    reader.onerror = () => {
      setError("Failed to read file");
      setCapturedFrame(null);
      setState("webcam");
    };
    reader.readAsDataURL(file);
  };

  const handleFileSelect = (e: Event) => {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      handleUpload(file);
    }
    // Reset input so the same file can be selected again
    input.value = "";
  };

  const handleDelayedCapture = () => {
    if (countdownInterval) {
      clearInterval(countdownInterval);
    }
    setCountdown(3);
    countdownInterval = setInterval(() => {
      setCountdown((prev) => {
        if (prev === null || prev <= 1) {
          clearInterval(countdownInterval);
          countdownInterval = undefined;
          handleCapture();
          return null;
        }
        return prev - 1;
      });
    }, 1000) as unknown as number;
  };

  const cancelCountdown = () => {
    if (countdownInterval) {
      clearInterval(countdownInterval);
      countdownInterval = undefined;
    }
    setCountdown(null);
  };

  const handleRetake = async () => {
    setProcessedImage(null);
    setCapturedFrame(null);
    setState("webcam");
    setError(null);
    setViewingExisting(false);
    // Restart webcam if it was stopped
    if (!stream || !stream.active) {
      await initWebcam();
    }
  };

  const handleAccept = async () => {
    const image = processedImage();
    if (!image) return;

    const emoji = currentEmoji();
    if (!emoji.trim()) {
      setError("Please enter an emoji");
      return;
    }

    try {
      await saveCapture(props.sessionId, emoji, image);
      props.onComplete();
    } catch (err: any) {
      setError(err.message || "Failed to save capture");
    }
  };

  const handleAcceptAndNext = async () => {
    const image = processedImage();
    if (!image) return;

    const emoji = currentEmoji();
    if (!emoji.trim()) {
      setError("Please enter an emoji");
      return;
    }

    try {
      await saveCapture(props.sessionId, emoji, image);
      if (props.onNext) {
        props.onNext();
      }
    } catch (err: any) {
      setError(err.message || "Failed to save capture");
    }
  };

  const handleDelete = async () => {
    try {
      await deleteCapture(props.sessionId, currentEmoji());
      props.onComplete();
    } catch (err) {
      setError("Failed to delete capture");
    }
  };

  return (
    <div
      class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4"
      onClick={props.onClose}
    >
      <div
        class="bg-white rounded-xl shadow-2xl max-w-[95vw] sm:max-w-2xl w-full max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div class="flex items-center justify-between p-4 border-b">
          <div class="flex items-center gap-3">
            <div class="w-12 h-12 flex items-center justify-center">
              <Show
                when={props.isCustom && !props.existingCapture}
                fallback={
                  <span class="text-4xl emoji">{props.emoji.emoji}</span>
                }
              >
                <span class="text-4xl emoji">{customEmojiInput() || "?"}</span>
              </Show>
            </div>
            <div>
              <h2 class="text-lg font-semibold">
                {props.isCustom && !props.existingCapture
                  ? "Add Custom Emoji"
                  : "Capture Emoji"}
              </h2>
              <p class="text-sm text-gray-500">
                {props.isCustom && !props.existingCapture
                  ? "Paste any emoji below!"
                  : "Mimic the expression!"}
              </p>
            </div>
          </div>
          <button
            class="p-2 hover:bg-gray-100 rounded-full transition-colors"
            onClick={props.onClose}
          >
            <svg
              class="w-6 h-6"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div class="p-4">
          {/* Error Display */}
          <Show when={error()}>
            <div class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
              {error()}
            </div>
          </Show>

          {/* Reference + Webcam/Preview Side by Side */}
          <div class="grid grid-cols-2 gap-4 mb-4">
            {/* Reference Emoji */}
            <div class="flex flex-col items-center">
              <p class="text-sm text-gray-500 mb-2">Reference</p>
              <div
                ref={referenceContainerRef}
                class="aspect-square w-full max-w-[200px] bg-gray-100 rounded-lg flex items-center justify-center relative overflow-hidden"
              >
                <Show
                  when={props.isCustom && !props.existingCapture}
                  fallback={
                    <span
                      class="emoji leading-none"
                      style={{
                        "font-size": "12rem",
                        transform: `scale(${(referenceWidth() / 200) / (1 + padding() * 1.5)})`,
                      }}
                    >
                      {props.emoji.emoji}
                    </span>
                  }
                >
                  <input
                    type="text"
                    value={customEmojiInput()}
                    onInput={handleEmojiInput}
                    class="absolute inset-0 w-full h-full text-center bg-transparent text-9xl emoji focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset rounded-lg"
                    placeholder="?"
                  />
                </Show>
              </div>
            </div>

            {/* Webcam / Preview */}
            <div class="flex flex-col items-center">
              <p class="text-sm text-gray-500 mb-2">
                {state() === "preview" ? "Result" : "Your Face"}
              </p>
              <div
                class={`aspect-square w-full max-w-[200px] rounded-lg overflow-hidden relative ${
                  state() === "preview" ? "bg-gray-100" : "bg-gray-900"
                }`}
              >
                {/* Video element - always mounted, hidden when in preview or processing mode */}
                <video
                  ref={videoRef}
                  class="w-full h-full object-cover"
                  style={{
                    display: state() === "webcam" ? "block" : "none",
                  }}
                  autoplay
                  playsinline
                  muted
                />

                {/* Captured frame shown during processing */}
                <Show when={state() === "processing" && capturedFrame()}>
                  <img
                    src={capturedFrame()!}
                    alt="Captured frame"
                    class="w-full h-full object-cover"
                  />
                  <div class="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center">
                    <div class="animate-spin rounded-full h-8 w-8 border-4 border-white border-t-transparent"></div>
                  </div>
                </Show>

                {/* Preview image with transparency */}
                <Show when={state() === "preview" && processedImage()}>
                  <img
                    src={processedImage()!}
                    alt="Captured"
                    class="w-full h-full object-contain"
                  />
                </Show>
              </div>
            </div>
          </div>

          {/* Parameters (only show in webcam mode) */}
          <Show when={state() === "webcam"}>
            <div class="bg-gray-50 rounded-lg p-4 mb-4">
              <h3 class="text-sm font-medium text-gray-700 mb-3">
                Capture Settings
              </h3>
              <div class="space-y-3">
                <div>
                  <label class="flex items-center justify-between text-sm">
                    <span>Face Padding: {Math.round(padding() * 100)}%</span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={padding() * 100}
                    onInput={(e) =>
                      handlePaddingChange(parseInt(e.currentTarget.value) / 100)
                    }
                    class="w-full"
                  />
                </div>
                <div class="flex flex-wrap gap-x-4 gap-y-2">
                  <label class="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={keepBackground()}
                      onChange={(e) =>
                        handleKeepBackgroundChange(e.currentTarget.checked)
                      }
                      class="w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-500"
                    />
                    <span>Background</span>
                  </label>
                  <label class="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={keepClothes()}
                      onChange={(e) =>
                        handleKeepClothesChange(e.currentTarget.checked)
                      }
                      class="w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-500"
                    />
                    <span>Clothes</span>
                  </label>
                  <label class="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={keepAccessories()}
                      onChange={(e) =>
                        handleKeepAccessoriesChange(e.currentTarget.checked)
                      }
                      class="w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-500"
                    />
                    <span>Accessories</span>
                  </label>
                </div>
              </div>
            </div>
          </Show>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            capture="user"
            class="hidden"
            onChange={handleFileSelect}
          />

          {/* Actions */}
          <div class="flex flex-col gap-2">
            <div class="flex gap-3">
              <Show when={state() === "webcam" && countdown() === null && !error()?.match(/camera|webcam|https/i)}>
                <div class="flex-1 flex">
                  <button
                    class={`flex-1 font-medium py-3 px-4 rounded-l-lg transition-colors ${
                      captureDisabled()
                        ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                        : "bg-blue-500 hover:bg-blue-600 text-white"
                    }`}
                    onClick={handleCapture}
                    disabled={captureDisabled()}
                  >
                    Capture
                  </button>
                  <button
                    class={`font-medium py-3 px-4 rounded-r-lg transition-colors border-l ${
                      captureDisabled()
                        ? "bg-gray-200 text-gray-400 cursor-not-allowed border-gray-400"
                        : "bg-blue-400 hover:bg-blue-500 text-white border-blue-600"
                    }`}
                    onClick={handleDelayedCapture}
                    disabled={captureDisabled()}
                  >
                    in 3 seconds
                  </button>
                </div>
                <button
                  class={`font-medium py-3 px-4 rounded-lg transition-colors ${
                    captureDisabled()
                      ? "bg-gray-200 text-gray-400 cursor-not-allowed"
                      : "bg-gray-200 hover:bg-gray-300 text-gray-700"
                  }`}
                  onClick={() => fileInputRef?.click()}
                  disabled={captureDisabled()}
                >
                  or Upload
                </button>
              </Show>

              <Show when={state() === "webcam" && countdown() === null && error()?.match(/camera|webcam|https/i)}>
                <button
                  class={`flex-1 font-medium py-3 px-4 rounded-lg transition-colors ${
                    captureDisabled()
                      ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                      : "bg-blue-500 hover:bg-blue-600 text-white"
                  }`}
                  onClick={() => fileInputRef?.click()}
                  disabled={captureDisabled()}
                >
                  Take Photo
                </button>
              </Show>

              <Show when={state() === "webcam" && countdown() !== null}>
                <button
                  class="flex-1 bg-red-500 hover:bg-red-600 text-white font-medium py-3 px-4 rounded-lg transition-colors"
                  onClick={cancelCountdown}
                >
                  Cancel ({countdown()}s)
                </button>
              </Show>

              <Show when={state() === "preview"}>
                <Show when={!viewingExisting()}>
                  <button
                    class="flex-1 bg-green-500 hover:bg-green-600 text-white font-medium py-3 px-4 rounded-lg transition-colors"
                    onClick={handleAccept}
                  >
                    Accept
                  </button>
                </Show>
                <button
                  class="flex-1 bg-gray-200 hover:bg-gray-300 text-gray-700 font-medium py-3 px-4 rounded-lg transition-colors"
                  onClick={handleRetake}
                >
                  Retake
                </button>
                <Show when={viewingExisting()}>
                  <button
                    class="flex-1 bg-red-100 hover:bg-red-200 text-red-700 font-medium py-3 px-4 rounded-lg transition-colors"
                    onClick={handleDelete}
                  >
                    Delete
                  </button>
                </Show>
                <Show when={props.onNext && !viewingExisting()}>
                  <button
                    class="flex-1 bg-blue-500 hover:bg-blue-600 text-white font-medium py-3 px-4 rounded-lg transition-colors"
                    onClick={handleAcceptAndNext}
                  >
                    Next
                  </button>
                </Show>
              </Show>

              <Show when={state() === "processing"}>
                <button
                  class="flex-1 bg-gray-300 text-gray-500 font-medium py-3 px-4 rounded-lg cursor-not-allowed"
                  disabled
                >
                  Processing...
                </button>
              </Show>
            </div>
            <Show when={state() === "webcam"}>
              <p class="text-xs text-gray-400 text-center">
                Press space / enter to capture
              </p>
            </Show>
            <Show when={state() === "preview" && !viewingExisting()}>
              <p class="text-xs text-gray-400 text-center">
                Press space / enter to {props.onNext ? "next" : "accept"}
              </p>
            </Show>
            <Show when={state() === "preview" && viewingExisting()}>
              <p class="text-xs text-gray-400 text-center">
                Press delete to remove
              </p>
            </Show>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CaptureModal;

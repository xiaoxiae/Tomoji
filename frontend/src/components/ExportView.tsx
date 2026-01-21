import { createSignal, createEffect, Show, onMount } from 'solid-js';
import { exportFont, getFontUrl, getImagesZipUrl } from '../lib/api';

interface ExportViewProps {
  sessionId: string;
  capturedCount: number;
  totalEmojis: number;
  capturedEmojis: string[];
  lastCaptureEdit: string | null;
  lastGeneration: string | null;
  setLastGeneration: (timestamp: string | null) => void;
  fontUrl: string | null;
  setFontUrl: (url: string | null) => void;
  fontLoaded: boolean;
  setFontLoaded: (loaded: boolean) => void;
  fontFamilyId: string | null;
  setFontFamilyId: (id: string | null) => void;
}

function ExportView(props: ExportViewProps) {
  const [fontName, setFontName] = createSignal('Tomoji');
  const [isExporting, setIsExporting] = createSignal(false);
  const [copied, setCopied] = createSignal(false);
  const [error, setError] = createSignal<string | null>(null);
  const [previewText, setPreviewText] = createSignal('');

  // Determine button text and state based on timestamps
  const buttonState = () => {
    const lastGen = props.lastGeneration;
    const lastEdit = props.lastCaptureEdit;

    // Never generated - show "Generate Font"
    if (!lastGen) return { text: 'Generate Font', disabled: false };

    // No edits recorded - font is up to date
    if (!lastEdit) return { text: 'Regenerate Font', disabled: true };

    // Compare timestamps
    const genTime = new Date(lastGen).getTime();
    const editTime = new Date(lastEdit).getTime();

    if (editTime > genTime) {
      return { text: 'Regenerate Font', disabled: false };
    }

    return { text: 'Regenerate Font', disabled: true };
  };

  // Set default preview text to captured emojis
  createEffect(() => {
    if (props.capturedEmojis.length > 0 && !previewText()) {
      setPreviewText(props.capturedEmojis.join(' '));
    }
  });

  // Check for existing font on mount (only if not already loaded)
  onMount(async () => {
    if (props.fontLoaded) return; // Already loaded, skip

    const url = getFontUrl(props.sessionId);
    try {
      await loadFont(url);
      // Only set fontUrl after successful load to avoid flash
      props.setFontUrl(url);
    } catch {
      // No existing font, keep fontUrl null
    }
  });

  const loadFont = async (url: string) => {
    // Generate new font family ID to avoid caching issues
    const newFontFamilyId = `tomoji-preview-${Date.now()}`;
    props.setFontFamilyId(newFontFamilyId);

    // Add cache-busting parameter
    const cacheBustedUrl = `${url}?t=${Date.now()}`;
    const font = new FontFace(newFontFamilyId, `url(${cacheBustedUrl})`);
    const loadedFont = await font.load();
    document.fonts.add(loadedFont);
    props.setFontLoaded(true);
  };

  const handleExport = async () => {
    if (props.capturedCount === 0) {
      setError('No emojis captured yet. Go to Gallery and capture some emojis first!');
      return;
    }

    if (!props.sessionId) {
      setError('Session not found. Please refresh the page.');
      return;
    }

    setIsExporting(true);
    setError(null);
    props.setFontLoaded(false);

    try {
      const result = await exportFont(props.sessionId, fontName());
      // Use server timestamp to ensure consistent comparison with lastCaptureEdit
      props.setLastGeneration(result.last_generation);
      const url = getFontUrl(props.sessionId);
      props.setFontUrl(url);
      await loadFont(url);
    } catch (err: any) {
      setError(err.message || 'Export failed');
    } finally {
      setIsExporting(false);
    }
  };

  const getFullFontUrl = () => {
    const url = props.fontUrl;
    if (!url) return '';
    return `${window.location.origin}${url}`;
  };

  const handleCopyUrl = async () => {
    try {
      await navigator.clipboard.writeText(getFullFontUrl());
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard errors silently
    }
  };

  return (
    <div class="w-full">
      <h2 class="text-xl font-bold mb-4">Export</h2>

      {/* Font Name Input */}
      <div class="mb-6">
        <label class="block text-sm font-medium text-gray-700 mb-2">Name</label>
        <input
          type="text"
          value={fontName()}
          onInput={(e) => setFontName(e.currentTarget.value)}
          class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          placeholder="Enter font name"
        />
      </div>

      {/* Error Display */}
      <Show when={error()}>
        <div class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
          {error()}
        </div>
      </Show>

      {/* Export Buttons */}
      <div class="flex gap-3 items-start">
        <div class="flex-1 relative">
          <button
            class={`w-full py-3 px-4 rounded-lg font-medium transition-colors ${
              isExporting() || buttonState().disabled
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-blue-500 hover:bg-blue-600 text-white'
            }`}
            onClick={handleExport}
            disabled={isExporting() || buttonState().disabled}
          >
            {isExporting() ? (
              <span class="flex items-center justify-center gap-2">
                <span class="animate-spin rounded-full h-5 w-5 border-2 border-white border-t-transparent"></span>
                Generating...
              </span>
            ) : (
              buttonState().text
            )}
          </button>
          <Show when={buttonState().disabled && !isExporting()}>
            <p class="absolute w-full text-xs text-gray-500 text-center mt-1">Up to date</p>
          </Show>
        </div>

        <span class="text-gray-500 py-3">or</span>

        <div class="flex-1">
          <a
            href={getImagesZipUrl(props.sessionId, fontName())}
            download
            class={`block w-full py-3 px-4 rounded-lg font-medium text-center transition-colors ${
              props.capturedCount === 0
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed pointer-events-none'
                : 'bg-gray-600 hover:bg-gray-700 text-white'
            }`}
          >
            Download Images
          </a>
        </div>
      </div>

      {/* Font Preview (shown when font is available) */}
      <Show when={props.fontUrl}>
        <div class="pt-6">
          {/* Font Preview */}
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 mb-2">Preview</label>
            <Show
              when={props.fontLoaded}
              fallback={
                <div class="w-full px-4 py-3 border border-gray-300 rounded-lg bg-gray-50 flex items-center justify-center" style={{ "min-height": "120px" }}>
                  <div class="flex items-center gap-2 text-gray-400">
                    <span class="animate-spin rounded-full h-5 w-5 border-2 border-gray-400 border-t-transparent"></span>
                    <span>Loading font...</span>
                  </div>
                </div>
              }
            >
              <textarea
                value={previewText()}
                onInput={(e) => setPreviewText(e.currentTarget.value)}
                class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-none"
                style={{
                  "font-family": `"${props.fontFamilyId}", sans-serif`,
                  "font-size": "2rem",
                  "line-height": "1.5",
                  "min-height": "120px",
                }}
                placeholder="Type emojis to preview..."
              />
            </Show>
            <p class="text-xs text-gray-500 mt-1">
              Type or paste emojis to see them rendered with your custom font
            </p>
          </div>

          {/* CDN URL Display */}
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 mb-2">
              Font URL
            </label>
            <div class="flex flex-col sm:flex-row gap-2">
              <input
                type="text"
                readonly
                value={getFullFontUrl()}
                class="w-full sm:flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono text-gray-600"
              />
              <div class="flex gap-2">
                <button
                  class={`flex-1 sm:flex-none px-4 py-2 rounded-lg font-medium transition-colors ${
                    copied()
                      ? 'bg-green-500 text-white'
                      : 'bg-blue-500 hover:bg-blue-600 text-white'
                  }`}
                  onClick={handleCopyUrl}
                >
                  {copied() ? 'Copied!' : 'Copy'}
                </button>
                <a
                  href={props.fontUrl!}
                  download={`${fontName()}.woff2`}
                  class="flex-1 sm:flex-none px-4 py-2 rounded-lg font-medium transition-colors bg-gray-600 hover:bg-gray-700 text-white text-center"
                >
                  Download
                </a>
              </div>
            </div>
          </div>

          {/* CSS Example */}
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-2">
              CSS Usage
            </label>
            <pre class="bg-gray-900 p-4 rounded-lg text-xs overflow-x-auto"><code>
              <span class="text-pink-400">@font-face</span>
              <span class="text-gray-100">{" {\n  "}</span>
              <span class="text-cyan-300">font-family</span>
              <span class="text-gray-100">: </span>
              <span class="text-amber-300">"{fontName()}"</span>
              <span class="text-gray-100">{";\n  "}</span>
              <span class="text-cyan-300">src</span>
              <span class="text-gray-100">: </span>
              <span class="text-violet-400">url</span>
              <span class="text-gray-100">(</span>
              <span class="text-amber-300">"{getFullFontUrl()}"</span>
              <span class="text-gray-100">) </span>
              <span class="text-violet-400">format</span>
              <span class="text-gray-100">(</span>
              <span class="text-amber-300">"woff2"</span>
              <span class="text-gray-100">)</span>
              <span class="text-gray-100">{";\n}\n\n"}</span>
              <span class="text-amber-200">.emoji</span>
              <span class="text-gray-100">{" {\n  "}</span>
              <span class="text-cyan-300">font-family</span>
              <span class="text-gray-100">: </span>
              <span class="text-amber-300">"{fontName()}"</span>
              <span class="text-gray-100">, </span>
              <span class="text-gray-100">sans-serif</span>
              <span class="text-gray-100">{";\n}"}</span>
            </code></pre>
          </div>
        </div>
      </Show>
    </div>
  );
}

export default ExportView;

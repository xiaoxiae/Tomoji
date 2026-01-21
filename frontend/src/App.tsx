import {
  createSignal,
  createResource,
  Show,
  Switch,
  Match,
  onMount,
} from "solid-js";
import { useParams, useNavigate, useLocation } from "@solidjs/router";
import {
  listEmojis,
  getGallery,
  validateSession,
  clearSession,
  getSettings,
  saveSettings,
  RateLimitError,
  type Emoji,
  type CapturedEmoji,
  type Settings,
} from "./lib/api";
import { setSessionCookie } from "./lib/cookies";
import Gallery from "./components/Gallery";
import CaptureModal from "./components/CaptureModal";
import ExportView from "./components/ExportView";

type View = "gallery" | "export" | "about";

function App() {
  const params = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const location = useLocation();

  // Derive view from URL path
  const view = (): View => {
    const path = location.pathname;
    if (path.endsWith("/export")) return "export";
    if (path.endsWith("/about")) return "about";
    return "gallery";
  };

  const setView = (newView: View) => {
    if (newView === "gallery") {
      navigate(`/${sessionId()}`, { replace: true });
    } else {
      navigate(`/${sessionId()}/${newView}`, { replace: true });
    }
  };

  const [selectedEmoji, setSelectedEmoji] = createSignal<Emoji | null>(null);
  const [isCustomCapture, setIsCustomCapture] = createSignal(false);
  const [sessionState, setSessionState] = createSignal<
    "loading" | "valid" | "invalid" | "rate-limited"
  >("loading");
  const [validatedSessionId, setValidatedSessionId] = createSignal<
    string | null
  >(null);
  const [showClearConfirm, setShowClearConfirm] = createSignal(false);
  const [clearing, setClearing] = createSignal(false);
  const [menuOpen, setMenuOpen] = createSignal(false);

  // Font state lifted from ExportView to persist across view changes
  const [fontUrl, setFontUrl] = createSignal<string | null>(null);
  const [fontLoaded, setFontLoaded] = createSignal(false);
  const [fontFamilyId, setFontFamilyId] = createSignal<string | null>(null);
  // Track last generation time locally to persist across view changes
  const [localLastGeneration, setLocalLastGeneration] = createSignal<
    string | null
  >(null);

  // App-wide settings (loaded once per session)
  const defaultSettings: Settings = {
    padding: 0,
    keep_background: false,
    keep_clothes: false,
    keep_accessories: true,
  };
  const [settings, setSettings] = createSignal<Settings>(defaultSettings);
  const [settingsLoaded, setSettingsLoaded] = createSignal(false);
  let settingsSaveTimeout: number | undefined;

  const sessionId = () => params.sessionId || "";

  const loadSettings = async (sid: string) => {
    try {
      const loadedSettings = await getSettings(sid);
      setSettings(loadedSettings);
      setSettingsLoaded(true);
    } catch (err) {
      // Use defaults if settings can't be loaded
      setSettingsLoaded(true);
    }
  };

  const handleSettingsChange = (newSettings: Settings) => {
    // Update UI immediately
    setSettings(newSettings);
    // Debounce save to backend
    if (settingsSaveTimeout) {
      clearTimeout(settingsSaveTimeout);
    }
    settingsSaveTimeout = setTimeout(async () => {
      try {
        await saveSettings(sessionId(), newSettings);
      } catch (err) {
        // Ignore save errors silently
      }
    }, 500) as unknown as number;
  };

  const validateAndSetSession = async () => {
    const currentSessionId = sessionId();

    // Skip if we've already validated this session
    if (
      validatedSessionId() === currentSessionId &&
      sessionState() === "valid"
    ) {
      return;
    }

    setSessionState("loading");
    try {
      const result = await validateSession(currentSessionId);
      if (!result.valid) {
        setSessionState("invalid");
        return;
      }
      // Save session to cookie for future visits
      setSessionCookie(currentSessionId);
      setValidatedSessionId(currentSessionId);
      setSessionState("valid");
      // Load settings once session is validated
      loadSettings(currentSessionId);
    } catch (error) {
      if (error instanceof RateLimitError) {
        setSessionState("rate-limited");
      } else {
        setSessionState("invalid");
      }
    }
  };

  // Validate session on mount
  onMount(() => {
    validateAndSetSession();

    // Load Umami analytics if configured
    const umamiUrl = import.meta.env.VITE_UMAMI_URL;
    const umamiWebsiteId = import.meta.env.VITE_UMAMI_WEBSITE_ID;
    const umamiDomains = import.meta.env.VITE_UMAMI_DOMAINS;

    if (umamiUrl && umamiWebsiteId) {
      const script = document.createElement("script");
      script.defer = true;
      script.src = umamiUrl;
      script.setAttribute("data-website-id", umamiWebsiteId);
      if (umamiDomains) {
        script.setAttribute("data-domains", umamiDomains);
      }
      document.head.appendChild(script);
    }
  });

  const [emojisData, { refetch: refetchEmojis }] = createResource(listEmojis);
  const [galleryData, { refetch: refetchGallery }] = createResource(
    () => (sessionState() === "valid" ? sessionId() : null),
    (id) =>
      id
        ? getGallery(id)
        : Promise.resolve({
            captured: [],
            total: 0,
            custom_emojis: [],
            last_capture_edit: null,
            last_generation: null,
          }),
  );

  // Flatten categories into a single list for navigation
  const allEmojis = () => {
    const categories = emojisData()?.categories || [];
    return categories.flatMap((cat) => cat.emojis);
  };

  const capturedSet = () => {
    const captured = galleryData()?.captured || [];
    return new Set(captured.map((c) => c.emoji));
  };

  const capturedMap = () => {
    const captured = galleryData()?.captured || [];
    const map = new Map<string, CapturedEmoji>();
    captured.forEach((c) => map.set(c.emoji, c));
    return map;
  };

  // Check if there are any uncaptured emojis
  const hasUncapturedEmoji = () => {
    const emojis = allEmojis();
    const captured = capturedSet();
    return emojis.some((e) => !captured.has(e.emoji));
  };

  const handleEmojiClick = (emoji: Emoji) => {
    setSelectedEmoji(emoji);
    setIsCustomCapture(false);
  };

  const handleAddCustomEmoji = () => {
    // Create a placeholder emoji for new custom capture
    setSelectedEmoji({ emoji: "", codepoint: "", name: "custom" });
    setIsCustomCapture(true);
  };

  const handleCaptureComplete = () => {
    setSelectedEmoji(null);
    setIsCustomCapture(false);
    refetchGallery();
  };

  const handleCaptureClose = () => {
    setSelectedEmoji(null);
    setIsCustomCapture(false);
  };

  const handleClearAll = async () => {
    setClearing(true);
    try {
      await clearSession(sessionId());
      // Reset font state since font is deleted with captures
      setFontUrl(null);
      setFontLoaded(false);
      setFontFamilyId(null);
      setLocalLastGeneration(null);
      refetchGallery();
    } finally {
      setClearing(false);
      setShowClearConfirm(false);
    }
  };

  const handleNext = async () => {
    // Refresh gallery to get updated capture status
    await refetchGallery();

    const emojis = allEmojis();
    const captured = capturedSet();
    const currentEmoji = selectedEmoji();

    if (!currentEmoji) return;

    const currentIndex = emojis.findIndex(
      (e) => e.emoji === currentEmoji.emoji,
    );

    // Find next uncaptured emoji after current, wrapping around
    for (let i = 1; i <= emojis.length; i++) {
      const nextIndex = (currentIndex + i) % emojis.length;
      const nextEmoji = emojis[nextIndex];
      if (!captured.has(nextEmoji.emoji)) {
        setSelectedEmoji(nextEmoji);
        return;
      }
    }

    // All captured, close modal
    setSelectedEmoji(null);
  };

  return (
    <Switch>
      <Match when={sessionState() === "loading"}>
        <div class="min-h-screen bg-gray-100 flex items-center justify-center">
          <div class="text-center">
            <div class="inline-block animate-spin rounded-full h-12 w-12 border-4 border-blue-500 border-t-transparent"></div>
            <p class="mt-4 text-gray-600 text-lg">Loading session...</p>
          </div>
        </div>
      </Match>

      <Match when={sessionState() === "invalid"}>
        <div class="min-h-screen bg-gray-100 flex items-center justify-center">
          <div class="text-center max-w-md mx-auto px-4">
            <div class="text-6xl mb-4">😕</div>
            <h1 class="text-2xl font-bold text-gray-900 mb-2">
              Session Not Found
            </h1>
            <p class="text-gray-600 mb-6">
              This session doesn't exist or has expired. Sessions are
              automatically deleted after 1 week of inactivity.
            </p>
            <button
              class="bg-blue-500 hover:bg-blue-600 text-white font-medium py-3 px-6 rounded-lg transition-colors"
              onClick={() => navigate("/", { replace: true })}
            >
              Start New Session
            </button>
          </div>
        </div>
      </Match>

      <Match when={sessionState() === "rate-limited"}>
        <div class="min-h-screen bg-gray-100 flex items-center justify-center">
          <div class="text-center max-w-md mx-auto px-4">
            <div class="text-6xl mb-4">⏳</div>
            <h1 class="text-2xl font-bold text-gray-900 mb-2">Rate Limited</h1>
            <p class="text-gray-600 mb-6">
              The website is being hugged to death. Please try again later.
            </p>
            <button
              class="bg-blue-500 hover:bg-blue-600 text-white font-medium py-3 px-6 rounded-lg transition-colors"
              onClick={validateAndSetSession}
            >
              Try Again
            </button>
          </div>
        </div>
      </Match>

      <Match when={sessionState() === "valid"}>
        <div class="min-h-screen bg-gray-100 flex flex-col">
          {/* Header */}
          <header class="bg-white shadow-sm relative">
            <div class="max-w-4xl mx-auto px-4 sm:px-8 py-3 sm:py-4">
              <div class="flex items-center justify-between">
                <h1
                  class="text-2xl font-bold text-gray-900 cursor-pointer hover:text-gray-700 transition-colors"
                  onClick={() => setView("gallery")}
                >
                  Tomoji<span class="tomoji">🤨</span>
                </h1>

                {/* Desktop Navigation - Segmented Control */}
                <nav class="hidden sm:flex items-center rounded-lg bg-gray-200 p-1 ml-4">
                  <button
                    class={`h-10 px-3 font-medium transition-colors rounded-md overflow-hidden flex items-center ${
                      view() === "gallery"
                        ? "bg-white shadow-sm text-gray-900"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                    onClick={() => setView("gallery")}
                  >
                    Gallery <span class="tomoji">🤳</span>
                  </button>
                  <button
                    class={`h-10 px-3 font-medium transition-colors rounded-md overflow-hidden flex items-center ${
                      view() === "export"
                        ? "bg-white shadow-sm text-gray-900"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                    onClick={() => setView("export")}
                  >
                    Export <span class="tomoji">👉</span>
                  </button>
                  <button
                    class={`h-10 px-3 font-medium transition-colors rounded-md overflow-hidden flex items-center ${
                      view() === "about"
                        ? "bg-white shadow-sm text-gray-900"
                        : "text-gray-600 hover:text-gray-900"
                    }`}
                    onClick={() => setView("about")}
                  >
                    About <span class="tomoji">🧑</span>
                  </button>
                </nav>

                {/* Mobile Hamburger Button */}
                <div class="relative sm:hidden ml-4">
                  <button
                    class="p-2 rounded-lg bg-gray-200 hover:bg-gray-300 transition-colors"
                    onClick={() => setMenuOpen(!menuOpen())}
                    aria-label="Toggle menu"
                  >
                    <svg
                      class="w-6 h-6"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <Show
                        when={!menuOpen()}
                        fallback={
                          <path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            stroke-width="2"
                            d="M6 18L18 6M6 6l12 12"
                          />
                        }
                      >
                        <path
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          stroke-width="2"
                          d="M4 6h16M4 12h16M4 18h16"
                        />
                      </Show>
                    </svg>
                  </button>

                  {/* Mobile Menu Dropdown */}
                  <Show when={menuOpen()}>
                    <nav class="absolute right-0 top-full mt-2 bg-white rounded-lg shadow-lg border border-gray-200 overflow-hidden z-50">
                      <button
                        class={`w-full px-4 py-2 font-medium transition-colors text-center whitespace-nowrap ${
                          view() === "gallery"
                            ? "bg-blue-50 text-blue-600"
                            : "text-gray-700 hover:bg-gray-100"
                        }`}
                        onClick={() => {
                          setView("gallery");
                          setMenuOpen(false);
                        }}
                      >
                        Gallery <span class="tomoji">🤳</span>
                      </button>
                      <button
                        class={`w-full px-4 py-2 font-medium transition-colors text-center whitespace-nowrap ${
                          view() === "export"
                            ? "bg-blue-50 text-blue-600"
                            : "text-gray-700 hover:bg-gray-100"
                        }`}
                        onClick={() => {
                          setView("export");
                          setMenuOpen(false);
                        }}
                      >
                        Export <span class="tomoji">👉</span>
                      </button>
                      <button
                        class={`w-full px-4 py-2 font-medium transition-colors text-center whitespace-nowrap ${
                          view() === "about"
                            ? "bg-blue-50 text-blue-600"
                            : "text-gray-700 hover:bg-gray-100"
                        }`}
                        onClick={() => {
                          setView("about");
                          setMenuOpen(false);
                        }}
                      >
                        About <span class="tomoji">🧑</span>
                      </button>
                    </nav>
                  </Show>
                </div>
              </div>
              <p class="text-sm text-gray-500 mt-2">
                Generate emojis from your face<span class="tomoji">😀</span>and
                use them on your website.
              </p>
            </div>
          </header>

          {/* Main Content */}
          <main class="w-full max-w-4xl mx-auto px-8 py-8 flex-1">
            <Show
              when={
                (emojisData.loading || galleryData.loading) && !emojisData()
              }
            >
              <div class="text-center py-8">
                <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent"></div>
                <p class="mt-2 text-gray-600">Loading...</p>
              </div>
            </Show>

            <Show when={emojisData.error || galleryData.error}>
              <div class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
                <p>Error loading data. Make sure the backend is running.</p>
              </div>
            </Show>

            <Show when={emojisData()}>
              <Show when={view() === "gallery"}>
                <Gallery
                  categories={emojisData()!.categories}
                  captured={capturedSet()}
                  capturedMap={capturedMap()}
                  customEmojis={galleryData()?.custom_emojis || []}
                  onEmojiClick={handleEmojiClick}
                  onAddCustomEmoji={handleAddCustomEmoji}
                  onRefresh={refetchGallery}
                  onShowClearConfirm={() => setShowClearConfirm(true)}
                />
              </Show>

              <Show when={view() === "export"}>
                <ExportView
                  sessionId={sessionId()}
                  capturedCount={galleryData()?.captured.length || 0}
                  totalEmojis={galleryData()?.total || 0}
                  capturedEmojis={
                    galleryData()?.captured.map((c) => c.emoji) || []
                  }
                  lastCaptureEdit={galleryData()?.last_capture_edit ?? null}
                  lastGeneration={
                    localLastGeneration() ??
                    galleryData()?.last_generation ??
                    null
                  }
                  setLastGeneration={setLocalLastGeneration}
                  fontUrl={fontUrl()}
                  setFontUrl={setFontUrl}
                  fontLoaded={fontLoaded()}
                  setFontLoaded={setFontLoaded}
                  fontFamilyId={fontFamilyId()}
                  setFontFamilyId={setFontFamilyId}
                />
              </Show>

              <Show when={view() === "about"}>
                <div>
                  <h2 class="text-xl font-bold text-gray-900 mb-4">About</h2>
                  <div class="text-gray-700 space-y-3">
                    <p>
                      To generate the emojis, this website uses{" "}
                      <a
                        class="text-blue-500 hover:text-blue-700 underline"
                        href="https://ai.google.dev/edge/mediapipe/solutions/vision/image_segmenter"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        MediaPipe
                      </a>{" "}
                      model for face segmentation and masking. The produced
                      bitmaps are then converted into a font via{" "}
                      <a
                        class="text-blue-500 hover:text-blue-700 underline"
                        href="https://fonttools.readthedocs.io/"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        fontTools
                      </a>{" "}
                      with 2 tables –{" "}
                      <a
                        class="text-blue-500 hover:text-blue-700 underline"
                        href="https://learn.microsoft.com/en-us/typography/opentype/spec/cbdt"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <strong>CBDT/CBLC</strong>
                      </a>{" "}
                      for Chrome and{" "}
                      <a
                        class="text-blue-500 hover:text-blue-700 underline"
                        href="https://learn.microsoft.com/en-us/typography/opentype/spec/svg"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <strong>OpenType-SVG</strong>
                      </a>{" "}
                      for Firefox. Since each of the tables{" "}
                      <a
                        class="text-blue-500 hover:text-blue-700 underline"
                        href="https://pixelambacht.nl/chromacheck"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        does NOT support the browser of the other
                      </a>
                      , we need to include both.
                    </p>
                    <p class="text-gray-400">
                      I haven't been able to find a table format that would
                      share support between both browsers and support bitmaps,
                      so do let me know if there is one since this is pretty
                      ugly (especially the SVG table, which just uses the
                      base64-encoded image; it works but it makes me sad).
                    </p>
                  </div>

                  <h3 class="text-lg font-semibold text-gray-900 mt-6 mb-3">
                    Privacy
                  </h3>
                  <div class="text-gray-700 space-y-3">
                    <p>
                      This website sends the images you capture to the server
                      for cropping the image and generating + hosting the font.
                      These are processed on the server and are accessible by
                      anyone with this URL. You can{" "}
                      <a
                        class="text-blue-500 hover:text-blue-700 underline"
                        href="https://github.com/xiaoxiae/tomoji"
                      >
                        host your own instance
                      </a>{" "}
                      if you want to generate a font locally, but I wanted to
                      set up an easy-to use instance if you just want to create
                      + host the font easily.
                    </p>
                    <p>
                      Sessions are automatically deleted after 7 days of
                      inactivity.
                    </p>
                    <p>
                      To delete all of this session's data,{" "}
                      <button
                        class="text-red-600 hover:text-red-800 underline font-medium"
                        onClick={() => setShowClearConfirm(true)}
                      >
                        click here
                      </button>
                      .
                    </p>
                  </div>
                </div>
              </Show>
            </Show>
          </main>

          {/* Capture Modal */}
          <Show when={selectedEmoji()}>
            <CaptureModal
              sessionId={sessionId()}
              emoji={selectedEmoji()!}
              existingCapture={capturedMap().get(selectedEmoji()!.emoji)}
              emojis={allEmojis()}
              isCustom={isCustomCapture()}
              settings={settings()}
              onSettingsChange={handleSettingsChange}
              onComplete={handleCaptureComplete}
              onClose={handleCaptureClose}
              onNext={hasUncapturedEmoji() ? handleNext : undefined}
            />
          </Show>

          {/* Clear All Confirmation Modal */}
          <Show when={showClearConfirm()}>
            <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
              <div class="bg-white rounded-lg p-6 max-w-sm mx-4 shadow-xl">
                <h3 class="text-lg font-semibold text-gray-900 mb-2">
                  Delete All Data?
                </h3>
                <p class="text-gray-600 mb-4">
                  This will delete all {galleryData()?.captured.length || 0}{" "}
                  captured images and the generated font. This action cannot be
                  undone.
                </p>
                <div class="flex gap-3 justify-end">
                  <button
                    class="px-4 py-2 text-gray-600 hover:text-gray-800"
                    onClick={() => setShowClearConfirm(false)}
                    disabled={clearing()}
                  >
                    Cancel
                  </button>
                  <button
                    class="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 disabled:opacity-50"
                    onClick={handleClearAll}
                    disabled={clearing()}
                  >
                    {clearing() ? "Deleting..." : "Delete All"}
                  </button>
                </div>
              </div>
            </div>
          </Show>

          {/* Footer */}
          <footer class="max-w-4xl mx-auto px-8 py-6 text-center text-sm text-gray-500">
            Maintained by{" "}
            <a
              class="text-blue-500 hover:text-blue-700 underline"
              href="https://slama.dev"
              target="_blank"
              rel="noopener noreferrer"
            >
              Tomáš Sláma
            </a>{" "}
            <span class="tomoji">🧑</span>.
          </footer>
        </div>
      </Match>
    </Switch>
  );
}

export default App;

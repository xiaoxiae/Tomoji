import { For, Show } from "solid-js";
import type { Emoji, EmojiCategory, CapturedEmoji } from "../lib/api";

interface GalleryProps {
  categories: EmojiCategory[];
  captured: Set<string>;
  capturedMap: Map<string, CapturedEmoji>;
  customEmojis: Emoji[];
  onEmojiClick: (emoji: Emoji) => void;
  onAddCustomEmoji: () => void;
  onRefresh: () => void;
  onShowClearConfirm: () => void;
}

function Gallery(props: GalleryProps) {
  const capturedCount = () => props.captured.size;
  const totalCount = () =>
    props.categories.reduce((sum, cat) => sum + cat.emojis.length, 0) +
    props.customEmojis.length;

  const firstUncapturedEmoji = () => {
    for (const category of props.categories) {
      for (const emoji of category.emojis) {
        if (!props.captured.has(emoji.emoji)) {
          return emoji;
        }
      }
    }
    return null;
  };

  return (
    <div>
      {/* Progress */}
      <div class="mb-6">
        <div class="flex items-center justify-between mb-2">
          <span class="text-gray-600">
            {capturedCount()} / {totalCount()} captured
          </span>
          <Show when={capturedCount() > 0}>
            <button
              class="text-sm text-red-500 hover:text-red-700"
              onClick={() => props.onShowClearConfirm()}
            >
              Clear All
            </button>
          </Show>
        </div>
        <div class="flex items-center gap-3">
          <Show when={firstUncapturedEmoji()}>
            <button
              class="px-4 py-1 bg-green-500 hover:bg-green-600 text-white text-sm font-medium rounded-full transition-colors whitespace-nowrap"
              onClick={() => {
                const emoji = firstUncapturedEmoji();
                if (emoji) props.onEmojiClick(emoji);
              }}
            >
              Start!
            </button>
          </Show>
          <div class="flex-1 bg-gray-200 rounded-full h-2">
            <div
              class="bg-blue-500 h-2 rounded-full transition-all duration-300"
              style={{ width: `${(capturedCount() / totalCount()) * 100}%` }}
            ></div>
          </div>
        </div>
      </div>

      {/* Emoji Categories */}
      <For each={props.categories}>
        {(category) => (
          <div class="mb-8">
            {/* Category Header */}
            <h2 class="text-lg font-semibold text-gray-700 mb-3">
              {category.name}{" "}
              <span class="text-gray-400 font-normal">
                (
                {
                  category.emojis.filter((e) => props.captured.has(e.emoji))
                    .length
                }
                /{category.emojis.length})
              </span>
            </h2>

            {/* Emoji Grid */}
            <div class="grid grid-cols-5 sm:grid-cols-7 md:grid-cols-10 gap-3">
              <For each={category.emojis}>
                {(emoji) => {
                  const isCaptured = () => props.captured.has(emoji.emoji);
                  const captureData = () => props.capturedMap.get(emoji.emoji);

                  return (
                    <button
                      class={`relative aspect-square rounded-lg border-2 flex items-center justify-center text-3xl transition-all hover:scale-110 hover:shadow-lg ${
                        isCaptured()
                          ? "border-green-500 bg-green-50"
                          : "border-gray-300 bg-white hover:border-blue-400"
                      }`}
                      onClick={() => props.onEmojiClick(emoji)}
                      title={
                        isCaptured()
                          ? `${emoji.name} - Click to retake`
                          : `${emoji.name} - Click to capture`
                      }
                    >
                      <Show
                        when={isCaptured() && captureData()}
                        fallback={
                          <span
                            class={`emoji ${isCaptured() ? "" : "opacity-50 grayscale"}`}
                          >
                            {emoji.emoji}
                          </span>
                        }
                      >
                        <img
                          src={captureData()!.image_data}
                          alt={emoji.name}
                          class="w-full h-full object-cover rounded-md"
                        />
                      </Show>
                      <Show when={isCaptured()}>
                        <div class="absolute -top-1 -left-1 w-5 h-5 bg-white rounded-full flex items-center justify-center shadow-sm border border-gray-200">
                          <span class="text-xs emoji">{emoji.emoji}</span>
                        </div>
                        <div class="absolute -top-1 -right-1 w-4 h-4 bg-green-500 rounded-full flex items-center justify-center">
                          <svg
                            class="w-3 h-3 text-white"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              stroke-linecap="round"
                              stroke-linejoin="round"
                              stroke-width="3"
                              d="M5 13l4 4L19 7"
                            />
                          </svg>
                        </div>
                      </Show>
                    </button>
                  );
                }}
              </For>
            </div>
          </div>
        )}
      </For>

      {/* Custom Emojis Section */}
      <div class="mb-8">
        <h2 class="text-lg font-semibold text-gray-700 mb-3">
          Custom{" "}
          <span class="text-gray-400 font-normal">
            ({props.customEmojis.length}/{props.customEmojis.length})
          </span>
        </h2>
        <div class="grid grid-cols-5 sm:grid-cols-7 md:grid-cols-10 gap-3">
          {/* Existing custom emojis */}
          <For each={props.customEmojis}>
            {(emoji) => {
              const captureData = () => props.capturedMap.get(emoji.emoji);

              return (
                <button
                  class="relative aspect-square rounded-lg border-2 border-green-500 bg-green-50 flex items-center justify-center text-3xl transition-all hover:scale-110 hover:shadow-lg"
                  onClick={() => props.onEmojiClick(emoji)}
                  title={`${emoji.name} - Click to retake`}
                >
                  <Show
                    when={captureData()}
                    fallback={<span class="emoji">{emoji.emoji}</span>}
                  >
                    <img
                      src={captureData()!.image_data}
                      alt={emoji.name}
                      class="w-full h-full object-cover rounded-md"
                    />
                  </Show>
                  <div class="absolute -top-1 -left-1 w-5 h-5 bg-white rounded-full flex items-center justify-center shadow-sm border border-gray-200">
                    <span class="text-xs emoji">{emoji.emoji}</span>
                  </div>
                  <div class="absolute -top-1 -right-1 w-4 h-4 bg-green-500 rounded-full flex items-center justify-center">
                    <svg
                      class="w-3 h-3 text-white"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="3"
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  </div>
                </button>
              );
            }}
          </For>

          {/* Add Custom Emoji Button */}
          <button
            class="aspect-square rounded-lg border-2 border-dashed border-gray-400 bg-white flex items-center justify-center text-3xl text-gray-400 transition-all hover:scale-110 hover:shadow-lg hover:border-blue-400 hover:text-blue-400"
            onClick={props.onAddCustomEmoji}
            title="Add custom emoji"
          >
            <svg
              class="w-8 h-8"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M12 4v16m8-8H4"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

export default Gallery;

import { createSignal, onMount, Show } from 'solid-js';
import { useNavigate } from '@solidjs/router';
import { createSession, validateSession, RateLimitError } from '../lib/api';
import { getSessionCookie, setSessionCookie } from '../lib/cookies';

function SessionRedirect() {
  const navigate = useNavigate();
  const [rateLimited, setRateLimited] = createSignal(false);

  const initSession = async () => {
    setRateLimited(false);

    // Check for existing session in cookie
    const existingSessionId = getSessionCookie();

    if (existingSessionId) {
      try {
        const result = await validateSession(existingSessionId);
        if (result.valid) {
          navigate(`/${existingSessionId}`, { replace: true });
          return;
        }
      } catch (err) {
        if (err instanceof RateLimitError) {
          setRateLimited(true);
          return;
        }
        // Session invalid or expired, create new one
      }
    }

    // Create new session
    try {
      const { session_id } = await createSession();
      setSessionCookie(session_id);
      navigate(`/${session_id}`, { replace: true });
    } catch (err) {
      if (err instanceof RateLimitError) {
        setRateLimited(true);
      }
    }
  };

  onMount(() => {
    initSession();
  });

  return (
    <div class="min-h-screen bg-gray-100 flex items-center justify-center">
      <div class="text-center max-w-md mx-auto px-4">
        <Show
          when={rateLimited()}
          fallback={
            <>
              <div class="inline-block animate-spin rounded-full h-12 w-12 border-4 border-blue-500 border-t-transparent"></div>
              <p class="mt-4 text-gray-600 text-lg">Loading session...</p>
            </>
          }
        >
          <div class="text-6xl mb-4">⏳</div>
          <h1 class="text-2xl font-bold text-gray-900 mb-2">Rate Limited</h1>
          <p class="text-gray-600 mb-6">The website is being hugged to death. Please try again later.</p>
          <button
            class="bg-blue-500 hover:bg-blue-600 text-white font-medium py-3 px-6 rounded-lg transition-colors"
            onClick={initSession}
          >
            Try Again
          </button>
        </Show>
      </div>
    </div>
  );
}

export default SessionRedirect;

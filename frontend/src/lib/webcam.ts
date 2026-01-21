export interface WebcamOptions {
  width?: number;
  height?: number;
  facingMode?: 'user' | 'environment';
}

async function tryGetUserMedia(facingMode: 'user' | 'environment'): Promise<MediaStream> {
  const constraintsList: MediaStreamConstraints[] = [
    {
      video: {
        width: { ideal: 640 },
        height: { ideal: 480 },
        facingMode,
      },
      audio: false,
    },
    {
      video: { facingMode },
      audio: false,
    },
    {
      video: true,
      audio: false,
    },
  ];

  let lastError: Error | null = null;

  for (const constraints of constraintsList) {
    try {
      return await navigator.mediaDevices.getUserMedia(constraints);
    } catch (err) {
      lastError = err as Error;
    }
  }

  throw lastError || new Error('Failed to access camera');
}

export async function startWebcam(
  videoElement: HTMLVideoElement,
  options: WebcamOptions = {}
): Promise<MediaStream> {
  const { facingMode = 'user' } = options;

  const stream = await tryGetUserMedia(facingMode);
  videoElement.srcObject = stream;

  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error('Video initialization timed out'));
    }, 10000);

    videoElement.onloadedmetadata = async () => {
      clearTimeout(timeout);
      try {
        await videoElement.play();
        resolve(stream);
      } catch (playError) {
        stream.getTracks().forEach((track) => track.stop());
        reject(playError);
      }
    };

    videoElement.onerror = () => {
      clearTimeout(timeout);
      stream.getTracks().forEach((track) => track.stop());
      reject(new Error('Video element error'));
    };
  });
}

export function stopWebcam(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
}

export function captureFrame(videoElement: HTMLVideoElement, mirror: boolean = true): string {
  const canvas = document.createElement('canvas');
  canvas.width = videoElement.videoWidth;
  canvas.height = videoElement.videoHeight;

  const ctx = canvas.getContext('2d')!;

  if (mirror) {
    // Flip horizontally to match the mirrored webcam preview
    ctx.translate(canvas.width, 0);
    ctx.scale(-1, 1);
  }

  ctx.drawImage(videoElement, 0, 0);

  return canvas.toDataURL('image/png');
}

export function mirrorVideo(videoElement: HTMLVideoElement, mirror: boolean): void {
  videoElement.style.transform = mirror ? 'scaleX(-1)' : 'scaleX(1)';
}

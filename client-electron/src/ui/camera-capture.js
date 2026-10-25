'use strict';

async function capture() {
  let stream;
  try {
    const parameters = new URLSearchParams(window.location.search);
    const requestedWidth = Number(parameters.get('width')) || 640;
    const quality = Number(parameters.get('quality')) || 0.7;
    const video = document.querySelector('#camera');
    const canvas = document.querySelector('#snapshot');
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { width: { ideal: requestedWidth }, audio: false },
    });
    video.srcObject = stream;
    await new Promise((resolve, reject) => {
      if (video.readyState >= HTMLMediaElement.HAVE_METADATA) return resolve();
      video.onloadedmetadata = resolve;
      video.onerror = reject;
    });
    await video.play();
    await new Promise((resolve) => setTimeout(resolve, 400));
    const scale = Math.min(1, requestedWidth / video.videoWidth);
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    canvas.getContext('2d', { alpha: false }).drawImage(video, 0, 0, canvas.width, canvas.height);
    window.cameraCapture.submit(canvas.toDataURL('image/jpeg', quality));
  } catch {
    window.cameraCapture.fail();
  } finally {
    if (stream) stream.getTracks().forEach((track) => track.stop());
    const video = document.querySelector('#camera');
    if (video) video.srcObject = null;
  }
}

capture();

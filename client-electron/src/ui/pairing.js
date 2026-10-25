'use strict';

const form = document.querySelector('#pairing-form');
const message = document.querySelector('#message');

window.jarvis.getPairing().then((config) => {
  document.querySelector('#url').value = config.url;
  if (config.error) message.textContent = config.error;
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  button.disabled = true;
  message.textContent = 'Connecting…';
  try {
    await window.jarvis.redeemAndConnect({
      url: document.querySelector('#url').value,
      code: document.querySelector('#code').value,
    });
    document.querySelector('#code').value = '';
    message.textContent = 'Device paired securely. Connection started.';
  } catch (error) {
    message.textContent = {
      insecure_url: 'Use an HTTPS backend URL. HTTP is allowed only for localhost in development.',
      invalid_pair_code: 'Enter the 8-character code shown in your JARVIS dashboard.',
      pair_code_expired_or_invalid: 'That code has expired or is invalid. Generate a new code in your dashboard.',
      backend_unavailable: 'Could not reach the backend. Check the URL and your connection.',
    }[error.message] || 'Pairing could not be completed. Check the code and backend URL.';
  } finally {
    button.disabled = false;
  }
});

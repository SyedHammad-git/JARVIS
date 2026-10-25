'use strict';

const form = document.querySelector('#pairing-form');
const message = document.querySelector('#message');

window.jarvis.getPairing().then((config) => {
  document.querySelector('#url').value = config.url;
  document.querySelector('#device-id').value = config.deviceId;
  document.querySelector('#token').required = !config.hasToken;
  document.querySelector('#token').placeholder = config.hasToken ? 'Saved securely; leave blank to keep it' : '';
  if (config.error) message.textContent = config.error;
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  button.disabled = true;
  message.textContent = 'Connecting…';
  try {
    await window.jarvis.saveAndConnect({
      url: document.querySelector('#url').value,
      deviceId: document.querySelector('#device-id').value,
      token: document.querySelector('#token').value,
    });
    document.querySelector('#token').value = '';
    message.textContent = 'Credentials encrypted. Connection started.';
  } catch (error) {
    message.textContent = error.message === 'insecure_url'
      ? 'Use an HTTPS backend URL. HTTP is allowed only for localhost in development.'
      : 'Could not save or connect. Check the URL and pairing details.';
  } finally {
    button.disabled = false;
  }
});

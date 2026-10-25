'use strict';

const connection = document.querySelector('#connection');
const lastCommand = document.querySelector('#last-command');

window.jarvis.getStatus().then((status) => {
  connection.textContent = status.state;
  lastCommand.textContent = status.lastCommand;
});
window.jarvis.onStatus((value) => { connection.textContent = value; });
window.jarvis.onLastCommand((value) => { lastCommand.textContent = value; });
document.querySelector('#pair').addEventListener('click', () => window.jarvis.openPairing());

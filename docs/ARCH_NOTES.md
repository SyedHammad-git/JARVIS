# Camera architecture

- Camera capture is opt-in and on-demand through the paired Electron client.
- The backend accepts bounded snapshot acknowledgements for vision processing.
- Never stream continuous camera frames through the backend.
- Do not enable camera capture automatically at launch.

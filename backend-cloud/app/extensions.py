"""Shared Flask extensions for the paired-device Socket.IO gateway."""
from flask_socketio import SocketIO

# cors_allowed_origins=[] : browser origins are not allowed. The Electron
# client and python-socketio fake device do not rely on browser CORS.
socketio = SocketIO(
    async_mode="threading",
    max_http_buffer_size=5_000_000,
    ping_interval=20,
    ping_timeout=25,
    cors_allowed_origins=[],
    logger=False,
    engineio_logger=False,
)

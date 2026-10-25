# Camera Architecture Notes
- Keep cloud camera access on-demand; do not stream video through the backend.
- Future local motion detection can run on the PC between user-requested snapshots.
- Future face detection should also remain local to the PC.
- Local detections should emit small `event` messages, not continuous frames.
- An event may include one opt-in, size-limited thumbnail for context.
- An optional Python OpenCV sidecar may be spawned and supervised by Electron.
- Bind any sidecar API to loopback only; never expose it on the network.
- Require explicit user consent before enabling local detection or thumbnails.
- This note describes a possible design; none of these features are implemented here.
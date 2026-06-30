"""Subject-aware reframing for 9:16 vertical crop.

Detects the dominant speaker/face position across a clip and returns the
horizontal pixel offset (`crop_x`) for a 9:16 crop window centred on the
subject — instead of a blind centre crop that can cut the speaker in half.

Design contract:
- This module reads the video (OpenCV). It NEVER builds ffmpeg commands.
  It only returns an integer x-offset that `render_core.build_crop_command`
  accepts as a parameter (keeps render_core pure).
- Graceful degradation is mandatory: if OpenCV is missing, the file cannot
  be read, or no face is found, `detect_crop_x` returns ``None`` and the
  caller falls back to the existing centre crop. Auto-reframe must never
  break a run.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional


def compute_crop_x(
    face_center_x: float,
    frame_w: int,
    frame_h: int,
    aspect_w: int = 9,
    aspect_h: int = 16,
) -> int:
    """Pure geometry: x-offset of a vertical crop window centred on a subject.

    The crop window width matches the ffmpeg expression ``ih*9/16`` so that
    the pixel offset computed here lines up with what ffmpeg crops at runtime
    (crop is the first spatial op, so cv2 pixel dims == ffmpeg input dims).

    The result is clamped so the window never leaves the frame.

    Args:
        face_center_x: subject centre on the horizontal axis, in pixels.
        frame_w: source frame width in pixels.
        frame_h: source frame height in pixels.
        aspect_w / aspect_h: target aspect ratio (default 9:16).

    Returns:
        Integer x-offset in pixels, in ``[0, frame_w - crop_w]``.
    """
    crop_w = frame_h * aspect_w / aspect_h
    if crop_w >= frame_w:
        # Source is already narrower than the target window — nothing to shift.
        return 0
    x = face_center_x - crop_w / 2.0
    max_x = frame_w - crop_w
    if x < 0:
        x = 0.0
    elif x > max_x:
        x = max_x
    return int(round(x))


def detect_crop_x(
    video_path: Path,
    start: float,
    end: float,
    samples: int = 12,
) -> Optional[int]:
    """Sample frames across ``[start, end]`` and return a subject-centred crop x.

    Returns ``None`` (→ caller keeps centre crop) when OpenCV is unavailable,
    the video cannot be opened, or no face is detected in any sampled frame.
    """
    try:
        import cv2  # imported lazily so the pipeline runs without opencv
    except ImportError:
        return None

    try:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if frame_w <= 0 or frame_h <= 0:
            cap.release()
            return None

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)
        if face_cascade.empty():
            cap.release()
            return None

        duration = max(0.0, end - start)
        if duration <= 0 or samples <= 0:
            cap.release()
            return None

        centers: List[float] = []
        for i in range(samples):
            # Even spread across the clip, avoiding the very first/last frame.
            t = start + duration * (i + 0.5) / samples
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5,
                minSize=(int(frame_h * 0.05), int(frame_h * 0.05)),
            )
            if len(faces) == 0:
                continue
            # Largest face = closest/dominant speaker.
            fx, _fy, fw, _fh = max(faces, key=lambda f: f[2] * f[3])
            centers.append(fx + fw / 2.0)

        cap.release()

        if not centers:
            return None

        centers.sort()
        median_cx = centers[len(centers) // 2]
        return compute_crop_x(median_cx, frame_w, frame_h)
    except Exception:
        # Any cv2/runtime hiccup must not break the pipeline.
        return None

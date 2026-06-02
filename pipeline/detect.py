"""YOLOv8 + ByteTrack detection pipeline for all store cameras."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from pipeline.emit import EventEmitter, make_event, utc_now_iso
from pipeline.staff_detector import classify_staff
from pipeline.tracker import VisitorTracker

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("detect")

ROOT = Path(__file__).resolve().parent.parent
LAYOUT_PATH = ROOT / "data" / "store_layout.json"
VIDEOS_DIR = ROOT / "data" / "videos"
EVENTS_PATH = ROOT / "data" / "events.jsonl"
CONF_THRESHOLD = 0.3


def resolve_video_path(filename: str) -> Path:
    """Accept both official CAM_1.mp4 names and downloaded CAM 1.mp4 names."""
    path = VIDEOS_DIR / filename
    if path.exists():
        return path

    alternates = {
        filename.replace("_", " "),
        filename.replace(" ", "_"),
    }
    for alt in alternates:
        alt_path = VIDEOS_DIR / alt
        if alt_path.exists():
            return alt_path

    return path
DWELL_INTERVAL_SEC = 30
STORE_ID = "STORE_BLR_002"


def load_layout() -> dict[str, Any]:
    with open(LAYOUT_PATH, encoding="utf-8") as f:
        return json.load(f)


def frame_timestamp(base: datetime, frame_idx: int, fps: float) -> str:
    t = base.timestamp() + frame_idx / max(fps, 1.0)
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def point_in_norm_zone(cx: float, cy: float, zone: dict[str, float]) -> bool:
    return zone["x1"] <= cx <= zone["x2"] and zone["y1"] <= cy <= zone["y2"]


class TrackState:
    def __init__(self, track_id: int, visitor_id: str, is_staff: bool):
        self.track_id = track_id
        self.visitor_id = visitor_id
        self.is_staff = is_staff
        self.last_y: Optional[float] = None
        self.side: Optional[str] = None  # above / below tripwire
        self.entered = False
        self.exited = False
        self.zones_active: dict[str, float] = {}  # zone_id -> start frame time
        self.last_dwell_emit: dict[str, float] = {}
        self.in_billing_queue = False
        self.billing_joined = False


def process_entry_camera(
    cap: cv2.VideoCapture,
    model: Any,
    camera_id: str,
    video_name: str,
    emitter: EventEmitter,
    visitor_tracker: VisitorTracker,
    tripwire_y: int,
    base_time: datetime,
    fps: float,
    date_str: str,
) -> None:
    frame_idx = 0
    states: dict[int, TrackState] = {}
    stride = max(1, int(fps / 10))  # ~10 detections per second

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % stride != 0:
            frame_idx += 1
            continue

        h, w = frame.shape[:2]
        ts = frame_timestamp(base_time, frame_idx, fps)
        now = datetime.fromisoformat(ts.replace("Z", "+00:00"))

        results = model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[0],
            conf=CONF_THRESHOLD,
            verbose=False,
        )

        active_ids: set[int] = set()
        if results and results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes
            for i in range(len(boxes)):
                tid = int(boxes.id[i].item())
                active_ids.add(tid)
                x1, y1, x2, y2 = map(int, boxes.xyxy[i].tolist())
                conf = float(boxes.conf[i].item())
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2

                is_staff = classify_staff(camera_id, frame, x1, y1, x2, y2)
                if tid not in states:
                    vid, is_reentry = visitor_tracker.get_or_create_visitor(
                        camera_id, tid, date_str, frame, x1, y1, x2, y2, now
                    )
                    states[tid] = TrackState(tid, vid, is_staff)
                    states[tid]._pending_reentry = is_reentry
                    side = "below" if cy > tripwire_y else "above"
                    states[tid].side = side
                    states[tid].last_y = cy
                st = states[tid]
                st.is_staff = is_staff

                prev_y = st.last_y
                st.last_y = cy
                if prev_y is None:
                    frame_idx += 1
                    continue

                # Cross tripwire: below (y>540) -> above (y<540) = ENTRY
                if not st.entered and prev_y > tripwire_y and cy <= tripwire_y:
                    is_reentry = getattr(st, "_pending_reentry", False)
                    etype = "REENTRY" if is_reentry else "ENTRY"
                    st.entered = True
                    emitter.emit(
                        make_event(
                            camera_id=camera_id,
                            visitor_id=st.visitor_id,
                            event_type=etype,
                            zone_id="ENTRY_EXIT",
                            dwell_ms=0,
                            is_staff=st.is_staff,
                            confidence=conf,
                            timestamp=ts,
                            metadata={"queue_depth": None, "sku_zone": None},
                        )
                    )
                elif not st.exited and prev_y < tripwire_y and cy >= tripwire_y:
                    st.exited = True
                    emitter.emit(
                        make_event(
                            camera_id=camera_id,
                            visitor_id=st.visitor_id,
                            event_type="EXIT",
                            zone_id="ENTRY_EXIT",
                            dwell_ms=0,
                            is_staff=st.is_staff,
                            confidence=conf,
                            timestamp=ts,
                        )
                    )
                    visitor_tracker.record_exit(
                        st.visitor_id, frame, x1, y1, x2, y2, now
                    )

        frame_idx += 1

    cap.release()


def process_zone_camera(
    cap: cv2.VideoCapture,
    model: Any,
    camera_id: str,
    zones: list[str],
    emitter: EventEmitter,
    visitor_tracker: VisitorTracker,
    base_time: datetime,
    fps: float,
    date_str: str,
    billing_zone: Optional[dict[str, float]] = None,
) -> None:
    frame_idx = 0
    states: dict[int, TrackState] = {}
    stride = max(1, int(fps / 10))
    h_frame = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    w_frame = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % stride != 0:
            frame_idx += 1
            continue

        ts = frame_timestamp(base_time, frame_idx, fps)
        now = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        t_sec = frame_idx / max(fps, 1.0)

        results = model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[0],
            conf=CONF_THRESHOLD,
            verbose=False,
        )

        if not (results and results[0].boxes is not None and results[0].boxes.id is not None):
            frame_idx += 1
            continue

        boxes = results[0].boxes
        queue_count = 0

        for i in range(len(boxes)):
            tid = int(boxes.id[i].item())
            x1, y1, x2, y2 = map(int, boxes.xyxy[i].tolist())
            conf = float(boxes.conf[i].item())
            cx_n = ((x1 + x2) / 2) / w_frame
            cy_n = ((y1 + y2) / 2) / h_frame

            is_staff = classify_staff(camera_id, frame, x1, y1, x2, y2)
            if tid not in states:
                vid, _ = visitor_tracker.get_or_create_visitor(
                    camera_id, tid, date_str, frame, x1, y1, x2, y2, now
                )
                states[tid] = TrackState(tid, vid, is_staff)
            st = states[tid]
            st.is_staff = is_staff

            primary_zone = zones[0] if zones else None
            in_billing = False
            if billing_zone and point_in_norm_zone(cx_n, cy_n, billing_zone):
                in_billing = True
                if not st.is_staff:
                    queue_count += 1

            if primary_zone:
                if primary_zone not in st.zones_active:
                    st.zones_active[primary_zone] = t_sec
                    emitter.emit(
                        make_event(
                            camera_id=camera_id,
                            visitor_id=st.visitor_id,
                            event_type="ZONE_ENTER",
                            zone_id=primary_zone,
                            is_staff=st.is_staff,
                            confidence=conf,
                            timestamp=ts,
                        )
                    )
                else:
                    elapsed = t_sec - st.zones_active[primary_zone]
                    last_emit = st.last_dwell_emit.get(primary_zone, 0)
                    if elapsed - last_emit >= DWELL_INTERVAL_SEC:
                        st.last_dwell_emit[primary_zone] = elapsed
                        dwell_ms = int(DWELL_INTERVAL_SEC * 1000)
                        emitter.emit(
                            make_event(
                                camera_id=camera_id,
                                visitor_id=st.visitor_id,
                                event_type="ZONE_DWELL",
                                zone_id=primary_zone,
                                dwell_ms=dwell_ms,
                                is_staff=st.is_staff,
                                confidence=conf,
                                timestamp=ts,
                                metadata={"sku_zone": primary_zone},
                            )
                        )

            if in_billing and not st.billing_joined and not st.is_staff:
                st.billing_joined = True
                st.in_billing_queue = True
                emitter.emit(
                    make_event(
                        camera_id=camera_id,
                        visitor_id=st.visitor_id,
                        event_type="BILLING_QUEUE_JOIN",
                        zone_id="BILLING",
                        is_staff=st.is_staff,
                        confidence=conf,
                        timestamp=ts,
                        metadata={"queue_depth": queue_count},
                    )
                )
            elif st.in_billing_queue and not in_billing and st.billing_joined:
                st.in_billing_queue = False
                emitter.emit(
                    make_event(
                        camera_id=camera_id,
                        visitor_id=st.visitor_id,
                        event_type="BILLING_QUEUE_ABANDON",
                        zone_id="BILLING",
                        is_staff=st.is_staff,
                        confidence=conf,
                        timestamp=ts,
                    )
                )

        frame_idx += 1

    cap.release()


def run_pipeline(api_url: Optional[str] = None, video_limit: Optional[int] = None) -> int:
    from ultralytics import YOLO

    layout = load_layout()
    mapping = layout["camera_mapping"]
    camera_zones = layout.get("camera_zones", {})
    tripwire = layout.get("tripwire", {}).get("CAM_ENTRY_03", {}).get("y", 540)
    billing = layout.get("billing_zone", {}).get("CAM_BILLING_05")

    if EVENTS_PATH.exists():
        EVENTS_PATH.unlink()

    emitter = EventEmitter(EVENTS_PATH, api_url=api_url or os.environ.get("API_URL"))
    visitor_tracker = VisitorTracker()
    model = YOLO("yolov8m.pt")

    base_time = datetime(2026, 4, 10, 14, 39, 0, tzinfo=timezone.utc)
    date_str = "2026-04-10"
    count = 0

    for cam_logical, filename in mapping.items():
        if video_limit is not None and count >= video_limit:
            break
        path = resolve_video_path(filename)
        if not path.exists():
            logger.warning("Skipping missing video: %s", path)
            continue

        logger.info("Processing %s (%s)", cam_logical, filename)
        cap = cv2.VideoCapture(str(path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        zones = camera_zones.get(cam_logical, [])

        if cam_logical == "CAM_ENTRY_03":
            process_entry_camera(
                cap,
                model,
                cam_logical,
                filename,
                emitter,
                visitor_tracker,
                tripwire,
                base_time,
                fps,
                date_str,
            )
        elif cam_logical == "CAM_BILLING_05":
            bz = billing if isinstance(billing, dict) else None
            process_zone_camera(
                cap,
                model,
                cam_logical,
                zones,
                emitter,
                visitor_tracker,
                base_time,
                fps,
                date_str,
                billing_zone=bz,
            )
        else:
            process_zone_camera(
                cap,
                model,
                cam_logical,
                zones,
                emitter,
                visitor_tracker,
                base_time,
                fps,
                date_str,
            )
        count += 1

    sent = emitter.flush_to_api()
    logger.info("Pipeline complete. Events written to %s. Ingested to API: %d", EVENTS_PATH, sent)
    return sent


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=os.environ.get("API_URL", "http://localhost:8000"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    run_pipeline(api_url=args.api_url, video_limit=args.limit)

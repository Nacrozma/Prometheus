#!/usr/bin/env python3
"""
arm_demo.py - run the gesture-controlled arm pipeline.

    python arm_demo.py --synthetic                # scripted hand, simulated arm (works anywhere; tested)
    python arm_demo.py --synthetic --svg docs/    # also write pose and workspace images
    python arm_demo.py --camera                   # webcam + MediaPipe -> simulated arm   (NOT tested by the author)
    python arm_demo.py --camera --port COM5       # ... driving a real arm over serial    (NOT tested by the author)

Real-hardware safety: power the servos from their own 5-6 V supply (common ground with the board),
keep a physical switch on that supply, start with the arm clear of people and the table, and press q
(or Ctrl+C) to stop: the program sends ESTOP on the way out. ESTOP stops motion but does not cut power.
"""
import argparse
import math
import os
import sys
import time

import arm_bridge as br
import arm_gesture as gest
import arm_sim


def synthetic_session(frames: int = 300, fps: int = 30):
    """A scripted hand: settle, sweep right while reaching out, rise, then pinch to close the gripper."""
    for i in range(frames):
        u = i / frames
        if u < 0.1:
            cx, cy, ps, pinch = 0.35, 0.55, 0.11, 1.0
        else:
            v = (u - 0.1) / 0.9
            cx, cy = 0.35 + 0.30 * v, 0.55 - 0.20 * math.sin(math.pi * v)
            ps = 0.11 + 0.06 * v
            pinch = 1.0 if v < 0.75 else 0.15
        yield gest.synthetic_hand(cx, cy, ps, pinch)


def run(frames_iter, transport, fps: int = 30, on_frame=None) -> dict:
    host = br.ArmBridge(transport)
    ctrl = gest.GestureController(arm_after=6)
    sent = held = 0
    last = None
    try:
        for frame in frames_iter:
            cmd = ctrl.step(frame)
            host.heartbeat()                           # keeps the firmware watchdog happy even when nothing moves
            if cmd.send:
                host.send_angles(cmd.servo_deg)
                sent += 1
                last = cmd
            held += cmd.state == "holding"
            if isinstance(transport, br.SimTransport):
                transport.advance(1 / fps)
            else:
                time.sleep(1 / fps)
            if on_frame:
                on_frame(cmd)
    finally:
        host.estop()                                   # whatever happened, leave the arm frozen
    return {"commands_sent": sent, "frames_holding": held, "last": last, "rejected_frames": ctrl.rejected_frames}


def camera_frames(camera_index: int = 0):
    """Yield 21-point landmark lists from the webcam (or None when no hand is seen). Needs opencv-python
    and mediapipe (requirements-arm.txt). Written against MediaPipe's legacy `mp.solutions.hands` API; if your
    version removed it, install an older mediapipe. NOT tested by the author: this needs a webcam."""
    try:
        import cv2
        import mediapipe as mp
    except ImportError as e:
        raise SystemExit(f"--camera needs opencv-python and mediapipe ({e}). pip install -r requirements-arm.txt")
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise SystemExit(f"cannot open camera {camera_index}")
    hands = mp.solutions.hands.Hands(max_num_hands=1, min_detection_confidence=0.6, min_tracking_confidence=0.6)
    try:
        while True:
            ok, bgr = cap.read()
            if not ok:
                yield None
                continue
            result = hands.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            lms = result.multi_hand_landmarks[0].landmark if result.multi_hand_landmarks else None
            cv2.imshow("hand (press q to stop)", cv2.flip(bgr, 1))
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                return
            yield [(p.x, p.y, p.z) for p in lms] if lms else None
    finally:
        cap.release()
        cv2.destroyAllWindows()


def write_svgs(outdir: str, last_cmd) -> None:
    os.makedirs(outdir, exist_ok=True)
    ws = arm_sim.workspace(step=0.01)
    pose = last_cmd.joints_deg if last_cmd else (0, 60, -60, 0)
    with open(os.path.join(outdir, "arm_pose.svg"), "w", encoding="utf-8") as f:
        f.write(arm_sim.render_svg(pose, target=last_cmd.target_m if last_cmd else None, points=ws["points"],
                                   title="IK solution for the last gesture target (green ring), reachable workspace in blue"))
    print(f"wrote {os.path.join(outdir, 'arm_pose.svg')}  (reach {ws['max_radius_m'] * 100:.0f} cm, height {ws['max_height_m'] * 100:.0f} cm, "
          f"{ws['reachable_fraction'] * 100:.0f}% of sampled plane reachable)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", action="store_true")
    src.add_argument("--camera", action="store_true")
    ap.add_argument("--port", help="serial port of a real arm (omit to drive the simulator)")
    ap.add_argument("--svg", metavar="DIR", help="write arm_pose.svg into DIR")
    args = ap.parse_args(argv)

    transport = br.SerialTransport(args.port) if args.port else br.SimTransport()
    if args.port and not args.synthetic:
        print("REAL ARM: servo supply on its own switch? arm clear of people and the table? Press q to stop.")
    frames = synthetic_session() if args.synthetic else camera_frames()
    try:
        summary = run(frames, transport)
    except KeyboardInterrupt:
        print("stopped")
        return 130
    finally:
        transport.close()
    print(f"commands sent: {summary['commands_sent']}   frames holding: {summary['frames_holding']}   rejected: {summary['rejected_frames']}")
    if isinstance(transport, br.SimTransport):
        fw = transport.firmware
        print(f"firmware model: state={fw.state} (2 = estop, as sent on exit)  clamped commands={fw.clamped_commands}  "
              f"final servo angles={[round(v, 1) for v in fw.current]}")
    if args.svg:
        write_svgs(args.svg, summary["last"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
arm_gesture.py - turn hand landmarks (21 points, MediaPipe Hands layout) into arm commands.

The mapping (selfie view by default, so moving your hand to YOUR right moves the arm to ITS right):
    hand left/right in the image      -> arm sideways (y)
    hand up/down in the image         -> arm height (z)
    hand closer to / farther from the camera (palm looks bigger/smaller) -> arm reach (x)
    thumb-to-index pinch              -> gripper (open hand = open gripper)

What stands between a noisy webcam and a servo:
  * validation   - wrong shape, NaN, off-screen, or a degenerate/too-small hand is rejected
  * arming       - the arm only starts following after the hand has been stable for several frames
  * outlier gate - a one-frame jump (tracker glitch) is ignored unless it persists
  * smoothing    - exponential filter + dead-band so sensor jitter doesn't reach the servos
  * workspace    - a target outside what the arm can reach is pulled back to the reachable boundary
  * hand lost    - the arm holds its last pose, then stops following (it never "returns" by itself)
  * downstream   - arm_bridge adds slew limits, limits, a watchdog and an e-stop

The pure-Python pipeline is tested with synthetic hands (tests/test_arm_gesture.py). Whether the real
MediaPipe tracker gives landmarks good enough for this has NOT been tested by the author: that needs a
webcam and is the first thing to try (see arm_demo.py --camera).
"""
import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import arm_sim

WRIST, THUMB_TIP, INDEX_MCP, INDEX_TIP, MIDDLE_MCP, RING_MCP, PINKY_MCP = 0, 4, 5, 8, 9, 13, 17
PALM_POINTS = (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)
Point = Tuple[float, float, float]


@dataclass(frozen=True)
class Calibration:
    palm_far: float = 0.07        # palm size (wrist to middle knuckle, image-width units) with the hand far away
    palm_near: float = 0.20       # ... and close to the camera
    reach_min: float = 0.14       # arm reach [m] for the far hand
    reach_max: float = 0.28       # ... and the near hand
    y_span: float = 0.30          # total sideways travel [m]
    z_min: float = 0.05           # arm height range [m]
    z_max: float = 0.28
    pinch_closed: float = 0.25    # thumb-index distance / palm size at or below which the gripper is closed
    pinch_open: float = 1.00      # ... and at or above which it is fully open
    gripper_closed_deg: float = 25.0
    gripper_open_deg: float = 90.0
    mirror: bool = True


@dataclass
class HandFeatures:
    center_x: float
    center_y: float
    palm_size: float
    pinch: float


@dataclass
class Command:
    state: str                              # idle | arming | tracking | holding
    send: bool                              # False: do not command the arm this frame
    target_m: Optional[Tuple[float, float, float]] = None
    joints_deg: Optional[Tuple[float, ...]] = None
    servo_deg: Optional[Tuple[float, ...]] = None      # yaw, shoulder, elbow, wrist, gripper
    clamped: bool = False
    reason: str = ""


def hand_features(landmarks: Sequence[Sequence[float]], min_palm: float = 0.02) -> Tuple[Optional[HandFeatures], str]:
    """Validate 21 landmarks and extract (centre, palm size, pinch). Returns (None, why) if unusable."""
    if not isinstance(landmarks, (list, tuple)) or len(landmarks) != 21:
        return None, "expected 21 landmarks"
    pts: List[Point] = []
    for p in landmarks:
        try:
            x, y, z = float(p[0]), float(p[1]), float(p[2])
        except (TypeError, ValueError, IndexError):
            return None, "malformed landmark"
        if not all(math.isfinite(v) for v in (x, y, z)):
            return None, "non-finite landmark"
        if not (-0.2 <= x <= 1.2 and -0.2 <= y <= 1.2):
            return None, "landmark far outside the image"
        pts.append((x, y, z))
    palm = math.hypot(pts[WRIST][0] - pts[MIDDLE_MCP][0], pts[WRIST][1] - pts[MIDDLE_MCP][1])
    if palm < min_palm:
        return None, "hand too small or degenerate"
    cx = sum(pts[i][0] for i in PALM_POINTS) / len(PALM_POINTS)
    cy = sum(pts[i][1] for i in PALM_POINTS) / len(PALM_POINTS)
    pinch = math.hypot(pts[THUMB_TIP][0] - pts[INDEX_TIP][0], pts[THUMB_TIP][1] - pts[INDEX_TIP][1]) / palm
    return HandFeatures(cx, cy, palm, pinch), ""


def _lerp(a: float, b: float, t: float) -> float:
    t = max(0.0, min(1.0, t))
    return a * (1.0 - t) + b * t            # exact at both ends (a + (b - a) * t is not)


def features_to_target(f: HandFeatures, c: Calibration) -> Tuple[Tuple[float, float, float], float]:
    """(x, y, z) target in metres and gripper openness 0..1."""
    x = _lerp(c.reach_min, c.reach_max, (f.palm_size - c.palm_far) / (c.palm_near - c.palm_far))
    lateral = (f.center_x - 0.5) * c.y_span / 0.6                     # the central 60% of the image spans y_span
    y = -lateral if c.mirror else lateral
    y = max(-c.y_span / 2, min(c.y_span / 2, y))
    z = _lerp(c.z_max, c.z_min, (f.center_y - 0.2) / 0.6)             # image y grows downward; the central band maps to the range
    openness = max(0.0, min(1.0, (f.pinch - c.pinch_closed) / (c.pinch_open - c.pinch_closed)))
    return (x, y, z), openness


def nearest_reachable(target: Tuple[float, float, float], pitch_deg: Optional[float], arm: arm_sim.ArmSpec,
                      home: Tuple[float, float, float]) -> Tuple[Optional[Tuple[float, float, float]], Optional[arm_sim.IKResult]]:
    """The reachable point closest to `target` along the line from a known-reachable `home` point."""
    res = arm_sim.inverse(*target, pitch_deg, arm)
    if res.reachable:
        return target, res
    if not arm_sim.inverse(*home, pitch_deg, arm).reachable:
        return None, None
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        p = tuple(h + (t - h) * mid for h, t in zip(home, target))
        if arm_sim.inverse(*p, pitch_deg, arm).reachable:
            lo = mid
        else:
            hi = mid
    p = tuple(h + (t - h) * lo for h, t in zip(home, target))
    return p, arm_sim.inverse(*p, pitch_deg, arm)


class GestureController:
    def __init__(self, arm: arm_sim.ArmSpec = arm_sim.DEFAULT_ARM, calib: Calibration = Calibration(),
                 alpha: float = 0.35, deadband_m: float = 0.004, max_jump_m: float = 0.08, arm_after: int = 6,
                 hold_lost_frames: int = 15, pitch_deg: Optional[float] = -45.0, home: Tuple[float, float, float] = (0.17, 0.0, 0.12)):
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0, 1]")
        self.arm, self.calib, self.alpha = arm, calib, alpha
        self.deadband, self.max_jump, self.arm_after = deadband_m, max_jump_m, arm_after
        self.hold_lost_frames, self.pitch, self.home = hold_lost_frames, pitch_deg, home
        self.reset()

    def reset(self) -> None:
        self.state = "idle"
        self._stable = 0
        self._lost = 0
        self._filtered: Optional[List[float]] = None
        self._open = 1.0
        self._last_sent: Optional[Command] = None
        self._outliers = 0
        self._last_center: Optional[Tuple[float, float]] = None
        self.rejected_frames = 0

    def _hold(self, why: str) -> Command:
        if self._last_sent is not None and self.state == "holding":
            c = self._last_sent
            return Command("holding", True, c.target_m, c.joints_deg, c.servo_deg, c.clamped, why)
        return Command(self.state, False, reason=why)

    def step(self, landmarks: Optional[Sequence[Sequence[float]]]) -> Command:
        feats, why = (None, "no hand") if landmarks is None else hand_features(landmarks)
        if feats is None:
            self.rejected_frames += landmarks is not None
            self._lost += 1
            self._stable = 0
            if self.state in ("tracking", "holding") and self._lost <= self.hold_lost_frames:
                self.state = "holding"
                return self._hold(why)
            if self.state != "idle":
                self.state = "idle"
                self._filtered = None
                self._last_center = None
            return Command("idle", False, reason=why)
        self._lost = 0
        center = (feats.center_x, feats.center_y)
        raw, openness = features_to_target(feats, self.calib)

        if self.state in ("idle", "arming"):
            # arming: the hand must hold roughly still for several frames before the arm follows it
            steady = self._last_center is not None and math.dist(center, self._last_center) < 0.05
            self._stable = self._stable + 1 if (steady or self.state == "idle") else 1
            self._last_center = center
            self.state = "arming"
            if self._stable < self.arm_after:
                return Command("arming", False, reason=f"hold still ({self._stable}/{self.arm_after})")
            self.state = "tracking"
            self._filtered = list(raw)
            self._open = openness
        elif self.state == "holding":
            self.state = "tracking"                                     # hand is back: continue from the filtered position

        assert self._filtered is not None
        jump = math.dist(raw, self._filtered)
        if jump > self.max_jump:
            self._outliers += 1
            if self._outliers < 5:                                       # a lone glitch is ignored; a persistent move is real
                self.rejected_frames += 1
                return self._resend("ignored a sudden jump")
        self._outliers = 0
        if jump >= self.deadband:
            self._filtered = [f + self.alpha * (r - f) for f, r in zip(self._filtered, raw)]
        self._open += self.alpha * (openness - self._open)

        target, ik = nearest_reachable(tuple(self._filtered), self.pitch, self.arm, self.home)
        if target is None or ik is None or not ik.reachable:
            return Command("tracking", False, reason="no reachable pose near the target")
        clamped = math.dist(target, self._filtered) > 1e-4
        grip = _lerp(self.calib.gripper_closed_deg, self.calib.gripper_open_deg, self._open)
        servo = arm_sim.to_servo_angles(ik.joints_deg, self.arm) + (round(grip, 2),)
        cmd = Command("tracking", True, tuple(round(v, 4) for v in target), ik.joints_deg, servo, clamped,
                      "target pulled back to the edge of the workspace" if clamped else "")
        self._last_sent = cmd
        return cmd

    def _resend(self, why: str) -> Command:
        c = self._last_sent
        if c is None:
            return Command("tracking", False, reason=why)
        return Command("tracking", True, c.target_m, c.joints_deg, c.servo_deg, c.clamped, why)


# ------------------------------------------------------------------------------ synthetic hands (tests and demo)
def synthetic_hand(cx: float, cy: float, palm_size: float, pinch: float = 1.0) -> List[Point]:
    """A 21-point hand with the given palm centre, palm size and thumb-index pinch ratio. A caricature:
    only the points the controller uses are placed meaningfully."""
    ps = palm_size
    pts: List[Point] = [(cx, cy - ps, 0.0) for _ in range(21)]
    pts[WRIST] = (cx, cy + 0.5 * ps, 0.0)
    pts[INDEX_MCP] = (cx - 0.4 * ps, cy - 0.45 * ps, 0.0)
    pts[MIDDLE_MCP] = (cx, cy - 0.5 * ps, 0.0)
    pts[RING_MCP] = (cx + 0.4 * ps, cy - 0.45 * ps, 0.0)
    pts[PINKY_MCP] = (cx, cy - 0.1 * ps, 0.0)
    pts[INDEX_TIP] = (cx - 0.4 * ps, cy - 1.4 * ps, 0.0)
    pts[THUMB_TIP] = (cx - 0.4 * ps + pinch * ps, cy - 1.4 * ps, 0.0)
    # the palm centre is the mean of five points; shift so it lands exactly on (cx, cy)
    mx = sum(pts[i][0] for i in PALM_POINTS) / 5
    my = sum(pts[i][1] for i in PALM_POINTS) / 5
    return [(x - (mx - cx), y - (my - cy), z) for x, y, z in pts]

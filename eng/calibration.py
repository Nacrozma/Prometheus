"""Measured arm parameters with provenance.

Every physical parameter the arm models use (link lengths, masses, centre-of-mass positions, joint offsets,
servo torque and speed) is a `Parameter`: a value, its unit and its *status*:

    provisional  a placeholder (the defaults in arm_sim.py). Usable for simulation, never presented as measured.
    measured     a real measurement. Requires the method, the equipment, a standard uncertainty, the date and who
                 or what produced it. Missing provenance is an error, not a warning.

A calibration file (JSON) holds only the parameters that have been measured; everything else stays provisional
and is reported as such. Nothing is substituted silently: `Calibration.summary()` lists what is still
provisional, and `arm_spec()` / `masses()` say which values they used.
"""
import datetime as _dt
import json
import math
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

import arm_sim

from . import EngError

STATUSES = ("provisional", "measured")

# name -> (default value, unit, description, how to measure it)
PARAMETERS: Dict[str, tuple] = {
    "L0": (arm_sim.DEFAULT_ARM.L0, "m", "shoulder axis height above the table", "calliper / steel rule from table to shoulder servo axis"),
    "L1": (arm_sim.DEFAULT_ARM.L1, "m", "upper arm: shoulder axis to elbow axis", "calliper between the two servo output-shaft centres"),
    "L2": (arm_sim.DEFAULT_ARM.L2, "m", "forearm: elbow axis to wrist axis", "calliper between the two servo output-shaft centres"),
    "L3": (arm_sim.DEFAULT_ARM.L3, "m", "wrist axis to gripper tip (tool centre point)", "calliper from wrist axis to the closed-gripper tip"),
    "m_link1": (arm_sim.Masses().link1, "kg", "upper-arm structure (without servos)", "kitchen/lab scale, part removed"),
    "m_link2": (arm_sim.Masses().link2, "kg", "forearm structure (without servos)", "scale, part removed"),
    "m_elbow_servo": (arm_sim.Masses().elbow_servo, "kg", "elbow servo incl. horn and screws", "scale"),
    "m_wrist_servo": (arm_sim.Masses().wrist_servo, "kg", "wrist servo incl. horn and screws", "scale"),
    "m_tool": (arm_sim.Masses().tool, "kg", "gripper incl. its servo", "scale"),
    "com_link1": (0.5, "fraction of L1", "upper-arm centre of mass from the shoulder axis", "balance the part on a knife edge, measure from the axis"),
    "com_link2": (0.5, "fraction of L2", "forearm centre of mass from the elbow axis", "knife-edge balance"),
    "com_tool": (0.5, "fraction of L3", "gripper centre of mass from the wrist axis", "knife-edge balance"),
    "offset_yaw": (0.0, "deg", "yaw servo angle error at the commanded rest pose", "protractor / phone inclinometer at REST_DEG"),
    "offset_shoulder": (0.0, "deg", "shoulder joint angle error at rest", "inclinometer on the upper arm"),
    "offset_elbow": (0.0, "deg", "elbow joint angle error at rest", "inclinometer on the forearm"),
    "offset_wrist": (0.0, "deg", "wrist joint angle error at rest", "inclinometer on the gripper"),
    "servo_stall_torque": (arm_sim.SERVOS["MG996R"] * 0.0980665, "N m", "servo stall torque at the supply voltage used", "lever + force gauge or hanging mass at known radius until stall (supervised)"),
    "servo_no_load_speed": (math.radians(60) / 0.14, "rad/s", "servo no-load speed", "time a 60 degree move with video at known frame rate"),
}


@dataclass
class Parameter:
    name: str
    value: float
    unit: str
    status: str = "provisional"
    method: str = ""
    equipment: str = ""
    uncertainty: Optional[float] = None       # standard uncertainty, same unit as value
    date: str = ""                            # ISO date of the measurement
    source: str = ""                          # who / which experiment record produced it
    notes: str = ""

    def validate(self) -> None:
        if self.name not in PARAMETERS:
            raise EngError(f"unknown arm parameter '{self.name}'. Known: {', '.join(PARAMETERS)}")
        unit = PARAMETERS[self.name][1]
        if self.unit != unit:
            raise EngError(f"'{self.name}' must be given in {unit} (got {self.unit})")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not math.isfinite(self.value):
            raise EngError(f"'{self.name}' value must be a finite number")
        if self.status not in STATUSES:
            raise EngError(f"status must be one of {STATUSES}")
        if self.name.startswith(("L", "m_")) and self.value <= 0:
            raise EngError(f"'{self.name}' must be positive")
        if self.name.startswith("com_") and not 0 <= self.value <= 1:
            raise EngError(f"'{self.name}' is a fraction of the link length: 0..1")
        if self.status == "measured":
            missing = [k for k in ("method", "equipment", "date", "source") if not str(getattr(self, k)).strip()]
            if self.uncertainty is None:
                missing.append("uncertainty")
            if missing:
                raise EngError(f"measured '{self.name}' needs its provenance: {', '.join(missing)}")
            if not (isinstance(self.uncertainty, (int, float)) and math.isfinite(self.uncertainty) and self.uncertainty >= 0):
                raise EngError(f"uncertainty of '{self.name}' must be a non-negative number")
            try:
                _dt.date.fromisoformat(self.date)
            except ValueError:
                raise EngError(f"date of '{self.name}' must be ISO (YYYY-MM-DD)") from None


def provisional(name: str) -> Parameter:
    v, unit, desc, _how = PARAMETERS[name]
    return Parameter(name, float(v), unit, "provisional", notes=f"placeholder: {desc}")


@dataclass
class Calibration:
    params: Dict[str, Parameter] = field(default_factory=lambda: {n: provisional(n) for n in PARAMETERS})

    @classmethod
    def from_dict(cls, data: dict) -> "Calibration":
        if not isinstance(data, dict) or not isinstance(data.get("parameters", []), list):
            raise EngError("calibration file must be an object with a 'parameters' list")
        cal = cls()
        for raw in data.get("parameters", []):
            if not isinstance(raw, dict):
                raise EngError("each parameter must be an object")
            known = {k: raw[k] for k in Parameter.__dataclass_fields__ if k in raw}
            p = Parameter(**known)
            p.validate()
            cal.params[p.name] = p
        return cal

    @classmethod
    def load(cls, path: str) -> "Calibration":
        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as f:
            try:
                return cls.from_dict(json.load(f))
            except json.JSONDecodeError as e:
                raise EngError(f"calibration file is not valid JSON: {e}") from None

    def set_measured(self, name: str, value: float, unit: str, method: str, equipment: str, uncertainty: float,
                     date: str, source: str, notes: str = "") -> Parameter:
        p = Parameter(name, value, unit, "measured", method, equipment, uncertainty, date, source, notes)
        p.validate()
        self.params[name] = p
        return p

    def to_dict(self) -> dict:
        return {"schema": "prometheus.arm_calibration/1",
                "parameters": [asdict(p) for p in self.params.values() if p.status == "measured"]}

    def save(self, path: str) -> None:
        import state_io
        if not state_io.atomic_write_json(path, self.to_dict()):
            raise EngError(f"could not write {path}")

    def value(self, name: str) -> float:
        return float(self.params[name].value)

    def provisional_names(self) -> List[str]:
        return [n for n, p in self.params.items() if p.status != "measured"]

    def summary(self) -> dict:
        return {"measured": sorted(n for n, p in self.params.items() if p.status == "measured"),
                "provisional": sorted(self.provisional_names()),
                "fully_measured": not self.provisional_names()}

    def arm_spec(self) -> arm_sim.ArmSpec:
        base = arm_sim.DEFAULT_ARM
        return arm_sim.ArmSpec(L0=self.value("L0"), L1=self.value("L1"), L2=self.value("L2"), L3=self.value("L3"),
                               floor_clearance=base.floor_clearance, joints=base.joints)

    def masses(self) -> arm_sim.Masses:
        return arm_sim.Masses(link1=self.value("m_link1"), link2=self.value("m_link2"), elbow_servo=self.value("m_elbow_servo"),
                              wrist_servo=self.value("m_wrist_servo"), tool=self.value("m_tool"))

    def joint_offsets_deg(self) -> tuple:
        return tuple(self.value(f"offset_{j}") for j in ("yaw", "shoulder", "elbow", "wrist"))


def template() -> dict:
    """A fill-in sheet: every parameter, what to measure and how, with the provenance fields left empty."""
    rows = []
    for name, (v, unit, desc, how) in PARAMETERS.items():
        rows.append({"name": name, "unit": unit, "description": desc, "suggested_method": how,
                     "provisional_value": v, "value": None, "uncertainty": None, "equipment": "", "date": "", "source": ""})
    return {"schema": "prometheus.arm_calibration_sheet/1", "rows": rows,
            "instructions": "Measure with the servo supply OFF. Repeat each measurement at least 3 times; the value is the mean, "
                            "the uncertainty combines the spread (s/sqrt(n)) with the instrument resolution (resolution/sqrt(12)). "
                            "Use eng.uncertainty.measurement_summary to compute both."}

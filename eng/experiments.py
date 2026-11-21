"""Engineering experiment records: what was run, with what, by which model version, and what came out.

A record is a JSON file (atomic write) in the experiments folder; tabular data (measurements, logged sensor rows,
simulation series) sits beside it as CSV. Records are the authoritative store of engineering results; a memory note
may point to one, but memory is never the source of truth.

Validation status is restricted to these classes, and the strongest one is guarded:
    analytically verified        the model reproduces a closed-form or published reference
    numerically verified         convergence / consistency checks (e.g. timestep refinement, energy balance)
    simulation tested            run in simulation only
    hardware tested              ONLY for kind == "hardware" records with attached measured data files
    awaiting physical validation the software is ready; the physical experiment has not been done

`rerun(id)` executes the stored model with the stored inputs and reports the largest relative difference, so any
earlier result can be reproduced and checked against the current code.
"""
import csv
import datetime as _dt
import hashlib
import io
import json
import math
import os
import re
import secrets
import time
from typing import Any, Dict, Iterable, List, Optional

from . import EngError, MODEL_VERSION

KINDS = ("calculation", "simulation", "analysis", "hardware")
STATUSES = ("analytically verified", "numerically verified", "simulation tested", "hardware tested", "awaiting physical validation")


def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def input_hash(model: str, inputs: dict) -> str:
    blob = json.dumps({"model": model, "inputs": inputs}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _software() -> dict:
    out = {"eng_model_version": MODEL_VERSION}
    try:
        from app import __version__ as v
        out["prometheus_version"] = v
    except Exception:
        pass
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    head = os.path.join(root, ".git", "HEAD")
    try:
        ref = open(head, encoding="utf-8").read().strip()
        if ref.startswith("ref:"):
            p = os.path.join(root, ".git", ref[5:])
            if os.path.exists(p):
                out["git_commit"] = open(p, encoding="utf-8").read().strip()[:12]
        else:
            out["git_commit"] = ref[:12]
    except OSError:
        pass
    return out


class ExperimentStore:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, eid: str) -> str:
        if not re.fullmatch(r"EXP-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", eid or ""):
            raise EngError("not a valid experiment id")
        return os.path.join(self.root, eid + ".json")

    def save(self, rec: dict) -> dict:
        import state_io
        if rec.get("kind") not in KINDS:
            raise EngError(f"kind must be one of {KINDS}")
        if rec.get("validation_status") not in STATUSES:
            raise EngError(f"validation_status must be one of {STATUSES}")
        if rec["validation_status"] == "hardware tested" and not (rec["kind"] == "hardware" and rec.get("data_files")):
            raise EngError("'hardware tested' needs a hardware experiment with its measured data attached; "
                           "use 'awaiting physical validation' until the physical test is done")
        rec["updated_at"] = _now()
        if not state_io.atomic_write_json(self._path(rec["id"]), rec):
            raise EngError("could not write the experiment record")
        return rec

    def create(self, title: str, kind: str, objective: str = "", model: str = "", inputs: Optional[dict] = None,
               outputs: Optional[dict] = None, assumptions: Optional[List[str]] = None, units: Optional[dict] = None,
               validation_status: str = "simulation tested", hypothesis: str = "", uncertainty: Optional[dict] = None,
               evidence: str = "", tags: Optional[List[str]] = None, parent: Optional[str] = None) -> dict:
        if not str(title).strip():
            raise EngError("an experiment needs a title")
        eid = f"EXP-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
        rec = {"schema": "prometheus.experiment/1", "id": eid, "title": str(title).strip()[:200], "kind": kind,
               "objective": objective, "hypothesis": hypothesis, "model": model, "inputs": inputs or {}, "units": units or {},
               "assumptions": assumptions or [], "outputs": outputs or {}, "validation_status": validation_status,
               "uncertainty": uncertainty or {}, "evidence": evidence, "tags": tags or [], "parent": parent,
               "data_files": [], "notes": [], "created_at": _now(), "software": _software(),
               "input_hash": input_hash(model, inputs or {})}
        return self.save(rec)

    def get(self, eid: str) -> dict:
        p = self._path(eid)
        if not os.path.exists(p):
            raise EngError(f"no experiment {eid}")
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def list(self) -> List[dict]:
        out = []
        for name in sorted(os.listdir(self.root), reverse=True):
            if name.startswith("EXP-") and name.endswith(".json"):
                try:
                    with open(os.path.join(self.root, name), encoding="utf-8") as f:
                        r = json.load(f)
                    out.append({k: r.get(k) for k in ("id", "title", "kind", "model", "validation_status", "created_at")})
                except (OSError, json.JSONDecodeError):
                    continue
        return out

    def attach_table(self, eid: str, name: str, rows: List[dict]) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name or ""):
            raise EngError("table name: letters, digits, _ and - only")
        if not rows:
            raise EngError("no rows to attach")
        rec = self.get(eid)
        fname = f"{eid}_{name}.csv"
        cols = list(dict.fromkeys(k for r in rows for k in r))
        buf = io.StringIO()
        w = csv.DictWriter(buf, cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
        import state_io
        state_io.atomic_write_text(os.path.join(self.root, fname), buf.getvalue())
        if fname not in rec["data_files"]:
            rec["data_files"].append(fname)
        self.save(rec)
        return fname

    def add_note(self, eid: str, text: str) -> dict:
        rec = self.get(eid)
        rec["notes"].append({"at": _now(), "text": str(text)[:2000]})
        return self.save(rec)

    def set_status(self, eid: str, status: str, evidence: str = "") -> dict:
        rec = self.get(eid)
        rec["validation_status"] = status
        if evidence:
            rec["evidence"] = evidence
        return self.save(rec)

    # --- model runs ---
    def run(self, model: str, params: dict, title: str = "", objective: str = "", validation_status: str = "simulation tested",
            kind: Optional[str] = None, tags: Optional[List[str]] = None, parent: Optional[str] = None) -> dict:
        from . import registry
        out = registry.run(model, **params)
        if out.get("status") != "success":
            raise EngError(out.get("message", "the model failed"))
        k = kind or ("simulation" if out.get("category") in ("aerospace", "control", "arm") and "series" in out else "calculation")
        rec = self.create(title or f"{model} run", k, objective, model, params, outputs=out.get("results", {}),
                          assumptions=out.get("assumptions", []), validation_status=validation_status, tags=tags, parent=parent)
        if out.get("series"):
            rec["series"] = out["series"]
            self.save(rec)
        return rec

    def rerun(self, eid: str, rel_tol: float = 1e-9) -> dict:
        from . import registry
        rec = self.get(eid)
        if not rec.get("model"):
            raise EngError("this record has no model to re-run (manual or hardware data)")
        out = registry.run(rec["model"], **rec["inputs"])
        if out.get("status") != "success":
            return {"reproduced": False, "message": out.get("message")}
        diff = _max_rel_diff(rec["outputs"], out.get("results", {}))
        return {"reproduced": diff <= rel_tol, "max_relative_difference": diff, "stored_model_version": rec["software"].get("eng_model_version"),
                "current_model_version": MODEL_VERSION, "input_hash_matches": input_hash(rec["model"], rec["inputs"]) == rec["input_hash"]}


def _max_rel_diff(a: Any, b: Any) -> float:
    if isinstance(a, dict) and isinstance(b, dict):
        keys = set(a) | set(b)
        return max((_max_rel_diff(a.get(k), b.get(k)) for k in keys), default=0.0)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return math.inf
        return max((_max_rel_diff(x, y) for x, y in zip(a, b)), default=0.0)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if a == b:
            return 0.0
        return abs(a - b) / max(abs(a), abs(b), 1e-300)
    return 0.0 if a == b else math.inf


class DataLogger:
    """Timestamped rows for a hardware or bench experiment, with the context needed to trust them later."""

    def __init__(self, configuration: dict, calibration: Optional[dict] = None, environment: Optional[dict] = None, clock=time.monotonic):
        self.meta = {"configuration": configuration, "calibration": calibration or {}, "environment": environment or {},
                     "started": _now()}
        self.clock = clock
        self.t0 = clock()
        self.rows: List[dict] = []

    def log(self, **values) -> dict:
        for k, v in values.items():
            if isinstance(v, float) and not math.isfinite(v):
                raise EngError(f"'{k}' is not finite")
        row = {"t_s": round(self.clock() - self.t0, 6), "wall_time": _now(), **values}
        self.rows.append(row)
        return row

    def to_csv(self) -> str:
        cols = list(dict.fromkeys(k for r in self.rows for k in r))
        buf = io.StringIO()
        w = csv.DictWriter(buf, cols)
        w.writeheader()
        for r in self.rows:
            w.writerow(r)
        return buf.getvalue()

    def to_json(self) -> str:
        return json.dumps({"meta": self.meta, "rows": self.rows}, indent=2)

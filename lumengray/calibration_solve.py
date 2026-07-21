"""Phase-2 solver: turn measured calibration numbers into printer corrections.

Feed it the ``answer_key`` (nominal design values, from the export manifest) plus the
filled-in ``measurement.csv`` rows, and it fits:

  * XY pixel pitch (per axis)  -- from the scale bars / squares. measured = s*nominal + b
    over several sizes; the slope s is the scale error, so the TRUE pitch = assumed*s.
    The intercept b is the fixed edge bloom (2*bloom_radius at white).
  * gray -> lateral bloom       -- from the gray x feature matrix. A positive pillar prints
    at nominal + 2*bloom(g); a negative hole at nominal - 2*bloom(g). Both give bloom(g).
  * cure threshold g_min        -- the lowest gray whose features actually formed.
  * resolution limit            -- the finest grating pitch marked resolved.

Pure numpy; no I/O. The result is the calibration profile Phase 3 applies to real prints.
"""

from __future__ import annotations

import csv
import io

import numpy as np


def parse_measurements(text: str) -> list[dict]:
    """Parse a filled measurement.csv into row dicts (blank ``measured_um`` -> None)."""
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        r["measured_um"] = _num(r.get("measured_um"))
        r["nominal_um"] = _num(r.get("nominal_um"))
        r["design_gray"] = _int(r.get("design_gray"))
        rows.append(r)
    return rows


def solve(answer_key: dict, rows: list[dict]) -> dict:
    pitch = answer_key.get("pitch_um") or [35.0, 35.0]
    result: dict = {"ok": True, "warnings": []}
    result["scale"] = _solve_scale(rows, pitch, result["warnings"])
    scales = [v["scale"] for v in result["scale"].values()]
    s_avg = float(np.mean(scales)) if scales else 1.0
    result["bloom"] = _solve_bloom(rows, s_avg, result["warnings"])
    result["threshold"] = _solve_threshold(rows)
    result["resolution"] = _solve_resolution(rows)
    return result


# ── scale / pitch ────────────────────────────────────────

def _solve_scale(rows, pitch, warnings) -> dict:
    """Per-axis linear fit measured = s*nominal + b over the scale bars + squares."""
    out = {}
    for ai, axis in enumerate(("X", "Y")):
        pts = [(r["nominal_um"], r["measured_um"]) for r in rows
               if r.get("zone") in ("square", "comb", "block", "ruler")
               and r.get("axis", "").upper().startswith(axis)
               and r["nominal_um"] and r["measured_um"]]
        if len(pts) < 2:
            warnings.append(f"scale {axis}: need >=2 measured scale features (have {len(pts)})")
            continue
        nom = np.array([p[0] for p in pts], float)
        mea = np.array([p[1] for p in pts], float)
        s, b = np.polyfit(nom, mea, 1)
        resid = mea - (s * nom + b)
        ss_tot = float(((mea - mea.mean()) ** 2).sum()) or 1.0
        r2 = 1.0 - float((resid ** 2).sum()) / ss_tot
        assumed = float(pitch[ai])
        out[axis] = {
            "scale": round(float(s), 5),
            "offset_um": round(float(b), 2),
            "true_pitch_um": round(assumed * float(s), 4),
            "assumed_pitch_um": assumed,
            "r2": round(r2, 4),
            "n": len(pts),
        }
    return out


# ── gray -> lateral bloom ────────────────────────────────

def _solve_bloom(rows, scale, warnings) -> dict:
    """bloom(g) in um from pillars (grow) and holes (shrink). The printed size carries
    the scale error too (printed = scale*nominal +/- 2*bloom), so bloom is measured
    against the SCALE-corrected nominal, isolating the dose-driven lateral spread."""
    per_g: dict = {}
    for r in rows:
        zone, g, nom, mea = r.get("zone"), r.get("design_gray"), r["nominal_um"], r["measured_um"]
        if g is None or nom is None or mea is None or mea <= 0:
            continue  # measured<=0 = vanished pillar / fully-closed hole: a threshold
            #           effect, not a clean bloom reading — handled by the threshold solve.
        base = scale * nom
        if zone == "matrix_pos":
            per_g.setdefault(g, []).append((mea - base) / 2.0)     # printed = scale*nominal + 2*bloom
        elif zone == "matrix_neg":
            per_g.setdefault(g, []).append((base - mea) / 2.0)     # printed = scale*nominal - 2*bloom
    if not per_g:
        warnings.append("bloom: no matrix_pos/matrix_neg measurements found")
        return {"curve": [], "note": "no data"}
    curve = [{"gray": g, "bloom_um": round(float(np.mean(v)), 2), "n": len(v)}
             for g, v in sorted(per_g.items())]
    return {"curve": curve}


# ── cure threshold ───────────────────────────────────────

def _solve_threshold(rows) -> dict:
    """Lowest gray whose pillars actually formed (measured > 0)."""
    formed = [r["design_gray"] for r in rows
              if r.get("zone") == "matrix_pos" and r["design_gray"] is not None
              and r["measured_um"] and r["measured_um"] > 0]
    vanished = sorted({r["design_gray"] for r in rows
                       if r.get("zone") == "matrix_pos" and r["design_gray"] is not None
                       and (r["measured_um"] is None or r["measured_um"] == 0)}
                      - set(formed))
    return {"g_min": (min(formed) if formed else None), "vanished_grays": vanished}


# ── resolution ───────────────────────────────────────────

def _solve_resolution(rows) -> dict:
    """Finest grating pitch (um) marked resolved (measured>0 or notes contains 'y')."""
    resolved = [r["nominal_um"] for r in rows
                if r.get("zone") == "grating" and r["nominal_um"]
                and ((r["measured_um"] and r["measured_um"] > 0) or "y" in r.get("notes", "").lower())]
    return {"finest_resolved_um": (min(resolved) if resolved else None)}


# ── helpers ──────────────────────────────────────────────

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None

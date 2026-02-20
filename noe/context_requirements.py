"""
context_requirements.py

Defines the required context fields for each Noe operator.
Used for static validation and pre-evaluation checks.
"""

# Mapping from operator to required context fields (dot-paths).
CONTEXT_REQUIREMENTS = {
    # Spatial (binary ops rely on entities + spatial)
    "nel": ["spatial.thresholds.near", "entities"],
    "tel": ["spatial.thresholds.far", "entities"],
    "xel": ["spatial.orientation.target", "spatial.orientation.tolerance", "entities"],
    "en":  ["entities"],  # because current code expects region radius on RHS entity
    "tra": ["entities"],  # because current code uses vel + pos
    "fra": ["entities"],

    # Demonstratives (fallback resolution uses entities + spatial thresholds)
    "dia": ["demonstratives", "entities", "spatial.thresholds.near"],
    "doq": ["demonstratives", "entities", "spatial.thresholds.far"],

    # Epistemic
    "shi": ["modal.knowledge"],
    "vek": ["modal"],  # (v1.0 code accepts knowledge as fallback)
    "sha": ["modal.certainty"],

    # Sensory (reserved)
    "vis": ["sensors.vision"],
    "hau": ["sensors.audio"],
    "per": ["sensors.perception"],

    # Temporal
    "nau": ["temporal.now"],
    "ret": ["temporal.now"],
    "tri": ["temporal.now"],
    "qer": ["temporal.now"],

    # Action / delivery
    "vus": ["delivery"],
    "vel": ["delivery"],
    "men": ["audit", "spatial"],
    "mek": ["spatial"],
    "kra": [],
    "noq": ["delivery"],

    # Normative
    "tor": ["axioms.value_system"],
}

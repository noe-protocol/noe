# Grounding Layer Walkthrough

> **Key insight:** Noe doesn't do grounding. YOU do. Noe validates what you've grounded.

---

## The Flow

```
Sensor Value → Your Grounding Logic → Epistemic Set → Noe Evaluation
```

---

## Step-by-Step Example

### 1. Sensor Reading Arrives

```python
lidar_reading = {
    "min_distance_m": 0.8,
    "confidence": 0.75,      # Noisy conditions
    "timestamp_us": 1768792000000000
}
```

### 2. Your Grounding Decision

```python
# YOUR thresholds (not Noe's)
KNOWLEDGE_THRESHOLD = 0.90
BELIEF_THRESHOLD = 0.40

# Derive predicate value
path_clear = lidar_reading["min_distance_m"] > 0.5  # True

# Decide epistemic status
if lidar_reading["confidence"] >= KNOWLEDGE_THRESHOLD:
    # High confidence → Knowledge
    context["modal"]["knowledge"]["@path_clear"] = path_clear
elif lidar_reading["confidence"] >= BELIEF_THRESHOLD:
    # Medium confidence → Belief only
    context["modal"]["belief"]["@path_clear"] = path_clear
else:
    # Low confidence → Neither (absent from both)
    pass
```

### 3. Context State

With confidence = 0.75:

```python
context = {
    "literals": {
        "@path_clear": {"value": True, "timestamp_us": 1768792000000000}
    },
    "modal": {
        "knowledge": {},                    # Empty! (0.75 < 0.90)
        "belief": {"@path_clear": True},   # Present (0.75 >= 0.40)
        "certainty": {}
    }
}
```

### 4. Noe Evaluation

```python
chain = "shi @path_clear khi sek mek @navigate sek nek"
result = run_noe_logic(chain, context, mode="strict")
```

**What happens:**
- `shi @path_clear` checks `modal.knowledge["@path_clear"]`
- Not found → returns `undefined`
- `undefined khi ...` → whole chain returns `undefined`
- `domain: undefined` → **non-execution**

### 5. Result

```python
result = {
    "domain": "undefined",
    "value": "undefined"
}
# Action NOT emitted. Robot halts safely.
```

---

## Three Outcomes

| Confidence | Epistemic Set | shi Result | Chain Result | Action |
|------------|---------------|------------|--------------|--------|
| ≥ 0.90 | knowledge | `true` | `list[action]` | ✅ Executed |
| 0.40 - 0.89 | belief only | `undefined` | `undefined` | ❌ Blocked |
| < 0.40 | neither | `undefined` | `undefined` | ❌ Blocked |

---

## Why This Matters

**You define the thresholds.** Noe enforces the contract.

- Sensor manufacturer claims 95% accuracy? Set threshold at 0.90.
- Safety-critical domain? Set threshold at 0.99.
- Non-critical advisory? Use `vek` (belief operator) instead.

**The provenance record shows:**
- What threshold was applied
- Whether predicate was in knowledge/belief/neither
- Exactly why the action was blocked

---

## Common Pattern

```python
def ground_sensor(reading: SensorReading, threshold: float = 0.90) -> dict:
    """Convert sensor reading to grounded predicate."""
    return {
        "value": reading.value,
        "timestamp_us": reading.timestamp_us,
        "in_knowledge": reading.confidence >= threshold,
        "in_belief": reading.confidence >= 0.40
    }
```

**Noe doesn't care WHERE the thresholds come from.** It only checks membership in the epistemic sets you provide.

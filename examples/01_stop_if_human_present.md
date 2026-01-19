# Canonical Example 1: Stop if Human Present

## Intent

If we **know** a human is in the danger zone, issue a stop command.  
If we don't know (missing/ambiguous) or know they are **not** there, do nothing.

## Noe Chain

```
shi @human_present khi sek mek @stop nek
```

**Breakdown**:
- `shi @human_present` – Epistemic: "I **know** that a human is present"
- `khi` – Guard: only proceed if the condition is true
- `sek` – Separator (structural)
- `mek @stop` – Action: issue a stop command to the controller
- `nek` – Terminate chain

## Tick 1: No Human in Zone (No Action)

### Context (Tick 1)

```json
{
  "root": {
    "temporal": { "now_ms": 1000 },
    "safety": {
      "human_stop_distance_m": 1.0
    }
  },
  "domain": {
    "entities": {
      "@robot": { "kind": "mobile_base" },
      "@human_zone": { "kind": "region", "frame": "base_link" }
    },
    "literals": {
      "@human_present": { "type": "boolean" }
    }
  },
  "local": {
    "timestamp_ms": 1000,
    "sensors": {
      "vision": {
        "human_detected": false,
        "distance_m": 2.5
      }
    },
    "literals": {
      "@human_present": false
    }
  },
  "delivery": { "status": {} },
  "audit": { "log": [] }
}
```

### Evaluation (Tick 1)

1. `@human_present` is present and `false`
2. `shi @human_present` → `false` (we **know** the proposition is false)
3. `false khi ...` → guard fails → whole chain → `undefined`
4. `undefined` ⇒ **non-execution**

### Result (Tick 1)

```json
{
  "domain": "undefined",
  "value": "undefined"
}
```

**No action emitted; no audit entry created.**

---

## Tick 2: Human Enters Zone (Stop Executes)

At tick 2, vision updates:
- `human_detected = true`
- `distance_m = 0.7` (< 1.0 m threshold)
- We mark `@human_present = true` in `C_local.literals`

### Context (Tick 2)

```json
{
  "root": {
    "temporal": { "now_ms": 1100 },
    "safety": {
      "human_stop_distance_m": 1.0
    }
  },
  "domain": {
    "entities": {
      "@robot": { "kind": "mobile_base" },
      "@human_zone": { "kind": "region", "frame": "base_link" }
    },
    "literals": {
      "@human_present": { "type": "boolean" }
    }
  },
  "local": {
    "timestamp_ms": 1100,
    "sensors": {
      "vision": {
        "human_detected": true,
        "distance_m": 0.7
      }
    },
    "literals": {
      "@human_present": true
    }
  },
  "delivery": { "status": {} },
  "audit": { "log": [] }
}
```

### Evaluation (Tick 2)

1. `shi @human_present` → `true` (known true)
2. Guard succeeds
3. `mek @stop` executes as an action

### Result (Tick 2)

```json
{
  "domain": "action",
  "type": "action",
  "verb": "mek",
  "target": "@stop"
}
```

**In a real integration**, that action goes to ROS2/PX4 as a "stop" velocity or trajectory cancel.

---

## Key Insights

1. **Epistemic Gating**: The `shi` operator ensures we only act when we **know** the condition is true
2. **Bochvar Semantics**: Unknown/missing data → `undefined` → non-execution (safe default)
3. **Deterministic**: Same context + same chain = same result (replayable)
4. **Safety-First**: Missing sensor data doesn't accidentally trigger stop; only positive knowledge does

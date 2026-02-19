# Canonical Example 1: Stop if Human Present

## Intent

This example demonstrates a **deterministic policy gate**: the controller only receives a stop action when `@human_present` is grounded in `C_safe.modal.knowledge` as `true` under freshness/threshold rules. If the proposition is absent, ambiguous, or explicitly `false`, strict mode collapses to non-execution.

- **Non-Execution Semantics**: 
Guard-fail is treated as a no-op; explicit refusal certificates are emitted when strict-mode encounters an epistemic mismatch or `undefined` on a guard protecting a `mek` action path (see Auditor Demo).

- **Safety Posture**: 
This is a pedagogical "positive authorization" example; in safety-critical deployments, you typically configure the projection or policy to trigger a fail-safe stop on uncertainty.

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
> [!NOTE]
> We show `C_total` below for traceability. Replay/evaluation uses the projected `C_safe` layer.  
> **Projection Assumption**: An upstream perception module computes a boolean literal; projection admits it into `C_safe.modal.knowledge` only if freshness (`max_staleness_us`) and confidence thresholds pass; otherwise the key is absent/ungrounded.  
> *(Not shown: After projection, `C_safe.modal.knowledge['@human_present'] = false` in Tick 1 and `true` in Tick 2).*

```json
{
  "root": {
    "temporal": { "now_us": 1000000 },
    "safety": {
      "human_stop_distance_mm": 1000
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
    "timestamp_us": 1000000,
    "sensors": {
      "vision": {
        "human_detected": false,
        "distance_mm": 2500
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

1. `@human_present` is grounded as `false` (no human detected).
2. `shi @human_present` → `false` (lookup returns the grounded value).
3. `false khi ...` → guard fails → no action emitted (no-op).
4. `undefined` ⇒ **non-execution sentinel** (The demo evaluator returns `undefined` to make "no execution" visibly distinct from an explicit empty action list in logs/certificates. Adapters MUST map `undefined` to "no action").

### Result (Tick 1)

```json
{
  "domain": "undefined",
  "value": "undefined"
}
```

**No action emitted; no audit entry created.**

<br />

## Tick 2: Human Enters Zone (Stop Executes)

At tick 2, vision updates:
- `human_detected = true`
- `distance_mm = 700` (< 1000 mm threshold)
- We mark `@human_present = true` in `C_local.literals`

### Context (Tick 2)

```json
{
  "root": {
    "temporal": { "now_us": 1100000 },
    "safety": {
      "human_stop_distance_mm": 1000
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
    "timestamp_us": 1100000,
    "sensors": {
      "vision": {
        "human_detected": true,
        "distance_mm": 700
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
  "domain": "list",
  "value": [
    { "type": "action", "verb": "mek", "target": "@stop" }
  ]
}
```

> [!TIP]
> When wrapped in a **Provenance Certificate** (NIP-010) for the Auditor Demo, the certificate will include `context_hashes.safe` and an `outcome.action_hash` computed from this single action list.

**In a real integration**, that action goes to ROS2/PX4 as a "stop" velocity or trajectory cancel.

<br />

## Key Insights

1. **Epistemic Gating**: The `shi` operator ensures we only act when we **know** the condition is true.
2. **Strict-mode guard rule**: Actions emit only when the guard is `true`; `false`, `undefined`, or `error` all yield non-execution (NIP-015).
3. **Pure Interpreter**: Evaluation is stateless and deterministic; the result is a proposal for the controller.
4. **Safety-First**: Missing sensor data doesn't accidentally trigger stop; only positive knowledge does.

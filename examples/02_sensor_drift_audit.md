# Canonical Example 2: Sensor-Drift Audit Request

## Intent

This demonstrates **multi-sink emission**: a single epistemic trigger triggers both delivery and audit actions.

- **Deterministic Ordering**: 
In the reference demo runner, chains are evaluated in file order and action lists are concatenated in that order.

- **Non-Execution Semantics**: 
Guard-fail is treated as a no-op.

- **Safety Posture**: 
This example uses a "positive authorization" trigger for audit/delivery. In production, you typically configure the projection or policy to ensure epistemic gaps are themselves auditable events.

<br />

## Noe Chains

Two chains evaluated in the same tick:

```
shi @sensor_drift khi sek vus @safety_channel sek nek
shi @sensor_drift khi sek men @sensor_drift_event sek nek
```

**Breakdown**:
- `shi @sensor_drift` – "I **know** sensors are in a drift condition"
- `vus @safety_channel` – Delivery operator: request event routing via delivery route
- `men @sensor_drift_event` – Audit operator: request append to provenance record
- Both chains only fire when drift is epistemically known true; otherwise `undefined` ⇒ no-op

<br />

## Tick A: Sensors Agree (No Audit, No Delivery)

Assume two distance sensors:
- `lidar_distance_mm = 1200`
- `ultra_distance_mm = 1250`
- Drift threshold = 200 mm → **sensors are consistent**

We compute `@sensor_drift = false`.

### Context (Tick A, Before Evaluation)
> [!NOTE]
> We show `C_total` below for traceability. Replay/evaluation uses the projected `C_safe` layer.  
> **Projection Assumption**: Upstream sensor fusion computes the `@sensor_drift` literal; projection admits it into `C_safe.modal.knowledge` only if both lidar/ultrasonic readings are fresh (`max_staleness_us`) and the drift threshold is exceeded.  
> *(Not shown: After projection, `@sensor_drift` is `false` in Tick A and `true` in Tick B. The Noe kernel evaluates against this grounded fact; the raw sensor JSON is retained purely for audit traceability).*

```json
{
  "root": {
    "temporal": { "now_us": 2000000 },
    "safety": {
      "sensor_drift_threshold_mm": 200
    }
  },
  "domain": {
    "entities": {
      "@robot": { "kind": "mobile_base" }
    },
    "literals": {
      "@sensor_drift": { "type": "boolean" }
    }
  },
  "local": {
    "timestamp_us": 2000000,
    "sensors": {
      "lidar": { "distance_mm": 1200, "sample_us": 1998000 },
      "ultra": { "distance_mm": 1250, "sample_us": 1999000 }
    },
    "literals": {
      "@sensor_drift": false
    }
  },
  "delivery": {
    "status": {},
    "routes": {
      "@safety_channel": {
        "kind": "topic",
        "endpoint": "safety/audit"
      }
    }
  },
  "audit": {
    "log": []
  }
}
```

### Evaluation (Tick A)

1. `shi @sensor_drift` → `false`
2. Both chains → `false` guard → `undefined`
3. `undefined` ⇒ **no delivery, no audit entry**

### Resulting Actions (Tick A)

```json
{
  "domain": "undefined",
  "value": "undefined"
}
```

**Context after Tick A**: Unchanged (no new delivery status, no audit log entries)

<br />

## Tick B: Sensors Drift (Audit + Delivery Fire)

Now sensors diverge beyond threshold:
- `lidar_distance_mm = 400`
- `ultra_distance_mm = 900`
- Difference = 500 > 200 → **drift condition detected**

We set `@sensor_drift = true` in `C_local.literals`.

### Context (Tick B, Before Evaluation)

```json
{
  "root": {
    "temporal": { "now_us": 2100000 },
    "safety": {
      "sensor_drift_threshold_mm": 200
    }
  },
  "domain": {
    "entities": {
      "@robot": { "kind": "mobile_base" }
    },
    "literals": {
      "@sensor_drift": { "type": "boolean" }
    }
  },
  "local": {
    "timestamp_us": 2100000,
    "sensors": {
      "lidar": { "distance_mm": 400, "sample_us": 2098000 },
      "ultra": { "distance_mm": 900, "sample_us": 2099000 }
    },
    "literals": {
      "@sensor_drift": true
    }
  },
  "delivery": {
    "status": {},
    "routes": {
      "@safety_channel": {
        "kind": "topic",
        "endpoint": "safety/audit"
      }
    }
  },
  "audit": {
    "log": []
  }
}
```

### Evaluation (Tick B)

1. `shi @sensor_drift` → `true` (drift known true)
2. **First chain**: `vus @safety_channel` produces delivery action
3. **Second chain**: `men @sensor_drift_event` produces audit action

### Resulting Actions (Tick B)

```json
{
  "domain": "list",
  "value": [
    {
      "type": "action",
      "kind": "delivery",
      "verb": "vus",
      "route": "@safety_channel",
      "payload": { "event": "sensor_drift", "lidar_distance_mm": 400, "ultra_distance_mm": 900 }
    },
    {
      "type": "action",
      "kind": "audit",
      "verb": "men",
      "event": "@sensor_drift_event"
    }
  ]
}
```

> [!TIP]
> Certificate output (NIP-010) adds top-level `context_hashes` and an `outcome.action_hash` encompassing this ordered list of actions.

### Integration

In the Noe runtime + Circular / ROS integration:
- **Route** the `vus` action out via your delivery adapter (Kafka topic, ROS topic, HTTP, etc.)
- **Apply** the `men` action to update `C.audit.log`

### Context (Tick B, After Applying Actions - Conceptual)

> [!NOTE]
> The Noe interpreter is **pure**. These context updates are applied **out-of-band** by system-level adapters *after* evaluation.

```json
{
  "root": {
    "temporal": { "now_us": 2100000 },
    "safety": {
      "sensor_drift_threshold_mm": 200
    }
  },
  "domain": {
    "entities": {
      "@robot": { "kind": "mobile_base" }
    },
    "literals": {
      "@sensor_drift": { "type": "boolean" }
    }
  },
  "local": {
    "timestamp_us": 2100000,
    "sensors": {
      "lidar": { "distance_mm": 400, "sample_us": 2098000 },
      "ultra": { "distance_mm": 900, "sample_us": 2099000 }
    },
    "literals": {
      "@sensor_drift": true
    }
  },
  "delivery": {
    "status": {
      "last_sent": {
        "route": "@safety_channel",
        "event": "sensor_drift",
        "time_us": 2100000
      }
    },
    "routes": {
      "@safety_channel": {
        "kind": "topic",
        "endpoint": "safety/audit"
      }
    }
  },
  "audit": {
    "log": [
      {
        "event": "@sensor_drift_event",
        "time_us": 2100000,
        "details": {
          "lidar_distance_mm": 400,
          "ultra_distance_mm": 900
        }
      }
    ]
  }
}
```

<br />

## Key Insights

1. **Multi-Channel Actions**: Single epistemic condition triggers both delivery and audit.
2. **Delivery Trace**: `C.delivery.status` records what was sent and when (updated by delivery adapter).
3. **Provenance**: `C.audit.log` provides replayable audit trail (updated by audit adapter).
4. **Pure Evaluation**: The interpreter is a pure function over `C_safe`; state mutation is decoupled.
5. **Deterministic**: Same sensor readings + same chains = same delivery + audit actions.

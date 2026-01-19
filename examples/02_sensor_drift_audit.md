# Canonical Example 2: Sensor-Drift Audit Request

## Intent

If we **know** the distance sensors disagree beyond a safe threshold:
1. Emit a **delivery event** to a safety/audit channel
2. Write a **provenance record** into `C.audit.log`

This demonstrates delivery + audit operators working together.

## Noe Chains

Two chains evaluated in the same tick:

```
shi @sensor_drift khi sek vus @safety_channel nek
shi @sensor_drift khi sek men @sensor_drift_event nek
```

**Breakdown**:
- `shi @sensor_drift` – "I **know** sensors are in a drift condition"
- `vus @safety_channel` – Delivery operator: send event via delivery channel
- `men @sensor_drift_event` – Audit/provenance operator: log this event
- Both chains only fire when drift is epistemically known true; otherwise `undefined` ⇒ no-op

---

## Tick A: Sensors Agree (No Audit, No Delivery)

Assume two distance sensors:
- `lidar_distance_m = 1.2`
- `ultra_distance_m = 1.25`
- Drift threshold = 0.2 m → **sensors are consistent**

We compute `@sensor_drift = false`.

### Context (Tick A, Before Evaluation)

```json
{
  "root": {
    "temporal": { "now_ms": 2000 },
    "safety": {
      "sensor_drift_threshold_m": 0.2
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
    "timestamp_ms": 2000,
    "sensors": {
      "lidar": { "distance_m": 1.20 },
      "ultra": { "distance_m": 1.25 }
    },
    "literals": {
      "@sensor_drift": false
    }
  },
  "delivery": {
    "status": {},
    "channels": {
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
[
  { "domain": "undefined", "value": "undefined" },
  { "domain": "undefined", "value": "undefined" }
]
```

**Context after Tick A**: Unchanged (no new delivery status, no audit log entries)

---

## Tick B: Sensors Drift (Audit + Delivery Fire)

Now sensors diverge beyond threshold:
- `lidar_distance_m = 0.4`
- `ultra_distance_m = 0.9`
- Difference = 0.5 > 0.2 → **drift condition detected**

We set `@sensor_drift = true` in `C_local.literals`.

### Context (Tick B, Before Evaluation)

```json
{
  "root": {
    "temporal": { "now_ms": 2100 },
    "safety": {
      "sensor_drift_threshold_m": 0.2
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
    "timestamp_ms": 2100,
    "sensors": {
      "lidar": { "distance_m": 0.40 },
      "ultra": { "distance_m": 0.90 }
    },
    "literals": {
      "@sensor_drift": true
    }
  },
  "delivery": {
    "status": {},
    "channels": {
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
[
  {
    "domain": "action",
    "type": "action",
    "verb": "vus",
    "channel": "@safety_channel",
    "payload": {
      "event": "sensor_drift",
      "lidar_distance_m": 0.40,
      "ultra_distance_m": 0.90
    }
  },
  {
    "domain": "action",
    "type": "action",
    "verb": "men",
    "event": "@sensor_drift_event"
  }
]
```

### Integration

In the Noe runtime + Circular / ROS integration:
- **Route** the `vus` action out via your delivery adapter (Kafka topic, ROS topic, HTTP, etc.)
- **Apply** the `men` action to update `C.audit.log`

### Context (Tick B, After Applying Actions)

```json
{
  "root": {
    "temporal": { "now_ms": 2100 },
    "safety": {
      "sensor_drift_threshold_m": 0.2
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
    "timestamp_ms": 2100,
    "sensors": {
      "lidar": { "distance_m": 0.40 },
      "ultra": { "distance_m": 0.90 }
    },
    "literals": {
      "@sensor_drift": true
    }
  },
  "delivery": {
    "status": {
      "last_sent": {
        "channel": "@safety_channel",
        "event": "sensor_drift",
        "time_ms": 2100
      }
    },
    "channels": {
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
        "time_ms": 2100,
        "details": {
          "lidar_distance_m": 0.40,
          "ultra_distance_m": 0.90
        }
      }
    ]
  }
}
```

---

## Key Insights

1. **Multi-Channel Actions**: Single epistemic condition triggers both delivery and audit
2. **Delivery Trace**: `C.delivery.status` records what was sent and when
3. **Provenance**: `C.audit.log` provides replayable audit trail
4. **Deterministic**: Same sensor readings + same chains = same delivery + audit actions
5. **Safety-First**: Only acts when drift is **known** true, not on missing/ambiguous data

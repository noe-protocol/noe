# ROS 2 Integration Pattern

> **Status:** Conceptual pseudocode. No ROS 2 dependencies required.

This shows how Noe fits into a typical ROS 2 node as a **safety gate** between sensor data and actuator commands.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     ROS 2 Node                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐     │
│  │ /lidar/scan  │   │ /camera/rgb  │   │ /joint_state │     │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘     │
│         │                  │                  │              │
│         ▼                  ▼                  ▼              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Context Builder                         │    │
│  │   Sensors → Grounding → Epistemic Sets → C_safe     │    │
│  └─────────────────────────┬───────────────────────────┘    │
│                            │                                 │
│                            ▼                                 │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Noe Safety Kernel                       │    │
│  │   run_noe_logic(chain, C_safe, mode="strict")       │    │
│  └─────────────────────────┬───────────────────────────┘    │
│                            │                                 │
│              ┌─────────────┴─────────────┐                  │
│              ▼                           ▼                  │
│     domain == "list"              domain != "list"          │
│     (action allowed)              (non-execution)           │
│              │                           │                  │
│              ▼                           ▼                  │
│  ┌──────────────────┐         ┌──────────────────┐         │
│  │ /cmd_vel publish │         │ Safe halt + log  │         │
│  └──────────────────┘         └──────────────────┘         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> **Failure Walkthrough (Designed Refusal)**
> 
> LiDAR confidence drops to 0.75 → grounding layer rejects `@path_clear` from knowledge set (threshold: 0.90) → `shi @path_clear` resolves to `undefined` → Noe emits non-execution (`domain: undefined`) + provenance hash → deliberation layer triggers safe halt → reflex controller continues obstacle avoidance → audit log records: "Epistemic gap at T=1234567890, hash=abc123..."
> 
> **This refusal is designed, not accidental.** The provenance record proves exactly why the action was blocked and what context was trusted at that moment.

---

## Pseudocode Implementation

```python
#!/usr/bin/env python3
"""
ROS 2 Noe Guard Node (Conceptual Pseudocode)

This is NOT runnable code - it shows the integration pattern.
"""

import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

# --- Simulated ROS 2 imports (pseudocode) ---
# from rclpy.node import Node
# from sensor_msgs.msg import LaserScan
# from geometry_msgs.msg import Twist

# --- Noe import (real) ---
from noe.noe_parser import run_noe_logic


@dataclass
class SensorReading:
    """Timestamped sensor value with confidence."""
    value: Any
    timestamp_us: int
    confidence: float = 1.0


class NoeGuardNode:  # (Node):  # Would inherit from rclpy.node.Node
    """
    ROS 2 node that uses Noe as a safety gate.
    
    Pattern:
    1. Collect sensor data from ROS topics
    2. Build grounded context (C_safe)
    3. Evaluate Noe chain
    4. Publish action OR safe halt
    """
    
    def __init__(self):
        # super().__init__('noe_guard_node')
        
        # Sensor state (updated by callbacks)
        self.sensors: Dict[str, SensorReading] = {}
        
        # Safety chain (could be loaded from param server)
        self.safety_chain = "shi @path_clear an shi @battery_ok khi sek mek @navigate sek nek"
        
        # Thresholds for epistemic grounding
        self.KNOWLEDGE_THRESHOLD = 0.90
        self.BELIEF_THRESHOLD = 0.40
        self.MAX_STALENESS_US = 5_000_000  # 5 seconds
        
        # --- Subscribers (pseudocode) ---
        # self.create_subscription(LaserScan, '/lidar/scan', self.lidar_callback, 10)
        # self.create_subscription(BatteryState, '/battery', self.battery_callback, 10)
        
        # --- Publisher (pseudocode) ---
        # self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        
        # --- Timer for decision loop ---
        # self.create_timer(0.1, self.decision_loop)  # 10 Hz
    
    # =========================================
    # STEP 1: Sensor Callbacks → Raw Readings
    # =========================================
    
    def lidar_callback(self, msg):
        """Process LiDAR scan, extract path_clear predicate."""
        # Your perception logic here
        min_distance = min(msg.ranges)
        path_clear = min_distance > 0.5  # meters
        confidence = 0.95 if min_distance > 1.0 else 0.70
        
        self.sensors["@path_clear"] = SensorReading(
            value=path_clear,
            timestamp_us=self._now_us(),
            confidence=confidence
        )
    
    def battery_callback(self, msg):
        """Process battery state."""
        battery_ok = msg.percentage > 0.20  # 20% threshold
        
        self.sensors["@battery_ok"] = SensorReading(
            value=battery_ok,
            timestamp_us=self._now_us(),
            confidence=1.0  # Battery sensor is deterministic
        )
    
    # =========================================
    # STEP 2: Build Grounded Context (C_safe)
    # =========================================
    
    def build_context(self) -> Dict[str, Any]:
        """
        Convert sensor readings to Noe context.
        
        This is YOUR grounding layer - Noe doesn't do this.
        """
        now_us = self._now_us()
        
        literals = {}
        knowledge = {}
        belief = {}
        
        for predicate, reading in self.sensors.items():
            # Skip stale readings
            age_us = now_us - reading.timestamp_us
            if age_us > self.MAX_STALENESS_US:
                continue  # Will be absent from C_safe → ERR_LITERAL_MISSING
            
            # Add to literals
            literals[predicate] = {
                "value": reading.value,
                "timestamp_us": reading.timestamp_us
            }
            
            # Epistemic grounding (YOUR policy)
            if reading.confidence >= self.KNOWLEDGE_THRESHOLD:
                knowledge[predicate] = reading.value
            elif reading.confidence >= self.BELIEF_THRESHOLD:
                belief[predicate] = reading.value
            # else: neither knowledge nor belief → shi returns undefined
        
        return {
            "temporal": {"now_us": now_us},
            "literals": literals,
            "modal": {
                "knowledge": knowledge,
                "belief": belief,
                "certainty": {}
            },
            "axioms": {},
            "delivery": {"status": "ready"},
            "audit": {"enabled": True}
        }
    
    # =========================================
    # STEP 3: Noe Evaluation (The Gate)
    # =========================================
    
    def decision_loop(self):
        """
        Main decision loop - runs at 10 Hz.
        
        This is where Noe gates the action.
        """
        # Build current context
        context = self.build_context()
        
        # Evaluate safety chain
        result = run_noe_logic(
            self.safety_chain,
            context,
            mode="strict"  # ALWAYS strict for robotics
        )
        
        # =========================================
        # STEP 4: Action vs Non-Execution
        # =========================================
        
        if result["domain"] == "list":
            # Action ALLOWED - Noe approved
            action = result["value"][0]  # Single action per chain
            self._execute_action(action)
            self._log_provenance(result, context, executed=True)
        
        elif result["domain"] == "undefined":
            # Epistemic gap - not enough knowledge
            self._safe_halt("Epistemic gap: insufficient knowledge")
            self._log_provenance(result, context, executed=False)
        
        elif result["domain"] == "error":
            # Fail-stop - missing literal, stale data, etc.
            error_code = result.get("code", "UNKNOWN")
            self._safe_halt(f"Fail-stop: {error_code}")
            self._log_provenance(result, context, executed=False)
        
        else:  # truth, numeric, question
            # Non-action result
            self._safe_halt(f"Non-action domain: {result['domain']}")
    
    # =========================================
    # Helpers
    # =========================================
    
    def _execute_action(self, action: dict):
        """Publish action to actuator."""
        # twist = Twist()
        # twist.linear.x = 0.5  # Forward
        # self.cmd_vel_pub.publish(twist)
        print(f"ACTION EXECUTED: {action['verb']} {action['target']}")
    
    def _safe_halt(self, reason: str):
        """Stop robot, log reason."""
        # twist = Twist()  # Zero velocity
        # self.cmd_vel_pub.publish(twist)
        print(f"SAFE HALT: {reason}")
    
    def _log_provenance(self, result: dict, context: dict, executed: bool):
        """Log decision for audit trail."""
        # In production: write to append-only log, blockchain, etc.
        print(f"PROVENANCE: executed={executed}, domain={result['domain']}")
    
    def _now_us(self) -> int:
        """Current time in microseconds (int64)."""
        return time.time_ns() // 1_000


# --- Main (pseudocode) ---
# def main():
#     rclpy.init()
#     node = NoeGuardNode()
#     rclpy.spin(node)
#     node.destroy_node()
#     rclpy.shutdown()
```

---

## Key Integration Points

### 1. Sensor → Predicate Grounding (YOUR responsibility)

```python
# LiDAR → @path_clear
min_distance = min(scan.ranges)
path_clear = min_distance > 0.5

# Confidence → Epistemic set
if confidence >= 0.90:
    knowledge["@path_clear"] = True
elif confidence >= 0.40:
    belief["@path_clear"] = True
```

### 2. Noe Evaluation (Deterministic)

```python
result = run_noe_logic(chain, context, mode="strict")
```

### 3. Action Gate (Binary Decision)

```python
if result["domain"] == "list":
    execute(result["value"][0])  # Approved
else:
    halt()  # Undefined, error, or non-action
```

---

## What Noe Adds Over Raw ROS 2

| Without Noe | With Noe |
|-------------|----------|
| `if lidar_ok and battery_ok:` | Deterministic chain + epistemic grounding |
| Scattered safety checks | Single safety kernel |
| No replay capability | Bit-identical replay from provenance |
| "Why did it move?" - grep logs | Hash-verified audit trail |
| Different logic per robot | Same chain across fleet |

---

## Recommended Pattern

```
10 Hz deliberation loop:
├── Build context from latest sensor state
├── Evaluate Noe chain (sub-ms)
├── If action: publish to /cmd_vel
└── Always: log provenance record

1000 Hz reflex loop (NOT Noe):
├── Read IMU/joint states
├── PID/MPC control
└── Emergency stop on hardware fault
```

**Noe is for deliberation (Hz), not reflexes (kHz).**

# Noe Canonical Examples

This directory contains fully worked, realistic examples demonstrating Noe semantics aligned with NIP-005/008/009.

## Examples

### 1. [Stop if Human Present](01_stop_if_human_present.md)

**Demonstrates**: Epistemic-gated action with `shi` operator

**Key Concepts**:
- Epistemic knowledge (`shi`) vs belief (`vek`)
- Guard-based action execution (`khi`)
- Bochvar semantics (undefined → non-execution)
- Safety-first design (only act on positive knowledge)

**Use Case**: Safety-critical human detection in robotics

---

### 2. [Sensor-Drift Audit Request](02_sensor_drift_audit.md)

**Demonstrates**: Delivery + audit operators working together

**Key Concepts**:
- Delivery operator (`vus`) for event routing
- Audit operator (`men`) for provenance logging
- Multi-channel actions from single epistemic condition
- Context evolution across ticks (before/after)

**Use Case**: Sensor validation and audit trail in safety-critical systems

---

## Structure

Each example includes:

1. **Intent**: What the example demonstrates
2. **Noe Chain**: The actual Noe expression
3. **Context (Before)**: Full `C_total` before evaluation
4. **Evaluation**: Step-by-step semantic breakdown
5. **Result**: Actual output from the Noe interpreter
6. **Context (After)**: Updated context (for delivery/audit examples)
7. **Key Insights**: Takeaways and design principles

## Testing

These examples can be converted into conformance tests by:
1. Extracting the chain and context
2. Adding to appropriate `nip011_*.json` file
3. Verifying expected result matches actual output

## Integration

For ROS2/PX4/Circular integration:
- **Actions** (`mek`, `vus`, `men`) → routed to appropriate adapters
- **Context updates** → applied after action execution
- **Audit logs** → persisted for replay/verification

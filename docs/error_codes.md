# NIP-011 Error Code Specification

## Overview
This document defines the canonical error codes used in NIP-011 conformance testing and their semantic distinctions.

## Error Code Hierarchy

### 1. Structural Errors (Context Schema)
**`ERR_CONTEXT_INCOMPLETE`**
- **When**: Required context subsystems are missing or structurally invalid
- **Examples**:
  - Missing `C.temporal.now` or `C.temporal.max_skew_ms`
  - Missing `C.spatial.thresholds.near` when using spatial operators
  - Missing `C.delivery` when using `vus`/`vel`/`noq`
  - Missing `C.audit` when using `men`/`kra`/`noq`
- **Semantics**: This is a **configuration error**, not a runtime semantic failure
- **Recovery**: Fix the context structure before evaluation

**`ERR_BAD_CONTEXT`**
- **When**: Context root is not a valid JSON object (fundamentally malformed)
- **Examples**:
  - Context is `null` → `ERR_BAD_CONTEXT`
  - Context is an array `[]` → `ERR_BAD_CONTEXT`
  - Context is a string `"not an object"` → `ERR_BAD_CONTEXT`
- **Semantics**: Catastrophic structural failure, cannot proceed with evaluation
- **Usage**: Actively used in v1.0 (see `nip011_context.json` tests CTX_001-003)
- **Recovery**: Fix the context to be a valid object before evaluation

### 2. Operator-Specific Errors
**`ERR_LITERAL_MISSING`**
- **When**: A literal referenced in the chain is not present in `C.literals`
- **Result**: Chain evaluates to `undefined` (non-execution)

**`ERR_EP_MISMATCH`**
- **When**: Epistemic operator (`shi`, `vek`, `sha`) used without required modal subsystem
- **Examples**: `shi @fact` when `C.modal.knowledge` is missing

**`ERR_SPATIAL_UNGROUNDABLE`**
- **When**: Spatial operator used without required spatial context
- **Examples**: `nel` without `C.spatial.thresholds.near`

**`ERR_DEMONSTRATIVE_UNRESOLVED`**
- **When**: Demonstrative (`dia`, `doq`) cannot be resolved
- **Examples**: `dia` with no binding and no spatial resolution context

### 3. Parse Errors
**`ERR_PARSE_FAILED`**
- **When**: Chain syntax is invalid or uses unrecognized operators
- **Examples**:
  - Missing termination: `true` (no `nek`)
  - Double termination: `true nek nek`
  - Unrecognized operator: `kra @data` (kra not in v1.0 grammar)

**`ERR_INVALID_LITERAL`**
- **When**: Literal syntax is malformed
- **Examples**: `@bad-char` (hyphen not allowed in literal names)

## Decision Tree

```
Is the context structurally valid?
├─ No → Is it fundamentally broken (not an object)?
│  ├─ Yes → ERR_BAD_CONTEXT
│  └─ No → ERR_CONTEXT_INCOMPLETE
└─ Yes → Can the chain be parsed?
   ├─ No → ERR_PARSE_FAILED or ERR_INVALID_LITERAL
   └─ Yes → Does the chain use operators requiring missing subsystems?
      ├─ Yes → ERR_CONTEXT_INCOMPLETE (structural requirement)
      └─ No → Evaluate chain
         └─ Missing literals/data → undefined (not an error)
```

## Semantic vs. Structural Failures

### Structural Failures (Errors)
- **Missing required subsystems** for operators in use
- **Invalid context schema** (wrong types, missing required fields)
- **Parse failures** (invalid syntax)
- **Result**: Error domain with specific code

### Semantic Failures (Undefined)
- **Missing literal values** (literal exists in table but value is undefined)
- **Demonstrative ambiguity** (multiple entities match)
- **Stale context** (temporal drift exceeds threshold)
- **Result**: `domain: "undefined", value: "undefined"` (non-execution)

## NIP-011 Conformance

A conformant implementation MUST:
1. Return the exact error codes specified for structural failures
2. Distinguish between structural errors and semantic undefined
3. Never execute actions when result is undefined or error
4. Propagate undefined through logical operators (Bochvar logic)

## Version History

- **v1.0**: Initial error code specification
  - `ERR_CONTEXT_INCOMPLETE` introduced for missing subsystems
  - `ERR_BAD_CONTEXT` reserved for catastrophic failures
  - Semantic undefined distinguished from structural errors

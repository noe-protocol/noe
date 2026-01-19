import math
from typing import Any

# Strict bounds for signed 64-bit integer
INT64_MIN = -(2**63)
INT64_MAX = (2**63) - 1

def deep_validate_no_floats(value: Any, path: str = "root") -> None:
    """
    Deep validation: reject any float anywhere in nested structure.
    
    This prevents floats from hiding in arrays, objects, or nested structures.
    
    Args:
        value: Value to validate (can be nested dict/list)
        path: Current path for error messages
        
    Raises:
        ValueError: If any float is found anywhere in structure
        
    Examples:
        >>> deep_validate_no_floats({"a": 1, "b": [2, 3]})  # OK
        >>> deep_validate_no_floats({"a": 1.5})  # doctest: +SKIP
        ValueError: ERR_INVALID_NUMBER: Float found at root.a
        >>> deep_validate_no_floats([1, [2, 3.5]])  # doctest: +SKIP
        ValueError: ERR_INVALID_NUMBER: Float found at root[1]
    """
    if isinstance(value, float):
        # Check for NaN/Inf first for better error messages
        if not math.isfinite(value):
            raise ValueError(f"ERR_INVALID_NUMBER: NaN or Infinity at {path}")
        else:
            raise ValueError(f"ERR_INVALID_NUMBER: Float found at {path} (C_safe must contain only int64)")
    
    elif isinstance(value, dict):
        for key, val in value.items():
            deep_validate_no_floats(val, f"{path}.{key}")
    
    elif isinstance(value, list):
        for idx, val in enumerate(value):
            deep_validate_no_floats(val, f"{path}[{idx}]")
    
    # Other types (int, str, bool, None) are OK


def validate_numeric(value) -> int:
    """
    Validate that a value is already an int64 (not perform quantization).
    
    The decision kernel does NOT quantize floats. Sensor adapters must
    pre-quantize using decimal arithmetic before values enter C_safe pipeline.
    
    Rules:
    1. Floats are REJECTED → ERR_INVALID_NUMBER (quantization is upstream responsibility)
    2. Integers must be in int64 bounds → ERR_INTEGER_RANGE
    3. NaN/Inf are always invalid → ERR_INVALID_NUMBER
    
    Args:
        value: Input value (expected to be int)
        
    Returns:
        Validated int64 value
        
    Raises:
        ValueError: ERR_INVALID_NUMBER or ERR_INTEGER_RANGE
        
    Examples:
        >>> validate_numeric(123456789)
        123456789
        >>> validate_numeric(123.456)  # doctest: +SKIP
        ValueError: ERR_INVALID_NUMBER: Floats not allowed in C_safe (must be pre-quantized)
    """
    # 1. Reject floats entirely
    if isinstance(value, float):
        # Check for NaN/Inf first for better error messages
        if not math.isfinite(value):
            raise ValueError("ERR_INVALID_NUMBER: NaN or Infinity not allowed")
        else:
            raise ValueError("ERR_INVALID_NUMBER: Floats not allowed in C_safe (must be pre-quantized by sensor adapter)")
    
    # 2. Validate integers are in int64 range
    if isinstance(value, int):
        if not (INT64_MIN <= value <= INT64_MAX):
            raise ValueError(f"ERR_INTEGER_RANGE: Value {value} exceeds int64 bounds [{INT64_MIN}, {INT64_MAX}]")
        return value
    
    # 3. Other types (bool, str, etc.) pass through
    # (Type validation handled elsewhere in pipeline)
    return value


# --- Example Sensor Adapter Quantization (UPSTREAM of decision kernel) ---
from decimal import Decimal, ROUND_HALF_EVEN, InvalidOperation

def sensor_adapter_quantize(decimal_string: str, scale: int = 1000000) -> int:
    """
    Example quantization in sensor adapter (NOT in decision kernel).
    
    Uses decimal arithmetic to avoid float portability issues.
    MUST quantize from raw decimal string (not binary float).
    
    Args:
        decimal_string: Raw sensor reading as decimal string ("123.456789")
        scale: Multiplier for desired precision (default 1e6 for micrometers)
        
    Returns:
        Quantized int64 value
        
    Raises:
        ValueError: ERR_INVALID_NUMBER or ERR_INTEGER_RANGE
        
    Examples:
        >>> sensor_adapter_quantize("123.456789", 1000000)
        123456789
        >>> sensor_adapter_quantize("1.5", 1)  # Ties-to-even
        2
        >>> sensor_adapter_quantize("0.5", 1)
        0
        >>> sensor_adapter_quantize("1.23e-4", 1000000)
        123
    """
    try:
        # Parse from raw decimal string (CRITICAL for determinism)
        decimal_val = Decimal(decimal_string)
    except (InvalidOperation, ValueError):
        raise ValueError(f"ERR_INVALID_NUMBER: Invalid decimal string: {decimal_string}")
    
    # Check for NaN/Inf
    if decimal_val.is_nan() or decimal_val.is_infinite():
        raise ValueError("ERR_INVALID_NUMBER: NaN or Infinity not allowed")
    
    # Scale using decimal arithmetic (not float)
    scaled = decimal_val * Decimal(str(scale))
    
    # Round ties-to-even (IEEE 754 default)
    quantized = int(scaled.quantize(Decimal('1'), rounding=ROUND_HALF_EVEN))
    
    # Range check
    if not (INT64_MIN <= quantized <= INT64_MAX):
        raise ValueError(f"ERR_INTEGER_RANGE: {quantized} exceeds int64 bounds")
    
    return quantized

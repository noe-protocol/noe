"""
noe/explain.py

Helper functions for human-readable explanation of Noe evaluation results
and context objects. Used by noe_playground.py.
"""


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"

GREEN  = lambda t: _c("92", t)
RED    = lambda t: _c("91", t)
YELLOW = lambda t: _c("93", t)
DIM    = lambda t: _c("2",  t)


def explain_result(result) -> str:
    """
    Return a one-line human-readable explanation of an evaluation result.

    Handles the standard domains: action, list, truth, undefined, error.
    Falls back to a generic repr for anything else.
    """
    domain = getattr(result, "domain", None) or (result.get("domain") if isinstance(result, dict) else "")
    value  = getattr(result, "value", None)  or (result.get("value")  if isinstance(result, dict) else None)
    code   = getattr(result, "code", None)   or (result.get("code")   if isinstance(result, dict) else "")

    if domain in ("action", "list"):
        target = ""
        if domain == "action" and isinstance(value, dict):
            target = value.get("target", "")
        elif domain == "list" and isinstance(value, list):
            targets = [v.get("target", "") for v in value if isinstance(v, dict)]
            target = ", ".join(t for t in targets if t)
        return GREEN(f"PERMIT  → {target}") if target else GREEN("PERMIT")

    if domain == "truth":
        return YELLOW(f"TRUTH  value={value}")

    if domain == "undefined":
        return RED("BLOCK  (undefined - grounding missing from C_safe)")

    if domain in ("error", "err") or code:
        return RED(f"ERROR  {code or str(value)[:60]}")

    return DIM(f"{domain}  {str(value)[:60]}")


def print_context(ctx: dict) -> None:
    """
    Print the current context in a human-readable table.
    Shows each literal, its value, and whether it is grounded (in knowledge).
    """
    literals  = ctx.get("literals", {})
    knowledge = ctx.get("modal", {}).get("knowledge", {})

    if not literals:
        print(DIM("  (empty context)"))
        return

    print(DIM("  ────────────────────────────────────────────────────────────"))
    for lit in sorted(literals.keys()):
        val = literals[lit]
        is_grounded = lit in knowledge

        if isinstance(val, bool):
            val_str = str(val).lower()
        elif isinstance(val, str):
            val_str = val[:16]
        elif isinstance(val, dict):
            # Sensor literal or action target
            inner = val.get("value", val.get("type", ""))
            val_str = str(inner)[:16] if inner else "dict"
        else:
            val_str = str(val)[:16]

        status = GREEN("✓ grounded") if is_grounded else YELLOW("literal only")
        print(f"    {lit:<28} {val_str:<16} {status}")
    print(DIM("  ────────────────────────────────────────────────────────────"))

#!/usr/bin/env python3
"""
noe_playground.py - Interactive Noe chain evaluator.

Type a Noe chain. See canonical form, gloss, parse tree, and verdict.
Modify the context on the fly to watch evaluation change.

Commands:
  :help             - show this help
  :examples         - print example chains
  :context          - print current context
  :set @lit true    - set a literal to true in C_safe
  :set @lit false   - set a literal to false in C_safe
  :unset @lit       - remove a literal from C_safe
  :mode strict      - evaluate in strict mode (default - real Noe semantics)
  :mode partial     - evaluate in partial mode (relaxed grounding)
  :tree on          - show parse tree (default: on)
  :tree off         - hide parse tree
  :reset            - restore default C_safe
  :quit / :q / Ctrl+D

Usage:
  python3 noe_playground.py
"""

import sys
import os
import time
import readline  # enables arrow-key history

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from arpeggio import Terminal, NonTerminal
from noe.noe_parser import run_noe_logic, _get_or_create_parser
from noe.gloss import gloss_chain

# ── ANSI colours ──────────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"

GREEN  = lambda t: _c("92", t)
RED    = lambda t: _c("91", t)
YELLOW = lambda t: _c("93", t)
CYAN   = lambda t: _c("96", t)
DIM    = lambda t: _c("2",  t)
BOLD   = lambda t: _c("1",  t)

# ── Built-in examples ─────────────────────────────────────────────────────────

EXAMPLES = [
    ("Simple fact",    "shi @human_present nek"),
    ("Conjunction",    "shi @temperature_ok an shi @location_ok nek"),
    ("Guarded action", "shi @path_clear an shi @controller_ready khi sek mek @move_forward sek nek"),
    ("Shipment gate",  "shi @temperature_ok an shi @location_ok an shi @chain_of_custody_ok an shi @human_clear khi sek mek @release_pallet sek nek"),
    ("Belief example", "vek @door_open nek"),
]

# ── Default C_safe ────────────────────────────────────────────────────────────

def _default_context() -> dict:
    now_ms = int(time.time() * 1000)
    # Epistemic literals (conditions): True = grounded in knowledge, False = literal only
    cond_literals = {
        "@human_present":       True,
        "@path_clear":          True,
        "@controller_ready":    True,
        "@temperature_ok":      True,
        "@location_ok":         True,
        "@chain_of_custody_ok": True,
        "@human_clear":         True,
        "@obstacle_detected":   False,
        "@door_open":           True,
        "@sensor_fresh":        True,
    }
    # Action target literals (mek targets): required by strict mode for action resolution
    action_literals = {
        "@move_forward":   "fwd_target",
        "@release_pallet": "pallet_release",
        "@stop":           "stop_cmd",
        "@send_email":     "email_target",
    }
    knowledge = {k: v for k, v in cond_literals.items() if v is True}
    return {
        "modal":    {"knowledge": knowledge, "belief": {}, "certainty": {}},
        "temporal": {"now": now_ms, "max_skew_ms": 5000.0},
        "spatial":  {"unit": "mm", "thresholds": {"near": 300.0, "far": 2000.0}},
        "literals": {**cond_literals, **action_literals},
        "axioms":   {"value_system": {"accepted": [], "rejected": []}},
        "audit":    {},          # required by strict validator (_validate_audit_strict)
        "entities": {},          # required for entity/spatial operator grounding
        "rel":      {},
        "demonstratives": {},
    }

# ── Verdict formatting ────────────────────────────────────────────────────────

def _format_verdict(result: dict) -> str:
    domain = result.get("domain", "error")
    value  = result.get("value")
    code   = result.get("code", "")

    if domain in ("action", "list"):
        target = ""
        if domain == "action" and isinstance(value, dict):
            target = f"  → {value.get('target', '')}"
        elif domain == "list" and isinstance(value, list):
            targets = [v.get("target", "") for v in value if isinstance(v, dict)]
            target = f"  → {', '.join(t for t in targets if t)}"
        return GREEN(f"PERMIT{target}")

    if domain == "truth":
        return YELLOW(f"TRUTH  value={value}")

    if domain == "undefined":
        return RED("BLOCK  (undefined - grounding missing from C_safe)")

    if domain in ("error", "err") or code:
        return RED(f"ERROR  {code or str(value)[:60]}")

    return DIM(f"{domain}  {str(value)[:60]}")

# ── Parse tree ────────────────────────────────────────────────────────────────

def _node_name(node) -> str:
    rule = getattr(node, "rule_name", None)
    if rule:
        return str(rule)
    rule_obj = getattr(node, "rule", None)
    if rule_obj is not None:
        rule_name = getattr(rule_obj, "rule_name", None)
        if rule_name:
            return str(rule_name)
    return node.__class__.__name__


def _render_parse_tree(node, indent: str = "", is_last: bool = True) -> list[str]:
    branch = "└── " if is_last else "├── "
    lines  = []
    if isinstance(node, Terminal):
        value = getattr(node, "value", "")
        lines.append(f"{indent}{branch}{_node_name(node)}: {value}")
        return lines
    lines.append(f"{indent}{branch}{_node_name(node)}")
    children     = list(node) if isinstance(node, NonTerminal) else []
    child_indent = indent + ("    " if is_last else "│   ")
    for i, child in enumerate(children):
        lines.extend(_render_parse_tree(child, child_indent, i == len(children) - 1))
    return lines


def _print_parse_tree(chain: str) -> None:
    try:
        parser     = _get_or_create_parser()
        parse_tree = parser.parse(chain)
        print(f"  {DIM('Parse tree:')}")
        for line in _render_parse_tree(parse_tree):
            print(f"  {DIM(line)}")
    except Exception as exc:
        print(f"  {DIM('Parse tree:')}  {RED(f'unavailable - {exc}')}")

# ── Context display ───────────────────────────────────────────────────────────

def _print_context(ctx: dict) -> None:
    knowledge = ctx.get("modal", {}).get("knowledge", {})
    literals  = ctx.get("literals", {})
    all_keys  = sorted(set(list(knowledge.keys()) + list(literals.keys())))
    print()
    print(BOLD("  Current context:"))
    print(DIM("  " + "─" * 60))
    for k in all_keys:
        in_k    = k in knowledge
        val     = literals.get(k, knowledge.get(k))
        grounded = GREEN("✓ grounded") if in_k else DIM("  literal only")
        val_str  = GREEN("true") if val is True else (RED("false") if val is False else str(val))
        print(f"    {k:<28} {val_str:<14} {grounded}")
    print(DIM("  " + "─" * 60))
    print(DIM("  Use :set @literal true/false or :unset @literal to modify."))
    print()

# ── Examples display ──────────────────────────────────────────────────────────

def _print_examples() -> None:
    print()
    print(BOLD("  Example chains:"))
    print(DIM("  " + "─" * 60))
    for i, (label, chain) in enumerate(EXAMPLES, start=1):
        print(f"  {i}. {label}")
        print(f"     {chain}")
        print(f"     {DIM(gloss_chain(chain))}")
    print(DIM("  ─" * 30))
    print(DIM("  Copy any chain above and paste it at the prompt."))
    print()

# ── Help ──────────────────────────────────────────────────────────────────────

HELP = f"""
{BOLD("Noe Playground")} - interactive chain evaluator

{CYAN("Commands:")}
  {YELLOW(":help")}               show this help
  {YELLOW(":examples")}           print example chains
  {YELLOW(":context")}            print current context
  {YELLOW(":set @lit true")}      add @lit to C_safe as true (grounded)
  {YELLOW(":set @lit false")}     set @lit to false (literal only, not grounded)
  {YELLOW(":unset @lit")}         remove @lit from C_safe entirely
  {YELLOW(":mode strict")}        evaluate in strict mode (default - real Noe semantics)
  {YELLOW(":mode partial")}       evaluate in partial mode (relaxed grounding)
  {YELLOW(":tree on|off")}        show or hide parse tree
  {YELLOW(":integrate")}          print a minimal Python integration snippet for the current chain
  {YELLOW(":reset")}              restore default C_safe
  {YELLOW(":quit")} or {YELLOW(":q")}        exit
"""

COLD_START = (
    f"\n  {BOLD('Noe Gate')}  {DIM('— epistemic safety chains for physical systems')}\n"
    f"  {DIM('The gate between a planner')}"
    f"{DIM(chr(39))}{DIM('s intent and a robot')}{DIM(chr(39))}{DIM('s actuator.')}\n"
    f"  {CYAN('Try:')} shi @path_clear khi sek mek @move_forward sek nek"
    f"   {DIM('(then: :set @path_clear false)')}\n"
)

# ── Context mutation ──────────────────────────────────────────────────────────

def _update_context(ctx: dict, literal: str, value: bool) -> None:
    ctx["literals"][literal] = value
    if value is True:
        ctx["modal"]["knowledge"][literal] = True
    else:
        ctx["modal"]["knowledge"].pop(literal, None)
    ctx["temporal"]["now"] = int(time.time() * 1000)


def _unset_context(ctx: dict, literal: str) -> None:
    ctx["literals"].pop(literal, None)
    ctx["modal"]["knowledge"].pop(literal, None)
    ctx["temporal"]["now"] = int(time.time() * 1000)

# ── Integration snippet ───────────────────────────────────────────────────────

def _print_integrate(chain: str, mode: str) -> None:
    # Produces a self-contained snippet the developer can drop into their project.
    # The chain and mode are pre-filled from the current session state.
    snippet = f'''
import sys, os
sys.path.insert(0, "/path/to/noe_reference")  # adjust to your checkout
from noe.noe_parser import run_noe_logic

context = {{  # replace with your grounded context dict
    "modal":    {{"knowledge": {{"@path_clear": True}}, "belief": {{}}, "certainty": {{}}}},
    "temporal": {{"now": 0, "max_skew_ms": 5000}},
    "spatial":  {{"thresholds": {{"near": 300.0, "far": 2000.0}}}},
    "literals": {{"@path_clear": True, "@move_forward": "fwd_target"}},
    "axioms":   {{"value_system": {{"accepted": [], "rejected": []}}}},
    "audit": {{}}, "entities": {{}}, "rel": {{}}, "demonstratives": {{}},
}}

result = run_noe_logic(
    {chain!r},
    context,
    mode={mode!r},  # "strict" for production; "partial" for development
)

if result["domain"] == "action":
    print("PERMIT", result["value"]["target"])
elif result["domain"] == "undefined":
    print("BLOCK  — grounding missing from context")
else:
    print("ERROR ", result.get("code"), result.get("value"))
'''
    print()
    print(BOLD("  Integration snippet:"))
    print(DIM("  " + "─" * 60))
    for ln in snippet.strip().splitlines():
        print(f"    {CYAN(ln)}")
    print(DIM("  " + "─" * 60))
    print(DIM("  Copy into your project. Adjust sys.path and context to match your setup."))
    print()


# ── Main REPL ─────────────────────────────────────────────────────────────────

def main() -> None:
    print(COLD_START)

    ctx       = _default_context()
    mode      = "strict"
    show_tree = True
    last_chain = "shi @path_clear khi sek mek @move_forward sek nek"

    while True:
        try:
            line = input(CYAN(f"noe [{mode}]> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        # ── Commands ────────────────────────────────────────────────────────
        if line.startswith(":"):
            parts = line.split()
            cmd   = parts[0].lower()

            if cmd in (":quit", ":q", ":exit"):
                break

            elif cmd == ":help":
                print(HELP)

            elif cmd == ":examples":
                _print_examples()

            elif cmd == ":context":
                _print_context(ctx)

            elif cmd == ":reset":
                ctx = _default_context()
                print(DIM("  C_safe reset to defaults."))

            elif cmd == ":mode":
                if len(parts) < 2 or parts[1] not in ("strict", "partial"):
                    print(RED("  Usage: :mode strict | :mode partial"))
                else:
                    mode = parts[1]
                    note = "(real Noe semantics - recommended)" if mode == "strict" else "(relaxed grounding)"
                    print(DIM(f"  Mode → {mode} {note}"))

            elif cmd == ":tree":
                if len(parts) < 2 or parts[1] not in ("on", "off"):
                    print(RED("  Usage: :tree on | :tree off"))
                else:
                    show_tree = (parts[1] == "on")
                    print(DIM(f"  Parse tree → {'on' if show_tree else 'off'}"))

            elif cmd == ":set":
                if len(parts) < 3 or not parts[1].startswith("@"):
                    print(RED("  Usage: :set @literal true|false"))
                else:
                    lit     = parts[1]
                    val_str = parts[2].lower()
                    if val_str in ("true", "1", "yes"):
                        _update_context(ctx, lit, True)
                        print(GREEN(f"  {lit} → true (grounded)"))
                    elif val_str in ("false", "0", "no"):
                        _update_context(ctx, lit, False)
                        print(YELLOW(f"  {lit} → false (literal only, not grounded)"))
                    else:
                        print(RED(f"  Unknown value '{val_str}'. Use true or false."))

            elif cmd == ":unset":
                if len(parts) < 2 or not parts[1].startswith("@"):
                    print(RED("  Usage: :unset @literal"))
                else:
                    lit = parts[1]
                    _unset_context(ctx, lit)
                    print(DIM(f"  {lit} removed from C_safe."))

            elif cmd == ":integrate":
                _print_integrate(last_chain, mode)

            else:
                print(RED(f"  Unknown command '{cmd}'. Type :help."))

            continue

        # ── Chain evaluation ────────────────────────────────────────────────
        chain      = line
        last_chain = chain  # track for :integrate
        glossed    = gloss_chain(chain)

        print()
        print(f"  {DIM('Canonical:')}  {chain}")
        print(f"  {DIM('Gloss    :')}  {CYAN(glossed)}")

        if show_tree:
            _print_parse_tree(chain)

        try:
            ctx["temporal"]["now"] = int(time.time() * 1000)
            result  = run_noe_logic(chain, ctx, mode=mode)
            verdict = _format_verdict(result)
            print(f"  {DIM('Verdict  :')}  {verdict}")
        except Exception as exc:
            print(f"  {DIM('Verdict  :')}  {RED(f'PARSE ERROR - {exc}')}")

        print()


if __name__ == "__main__":
    main()

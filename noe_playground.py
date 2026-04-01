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
from noe.noe_parser import _get_or_create_parser
from noe.gloss import gloss_chain
from noe import ContextManager, NoeRuntime

# ── ANSI colours ──────────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"

GREEN  = lambda t: _c("92", t)
RED    = lambda t: _c("91", t)
YELLOW = lambda t: _c("93", t)
CYAN   = lambda t: _c("96", t)
DIM    = lambda t: _c("2",  t)
BOLD   = lambda t: t

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
        "@human_present":       False,
        "@path_clear":          True,
        "@controller_ready":    True,
        "@temperature_ok":      True,
        "@location_ok":         True,
        "@chain_of_custody_ok": True,
        "@human_clear":         True,
        "@obstacle_detected":   False,
        "@door_open":           True,
        "@sensor_fresh":        True,
        "@lidar_zone_clear":    True,
        "@camera_no_human":     True,
        "@estop_released":      True,
    }
    # Action target literals (mek targets): required by strict mode for action resolution
    action_literals = {
        "@move_forward":        "fwd_target",
        "@release_pallet":      "pallet_release",
        "@stop":                "stop_cmd",
        "@send_email":          "email_target",
        "@enter_zone_alpha":    "zone_alpha_target",
        "@enter_room":          "room_target",
        "@resume_operations":   "resume_cmd",
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

def explain_result(result) -> str:
    if result.domain in ("action", "list"):
        actions = []
        val_list = result.value if isinstance(result.value, list) else [result.value]
        for a in val_list:
            if not isinstance(a, dict):
                continue
            v_name = str(a.get('target', 'unknown_target'))
            args = [str(x) for x in a.get('args', [])]
            actions.append(f"{v_name}({', '.join(args)})")
        
        verbs_str = ", ".join(actions)
        return f"{GREEN(BOLD('Verdict: PERMIT'))}  {DIM('(--> Action permitted. All guards satisfied under grounded context: ')}{verbs_str}{DIM(')')}"
    elif result.domain == "undefined":
        return f"{YELLOW(BOLD('Verdict: BLOCKED'))} {DIM('(--> Refused. The required facts are not present in the grounded context.)')}"
    elif result.domain in ("error", "err"):
        err_msg = str(result.error or result.value or "Unknown structural error")
        return f"{RED(BOLD('Verdict: ERROR'))} {DIM(f'(--> Refused. Structural error or type mismatch: {err_msg})')}"
    return f"{DIM('Verdict: UNKNOWN')} ({result.domain})"

def print_context(ctx: dict) -> None:
    knowledge = ctx.get("modal", {}).get("knowledge", {})
    literals  = ctx.get("literals", {})
    all_keys  = sorted(set(list(knowledge.keys()) + list(literals.keys())))
    print("\n  " + BOLD("Current Context Overview:"))
    print(DIM("  " + "─" * 60))
    for k in all_keys:
        in_k    = k in knowledge
        val     = literals.get(k, knowledge.get(k))
        grounded = GREEN("✓ grounded") if in_k else DIM("  literal only")
        val_str  = GREEN("true") if val is True else (RED("false") if val is False else str(val))
        print(f"    {k:<28} {val_str:<14} {grounded}")
    print(DIM("  " + "─" * 60) + "\n")
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
  {YELLOW(":scenarios")}          run curated permit/blocked scenarios
  {YELLOW(":context")}            print current context
  {YELLOW(":set @lit true")}      add @lit to C_safe as true (grounded)
  {YELLOW(":set @lit false")}     set @lit to false (literal only, not grounded)
  {YELLOW(":unset @lit")}         remove @lit from C_safe entirely
  {YELLOW(":mode strict")}        evaluate in strict mode (default - real Noe semantics)
  {YELLOW(":mode partial")}       evaluate in partial mode (relaxed grounding)
  {YELLOW(":tree on|off")}        show or hide parse tree
  {YELLOW(":glyphs")}             show Noe unicode visual representation
  {YELLOW(":integrate")}          print a minimal Python integration snippet for the current chain
  {YELLOW(":next")}               show directory of integration, adapter, and threat model docs
  {YELLOW(":reset")}              restore default C_safe
  {YELLOW(":quit")} or {YELLOW(":q")}        exit
"""

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
    # 1. Extract predicates (following shi/vek) and actions (following mek/men)
    preds, actions = [], []
    tokens = chain.split()
    for i, t in enumerate(tokens):
        if t.startswith("@"):
            if i > 0 and tokens[i-1] in ("mek", "men"):
                if t not in actions: actions.append(t)
            else:
                if t not in preds: preds.append(t)

    kn_str = ", ".join([f'"{p}": True' for p in preds]) if preds else ""
    
    lit_items = [f'"{p}": True' for p in preds]
    for i, a in enumerate(actions):
        lit_items.append(f'"{a}": "tgt_{i}"')
    lit_str = ", ".join(lit_items) if lit_items else ""

    snippet = f'''
from noe import parse_chain, evaluate

chain = parse_chain({chain!r})

# Minimum context required to evaluate
context = {{
    "modal": {{"knowledge": {{{kn_str}}}}},
    "literals": {{{lit_str}}}
}}

result = evaluate(chain, context)

if getattr(result, "domain", "") == "action":
    print("PERMIT", getattr(result, "value", "unknown_target"))
elif getattr(result, "domain", "") == "undefined":
    print("BLOCK  — grounding missing from context")
else:
    print("ERROR ", getattr(result, "code", getattr(result, "value", "")))
'''
    print("\n" + BOLD("  Minimal integration:"))
    for ln in snippet.strip().splitlines():
        print(f"    {CYAN(ln)}")
    print("\n  " + DIM("The chain shown above is the one you last evaluated."))
    print("  " + DIM("Swap in your own predicates and actions.\n"))
    print(f"  {DIM('── Next steps ──────────────────────────────────────────────')}")
    print(f"  Ready to build? Start here: {CYAN('docs/quickstart_llm_governance.md')}")
    print(f"  For ROS2, threat model, or contributing: type {CYAN(':next')}")
    print(f"  {DIM('───────────────────────────────────────────────────────────')}\n")


def _print_parse_error(chain: str, exc: Exception) -> None:
    exc_str = str(exc)
    
    if not chain.strip():
        msg = "Empty chain"
        fix = "Type a chain or :examples for reference"
    elif chain.strip().endswith("sek"):
        msg = "Missing chain terminator"
        fix = "Add 'nek' (END) at the end"
    elif 'mek' in chain and not ('sek' in chain and 'nek' in chain):
        msg = "Missing scope close"
        fix = "Add 'sek nek' to close the guarded block"
    elif "Expected" in exc_str and "sek" in exc_str:
        msg = "Missing scope close"
        fix = "Add 'sek nek' to close the guarded block"
    elif "=> 'mek" in exc_str or "=> 'men" in exc_str:
        msg = "Action outside guarded block"
        fix = "Wrap with 'khi sek mek @action sek nek'"
    elif "=>" in exc_str and "Expected" in exc_str:
        token_snippet = exc_str.split("=>")[-1].strip().strip("'")
        msg = f"Unrecognized token: '{token_snippet}'"
        fix = "Check your syntax or type :examples"
    else:
        if "Expected" in exc_str and "at position" in exc_str:
            pos_part = exc_str.split("at position")[-1]
            msg = "Syntax error"
            fix = f"Failed at position {pos_part.strip()}"
        else:
            msg = "Syntax error"
            fix = exc_str
            
    print(f"  {DIM('Verdict  :')}  {RED('ERROR')} — {msg}\n")
    print(f"  This chain is structurally malformed.")
    print(f"  {DIM('Expected :')} {fix}")


def _print_filtered_context(chain: str, ctx: dict) -> None:
    """Print only the context lines relevant to the evaluated chain."""
    used_literals = {word for word in chain.split() if word.startswith("@")}
    if not used_literals:
        print_context(ctx)
        return
        
    print(DIM("  ────────────────────────────────────────────────────────────"))
    for lit in sorted(used_literals):
        is_literal = lit in ctx.get("literals", {})
        val = ctx.get("literals", {}).get(lit, "not_present")
        is_grounded = lit in ctx.get("modal", {}).get("knowledge", {})
        
        val_str = str(val).lower() if isinstance(val, bool) else str(val)
        status = GREEN("✓ grounded") if is_grounded else YELLOW("literal only")

        if not is_literal:
            print(f"    {lit:<28} {DIM('not in C_safe (undefined)')}")
        else:
            print(f"    {lit:<28} {val_str:<5}  {status}")
    print(DIM("  ────────────────────────────────────────────────────────────"))
    
    # We only want to show the 'grounded'/'literal only' explanation once
    if not getattr(_print_filtered_context, "has_run", False):
        print(DIM("  (grounded = admitted as verified knowledge. literal only = present but not accepted as known)\n"))
        _print_filtered_context.has_run = True
    else:
        print()

# ── Main REPL ─────────────────────────────────────────────────────────────────

def main() -> None:
    welcome_screen = f"""
{RED('▽ Noe Gate 1.0 (main) — Deterministic action gating.')}
{BOLD(' ███    ██  ██████  ███████      ██████   █████  ████████ ███████')}
{BOLD(' ████   ██ ██    ██ ██          ██       ██   ██    ██    ██     ')}
{BOLD(' ██ ██  ██ ██    ██ █████       ██   ███ ███████    ██    █████  ')}
{BOLD(' ██  ██ ██ ██    ██ ██          ██    ██ ██   ██    ██    ██     ')}
{BOLD(' ██   ████  ██████  ███████      ██████  ██   ██    ██    ███████')}
{RED('               ▽ NOE GATE ▽')}

{DIM('╭── Noe Gate ─────────────────────────────────────────────────────────╮')}
{DIM('│')} Planners and LLMs propose actions. Noe Gate decides whether they    {DIM('│')}
{DIM('│')} may execute. It checks grounded context — not trust, not intent.    {DIM('│')}
{DIM('│')}                                                                     {DIM('│')}
{DIM('│')} If the required knowledge is absent, execution does not pass.       {DIM('│')}
{DIM('╰─────────────────────────────────────────────────────────────────────╯')}
"""
    print(welcome_screen)
    try:
        input("  [Enter] Start  \n──────────────────────────────────────────────────────────────────────\n")
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)
    
    print("\n")

    ctx       = _default_context()
    mode      = "strict"
    show_tree = False
    show_glyphs = False
    last_chain = "shi @path_clear khi sek mek @move_forward sek nek"
    
    first_eval_done = False
    first_block_done = False
    first_conjunction_done = False

    cm = ContextManager(root=ctx, domain={}, local=ctx)
    rt = NoeRuntime(context_manager=cm, strict_mode=(mode=="strict"))

    # Initial guided prompt
    print("\n" + DIM("Let's evaluate a chain. This rule says: move forward may execute only if path_clear is known.\n"))
    print(f"  {DIM('Gloss: ')} {YELLOW('KNOW @path_clear IF [ DO @move_forward ] END')}")
    print(f"  {DIM('Chain: ')} {CYAN('shi @path_clear khi sek mek @move_forward sek nek')}\n")
    print(DIM("Paste the chain below and press Enter."))

    while True:
        try:
            line = input(CYAN(f"\nnoe [{mode}]> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

        if not line:
            continue

        # ── Commands ────────────────────────────────────────────────────────
        parts = line.split()
        cmd   = parts[0].lower() if parts else ""

        # Intercept commands (either explicit : commands, or known safe intercepts)
        if cmd.startswith(":") or cmd in ("quit", "exit", "q", "help", "clear", "back", "menu"):
            if cmd in (":quit", ":q", ":exit", "quit", "exit", "q"):
                sys.exit(0)

            elif cmd in (":menu", "menu", "back"):
                break

            elif cmd in (":help", "help"):
                print(HELP)

            elif cmd == ":examples" or cmd == ":scenarios":
                print("\n  " + BOLD("Domain Scenarios"))
                print(DIM("  ────────────────────────────────────────────────────────────"))
                
                print("  1. " + DIM("Multi-sensor zone entry (real-world):"))
                print("     " + CYAN("shi @lidar_zone_clear an shi @camera_no_human an shi @estop_released khi sek mek @enter_zone_alpha sek nek"))
                print("     " + DIM("KNOW @lidar_zone_clear AND KNOW @camera_no_human AND KNOW @estop_released IF [ DO @enter_zone_alpha ] END"))
                print("     " + DIM("Why: No single sensor is sufficient. The gate requires independent grounding from each modality.\n"))
                
                print("  2. " + DIM("Guarded action (simple):"))
                print("     " + CYAN("shi @path_clear khi sek mek @move_forward sek nek"))
                print("     " + DIM("KNOW @path_clear IF [ DO @move_forward ] END\n"))
                
                print("  3. " + DIM("Belief vs knowledge:"))
                print("     " + CYAN("vek @door_open khi sek mek @enter_room sek nek"))
                print("     " + DIM("BELIEVE @door_open IF [ DO @enter_room ] END"))
                print("     " + DIM("Why: 'vek' (BELIEVE) has a lower evidentiary threshold than 'shi' (KNOW)."))
                print("     " + DIM("The chain makes the confidence level explicit and inspectable.\n"))
                
                print("  4. " + DIM("Negation (emergency stop override):"))
                print("     " + CYAN("nai shi @human_present khi sek mek @resume_operations sek nek"))
                print("     " + DIM("NOT KNOW @human_present IF [ DO @resume_operations ] END"))
                print("     " + DIM("Why: Some actions should only proceed when a condition is NOT known."))
                print("     " + DIM("The absence of grounding is itself a gating criterion.\n"))

                print("  5. " + DIM("Malformed — missing scope close and terminator (ERROR):"))
                print("     " + CYAN("shi @path_clear khi sek mek @move_forward"))
                print("     " + DIM("(compare with correct form: shi @path_clear khi sek mek @move_forward sek nek)\n"))

                print(DIM("  Copy any chain and paste it at the prompt."))

            elif cmd == ":context":
                print("\n  " + BOLD("Current Context Components:"))
                print_context(ctx)
                print(DIM("  (grounded = admitted as verified knowledge. literal only = present but not accepted as known)\n"))

            elif cmd == ":reset":
                ctx = _default_context()
                cm = ContextManager(root=ctx, domain={}, local=ctx)
                rt.context_manager = cm
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

            elif cmd == ":glyphs":
                if len(parts) < 2 or parts[1] not in ("on", "off"):
                    print(RED("  Usage: :glyphs on | :glyphs off"))
                else:
                    show_glyphs = (parts[1] == "on")
                    print(DIM(f"  Glyphs → {'on' if show_glyphs else 'off'}"))

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
                        msg = "no longer admitted as known" if not first_eval_done or not first_block_done else "literal only, not grounded"
                        print(YELLOW(f"  {lit} → false ({msg})"))
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

            elif cmd == ":next":
                print("\n  " + BOLD("── Where to go from here ──────────────────────────────────"))
                print(f"  Python integration:    {CYAN('docs/quickstart_llm_governance.md')}")
                print(f"  ROS2 adapter:          {CYAN('ros2_adapter/README.md')}")
                print(f"  Threat model:          {CYAN('THREAT_MODEL.md')}")
                print(f"  Conformance suite:     {CYAN('tests/nip011/README.md')}")
                print(f"  Contribute:            {CYAN('github.com/noe-protocol/noe-gate/discussions')}")
                print(f"  Issues:                {CYAN('github.com/noe-protocol/noe-gate/issues')}")
                print(f"  {DIM('───────────────────────────────────────────────────────────')}\n")

            elif cmd == ":cert":
                import hashlib
                chash = hashlib.sha256(last_chain.encode('utf-8')).hexdigest()
                # Run evaluation quietly
                rt_cert = NoeRuntime(context_manager=ContextManager(root=ctx, domain={}, local=ctx), strict_mode=(mode=="strict"))
                res_cert = rt_cert.evaluate(last_chain)
                ctx_hash = getattr(res_cert, "context_hash", "<uncomputed>")
                ts = getattr(res_cert, "snapshot_ts", int(time.time()*1000))
                dom = getattr(res_cert, "domain", "unknown").upper()
                
                print(f"  {BOLD('Certificate Record')}")
                print(f"  {DIM('────────────────────────────────────────')}")
                print(f"    {DIM('context_hash:')}  {CYAN(ctx_hash)}")
                print(f"    {DIM('chain_hash:')}    {CYAN(chash)}")
                print(f"    {DIM('verdict:')}       {RED(dom) if dom == 'UNDEFINED' else GREEN(dom)}")
                print(f"    {DIM('timestamp_ms:')}  {CYAN(str(ts))}")
                print(f"  {DIM('────────────────────────────────────────')}")

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

        if show_glyphs:
            if chain == "shi @path_clear khi sek mek @move_forward sek nek":
                print(f"  {DIM('Glyphs   :')}  {CYAN('ʖ @path_clear ⟠ § 𐍀 @move_forward § —')}")
            else:
                print(f"  {DIM('Glyphs   :')}  {DIM('On-the-fly glyph generation not available for custom chains')}")

        if show_tree:
            _print_parse_tree(chain)

        try:
            ctx["temporal"]["now"] = int(time.time() * 1000)
            
            rt = NoeRuntime(context_manager=ContextManager(root=ctx, domain={}, local=ctx), strict_mode=(mode=="strict"))
            result = rt.evaluate(chain)

            domain = getattr(result, "domain", "")
            
            if domain == "action":
                target = getattr(getattr(result, "value", None), "target", getattr(result, "value", ""))
                if not target and isinstance(getattr(result, "value", None), dict):
                    target = result.value.get("target", "")
                print(f"  {DIM('Verdict  :')}  {GREEN('PERMIT')} → {target}")
            elif domain == "list":
                targets = [v.get("target", "") for v in result.value if isinstance(v, dict)]
                print(f"  {DIM('Verdict  :')}  {GREEN('PERMIT')} → {', '.join(targets)}")
            elif domain == "undefined":
                missing_lits = []
                for word in chain.split():
                    if word.startswith("@"):
                        val = ctx.get("literals", {}).get(word)
                        is_action = isinstance(val, str)
                        if not is_action and not ctx.get("modal", {}).get("knowledge", {}).get(word, False):
                            if word not in missing_lits:
                                missing_lits.append(word)
                
                if missing_lits:
                    missing_str = ", ".join(missing_lits)
                    print(f"  {DIM('Verdict  :')}  {RED('BLOCK')} (undefined — {missing_str} not grounded in C_safe)")
                else:
                    print(f"  {DIM('Verdict  :')}  {RED('BLOCK')} (undefined — grounding missing from C_safe)")
                
                if first_block_done:
                    print(f"\n  {DIM('Hint: Use ')}:set @literal true{DIM(' to ground missing predicates, or ')}:reset{DIM(' to restore defaults.')}")
            elif domain == "error":
                _print_parse_error(chain, result.value)
            else:
                if domain == "truth":
                    print(f"  {DIM('Verdict  :')}  {YELLOW('TRUTH')} value={getattr(result, 'value', '')}")
                else:
                    print(f"  {DIM('Verdict  :')}  {explain_result(result)}")

            # State Transitions
            if not first_eval_done:
                first_eval_done = True
                if domain in ("action", "list"):
                    # Only show the guided output if they evaluated and it permitted correctly
                    print(f"\n  {DIM('Context (why it permitted):')}")
                    _print_filtered_context(chain, ctx)
                    m1 = "The gate didn't trust the proposal. It checked whether "
                    print(f"  {DIM(m1)}@path_clear")
                    m2 = "is grounded — verified by a sensor, adapter, or trusted source."
                    print(f"  {DIM(m2)}")
                    m3 = 'An LLM or planner asserting "path is clear" is not enough.'
                    print(f"  {DIM(m3)}\n")
                    print(f"  {DIM('Now try: ')}:set @path_clear false")
                    print(f"  {DIM('Then re-run the same chain.')}")
            elif domain == "undefined" and not first_block_done:
                first_block_done = True
                print()
                _print_filtered_context(chain, ctx)
                
                m1 = "This is not a crash or an exception. BLOCK is a typed semantic outcome."
                print(f"  {DIM(m1)}")
                m2 = 'The gate distinguishes between "not permitted" (undefined) and'
                print(f"  {DIM(m2)}")
                m3 = '"structurally invalid" (error). Downstream systems can handle each differently.'
                print(f"  {DIM(m3)}\n")
                
                print(f"  Same chain. Same code. Different context. Different verdict.")
                print(f"  That is the execution boundary.\n")
                
                import hashlib
                chash = hashlib.sha256(chain.encode('utf-8')).hexdigest()
                ctx_hash = getattr(result, "context_hash", chash[:16] + "...")
                print(f"  {BOLD('Certificate:')}")
                print(f"    {DIM('context_hash:')}  {CYAN(ctx_hash)}")
                print(f"    {DIM('chain_hash:')}    {CYAN(chash)}")
                print(f"    {DIM('verdict:')}       {RED('BLOCK')}")
                print(f"    {DIM('timestamp_ms:')}  {CYAN(str(getattr(result, 'snapshot_ts', int(time.time()*1000))))}\n")
                
                m1 = "This record is replayable. Another conforming runtime — Rust, C++,"
                print(f"  {DIM(m1)}")
                m2 = "a different machine — evaluating the same chain against the same context"
                print(f"  {DIM(m2)}")
                m3 = "will produce the same hashes. That's the basis for cross-system audit"
                print(f"  {DIM(m3)}")
                m4 = "and incident reconstruction."
                print(f"  {DIM(m4)}\n")
                
                ctx.clear()
                ctx.update(_default_context())
                cm = ContextManager(root=ctx, domain={}, local=ctx)
                print(f"  {DIM('Context restored to defaults.')}\n")
                
                print(f"  {DIM('Try a conjunction:')} shi @path_clear an shi @controller_ready khi sek mek @move_forward sek nek")
                print(f"  {DIM('Type :help for commands, :scenarios for examples, or :integrate for a copy-paste snippet.')}")
            
            elif first_block_done and not first_conjunction_done and domain in ("action", "list") and " an " in chain:
                first_conjunction_done = True
                hdr = "You've seen:"
                print(f"\n  {BOLD(hdr)}")
                print(f"    {GREEN('✓')} {DIM('A chain evaluate to PERMIT under grounded context')}")
                print(f"    {GREEN('✓')} {DIM('The same chain BLOCK when grounding is removed')}")
                print(f"    {GREEN('✓')} {DIM('A certificate with replayable hashes')}")
                print(f"    {GREEN('✓')} {DIM('A conjunction gate with multiple predicates')}\n")
                
                print(f"  {DIM('Real gates often require multiple independent checks — sensor fusion,')}")
                print(f"  {DIM('human clearance, temporal freshness — composed in a single auditable chain.')}\n")
                
                msg1 = "Type "
                print(f"  {DIM(msg1)}:integrate{DIM(' for a copy-paste integration snippet,')}")
                print(f"  {DIM('or ')}:scenarios{DIM(' to explore domain examples (zone entry, sensor fusion, belief vs knowledge).')}")
                
        except Exception as exc:
            _print_parse_error(chain, exc)

        print()


if __name__ == "__main__":
    main()

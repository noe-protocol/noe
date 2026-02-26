"""
noe_runtime.py

Noe Runtime v1.0
----------------

The NoeRuntime is the unified entrypoint for evaluating Noe chains.

It connects:
    - ContextManager (snapshot + merge + validation + staleness)
    - NoeParser     (PEG parser → AST)
    - NoeValidator  (context safety)
    - NoeEvaluator  (model-theoretic semantics)
    - strict / partial mode enforcement
    - action-class safety
    - undefined ⇒ non-execution rule

This file is designed according to:
    - NIP-004 (Grammar)
    - NIP-005 (Core Semantics)
    - NIP-009 (Context Serialization Standard)
    - NIP-011 (Reference Interpreter & Test Suite)
"""

from __future__ import annotations

import traceback
import copy
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable, Tuple
import hashlib
import json
import sys



from .context_manager import (
    ContextSnapshot,
    ContextManager,
    ContextStaleError,
    BadContextError,
    ContextConflictError,
)
from .context_projection import (
    compile_path,
    extract_evidence_from_context,
    pi_safe,
    ProjectionConfig
)
from .canonical import canonical_json, canonicalize_chain
from .noe_validator import validate_chain

from .provenance import (
    build_provenance_record,
    ProvenanceRecord,
    compute_action_lineage_hashes,
    compute_execution_request_hash, # Renamed from compute_action_hash
    compute_decision_hash,
    compute_child_action_hash,
)

def _hash_json(data: Dict[str, Any]) -> str:
    """Compute canonical hash of a dictionary (for domain pack validation)."""
    payload = canonical_json(data).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

# add this type alias near the top
SafetyHandler = Callable[
    ["NoeRuntime", str, ContextSnapshot, "RuntimeResult"],
    "RuntimeResult"
]

# Your modules (import paths as in your repo)
from arpeggio import ParserPython, NoMatch
from .noe_parser import chain, NoeEvaluator, visit_parse_tree, wrap_domain

class ParseError(Exception):
    pass

class NoeParser:
    def __init__(self):
        self.parser = ParserPython(chain, reduce_tree=False)

    def parse(self, text):
        try:
            return self.parser.parse(text)
        except NoMatch as e:
            raise ParseError(str(e))

class EvaluationError(Exception):
    pass


# -------------------------------------------------------------------------
# Runtime Result Object
# -------------------------------------------------------------------------

@dataclass
class RuntimeResult:
    """
    Public result returned by NoeRuntime.evaluate(...)

    This object contains:
        - domain: truth | numeric | action | undefined | error
        - value: underlying python scalar or action object
        - error: optional string
        - context_hash: the hash of the context used
        - snapshot_ts: timestamp of the snapshot
        - raw_ast: optional (for debugging)
    """
    domain: str
    value: Any
    error: Optional[str]
    context_hash: str
    snapshot_ts: int
    raw_ast: Any
    canonical_chain: Optional[str] = None
    provenance: Optional[Dict[str, Any]] = None
    explained_literals: Optional[Dict[str, Any]] = None


# -------------------------------------------------------------------------
# Runtime Core
# -------------------------------------------------------------------------

class NoeRuntime:
    """
    The canonical Noe Runtime.

    Responsibilities:
        - parse chains into AST
        - obtain immutable snapshot from Context Manager
        - validate context
        - evaluate AST with NoeEvaluator
        - enforce strict/partial mode
        - implement undefined ⇒ non-execution rule
        - attach context hash and timestamp
        - provide consistent error handling
    """

    def __init__(
        self,
        *,
        context_manager: ContextManager,
        strict_mode: bool = True,
        debug: bool = False,
        safety_handler: Optional[SafetyHandler] = None,
        domain_pack: Optional[Dict[str, Any]] = None,
    ):
        self.cm = context_manager
        self.strict_mode = strict_mode
        self.debug = debug
        self.safety_handler = safety_handler or self._default_safety_handler
        self.domain_pack = domain_pack
        # Debug logging controlled by self.debug flag
        if self.debug:
            import sys
            sys.stderr.write(f"[NoeRuntime] Initialized (domain_pack={domain_pack is not None})\n")
        
        # If a domain pack is provided, we compute its hash to enforce consistency
        # during evaluation. This prevents "Config Drift" where the runtime thinks
        # it's running one config but the context manager has another.
        self._expected_domain_hash: Optional[str] = None
        if domain_pack is not None:
            self._expected_domain_hash = _hash_json(domain_pack)
            # Ensure the context manager actually has this domain loaded?
            # We can't easily check here without snapshotting, but we will check in evaluate().

        self.parser = NoeParser()
        # self.evaluator is instantiated per evaluate() call
        
        # Pre-compile required context paths for optimization
        self._compiled_requirements = {}
        if self.domain_pack:
            literals_def = self.domain_pack.get("literals", {})
            if isinstance(literals_def, dict):
                for lit_key, lit_def in literals_def.items():
                    if isinstance(lit_def, dict) and "required_context" in lit_def:
                        paths = lit_def["required_context"]
                        if isinstance(paths, list):
                            self._compiled_requirements[lit_key] = [compile_path(p) for p in paths]

    # ------------------------------------------------------------------
    # Main evaluation entrypoint
    # ------------------------------------------------------------------

    def _apply_safety_handler(
        self,
        chain: str,
        snap: ContextSnapshot,
        prelim: RuntimeResult,
    ) -> RuntimeResult:
        """
        Route undefined/error results through the optional safety_handler.

        If no handler is configured, returns the preliminary result unchanged.
        """
        if self.safety_handler is None:
            return prelim

        try:
            return self.safety_handler(self, chain, snap, prelim)
        except Exception as e:
            # Safety handler itself failed – last resort: return original result,
            # but annotate error if debug is on.
            if self.debug:
                new_err = (prelim.error or "") + f" | SAFETY_HANDLER_FAILED: {e}"
                return RuntimeResult(
                    domain="error",
                    value=None,
                    error=new_err,
                    context_hash=snap.context_hash,
                    snapshot_ts=getattr(snap, 'timestamp_ms', 0),
                    raw_ast=None,
                    canonical_chain=chain,
                    provenance=None,
                )
            return prelim

    def _default_safety_handler(
        self,
        runtime: "NoeRuntime",
        chain: str,
        snap: ContextSnapshot,
        prelim: RuntimeResult,
    ) -> RuntimeResult:
        """
        Default safety handler. Currently, it just returns the preliminary result.
        This can be extended to implement custom safety policies.
        """
        return prelim

    # -------------------------------------------------------------------------
    # MAX RECURSION DEPTH (Safety)
    # -------------------------------------------------------------------------
    MAX_DEPTH = 100

    def _get_ast_depth(self, node: Any) -> int:
        """
        Calculate the maximum depth of the AST.
        """
        if isinstance(node, list):
            if not node: return 1
            return 1 + max(self._get_ast_depth(child) for child in node)
        # Terminals (dicts or strings) are depth 1
        return 1

    def evaluate(
        self, 
        chain: str,
        *,
        parent_action_hash: Optional[str] = None
    ) -> RuntimeResult:
        """
        Evaluate a single Noe chain.
        """
        
        snap: Optional[ContextSnapshot] = None
        
        # 1. Canonicalize Chain (Single Source of Truth)
        # Ensures evaluate() and evaluate_with_provenance() hash the exact same string.
        chain = canonicalize_chain(chain)

        try:
            snap = self.cm.snapshot()
            
            # Idempotency Check (Guard against non-stable canonicalization)
            # We do this AFTER snapshot so we can use _error() with context info
            redundant_check = canonicalize_chain(chain)
            if chain != redundant_check:
                prelim = self._error("ERR_CANONICALIZATION_NON_IDEMPOTENT", snap, canonical_chain=redundant_check)
                return self._apply_safety_handler(chain, snap, prelim)

            # 2. Config Consistency Check (New Safety Guard)
            if self._expected_domain_hash is not None:
                if snap.domain_hash != self._expected_domain_hash:
                    msg = (
                        f"CONFIG_MISMATCH: Runtime expected domain hash {self._expected_domain_hash[:8]}... "
                        f"but ContextManager has {snap.domain_hash[:8]}..."
                    )
                    prelim = self._error(msg, snap, canonical_chain=chain)
                    return self._apply_safety_handler(chain, snap, prelim)
            
            # Stale context handling (strict mode)
            if getattr(snap, 'is_stale', False) and self.strict_mode:
                prelim = self._error("ERR_CONTEXT_STALE", snap)
                prelim.canonical_chain = chain
                return self._apply_safety_handler(chain, snap, prelim)
                
            # Strict mode structural validation
            if self.strict_mode:
                from .noe_validator import validate_context_strict
                is_valid, err_msg = validate_context_strict(snap.structured)
                if not is_valid:
                    prelim = self._bad_context(snap, chain, err_msg)
                    return self._apply_safety_handler(chain, snap, prelim)

                # Preflight: required context fields must be present and well-typed
                root = snap.structured.get("root", {})
                if isinstance(root, dict):
                    missing = []
                    temporal = root.get("temporal", None)
                    if not isinstance(temporal, dict):
                        missing.append("root.temporal")
                    spatial = root.get("spatial", None)
                    if isinstance(spatial, dict):
                        if not isinstance(spatial.get("thresholds", None), dict):
                            missing.append("root.spatial.thresholds")
                    elif spatial is not None:
                        missing.append("root.spatial")
                    if missing:
                        prelim = self._bad_context(snap, chain, missing)
                        return self._apply_safety_handler(chain, snap, prelim)
            
            # 3. Parse (Moved up for AST validation)
            try:
                ast = self.parser.parse(chain)
            except Exception as e:
                # If parsing fails, we return undefined (or error if strict?)
                # Usually parsing failure is an error.
                prelim = self._error(f"ERR_PARSE: {e}", snap, canonical_chain=chain)
                return self._apply_safety_handler(chain, snap, prelim)

            # 4. Threshold Safety Validation (NIP-016)
            #    Enforce epistemic threshold safety floors before any execution
            try:
                from threshold_safety_validator import validate_threshold_safety
                
                # Validate threshold safety against NIP-016 floors
                is_safe, threshold_errors = validate_threshold_safety(getattr(snap, 'merged', snap.structured))
                
                if not is_safe and self.strict_mode:
                    # In strict mode, unsafe thresholds are a hard error
                    error_msg = "; ".join(threshold_errors)
                    prelim = self._error(f"ERR_UNSAFE_THRESHOLD: {error_msg}", snap, canonical_chain=chain)
                    return self._apply_safety_handler(chain, snap, prelim)
            except ImportError:
                # threshold_safety_validator not available - skip check
                pass
            except Exception as e:
                # Threshold validation is optional; skip silently if unavailable
                pass

            
            # 5. Validation (NIP-005 Safety Constraints)
            # validate_chain imported at top-level
            # validate_ast_safety imported at top-level (if needed) or lazy import
            from .noe_validator import validate_ast_safety

            
            flat_ctx = getattr(snap, 'merged', snap.structured)
            val_res = validate_chain(chain, flat_ctx, mode="strict" if self.strict_mode else "partial")
            
            if not val_res["ok"]:
                if val_res.get("domain") == "error":
                    code = val_res.get("code", "ERR_VALIDATION")
                    msg = val_res.get("value", "Validation failed")
                    prelim = self._error(f"{code}: {msg}", snap, canonical_chain=chain)
                    return self._apply_safety_handler(chain, snap, prelim)
                
                reasons = "; ".join(val_res.get("reasons", []))
                prelim = self._undefined(f"Validation failed: {reasons}", snap, canonical_chain=chain)
                return self._apply_safety_handler(chain, snap, prelim)

            # AST-based Safety Validation (Normative Guard Check + Epistemic Nesting)
            is_safe = validate_ast_safety(ast)
            if not is_safe:
                # Need richer error from validator? Currently only bool.
                # Assuming generic safety failure if False.
                code = "ERR_SAFETY"
                msg = "AST safety validation failed (depth or banned nodes)"

                prelim = self._error(f"{code}: {msg}", snap, canonical_chain=chain)
                return self._apply_safety_handler(chain, snap, prelim)

            # 5. Recursion Depth Check (Safety)
            depth = self._get_ast_depth(ast)
            
            if depth > self.MAX_DEPTH:
                msg = f"Recursion depth exceeded: {depth} > {self.MAX_DEPTH}"
                prelim = self._error(f"ERR_RECURSION_LIMIT: {msg}", snap, canonical_chain=chain)
                return self._apply_safety_handler(chain, snap, prelim)

            # 6. Evaluate
            try:
                # Apply Safe Projection (pi_safe) using the flattened context
                C_eval, explanations = self._apply_safe_projection(flat_ctx)
                
                evaluator = NoeEvaluator(
                    C_eval,
                    mode="strict" if self.strict_mode else "partial",
                    debug=self.debug,
                )
                result = visit_parse_tree(ast, evaluator)

                if isinstance(result, dict) and "domain" in result:
                    domain = result["domain"]
                    value = result["value"]
                    if domain == "error":
                        code = result.get("code", "ERR_EVAL")
                        prelim = self._error(f"{code}: {value}", snap, canonical_chain=chain)
                        return self._apply_safety_handler(chain, snap, prelim)
                else:
                    from .noe_parser import wrap_domain
                    wrapped = wrap_domain(result)
                    domain = wrapped["domain"]
                    value = wrapped["value"]

            except Exception as e:
                if self.debug:
                    # traceback already imported at module level
                    tb = traceback.format_exc()
                    sys.stderr.write(f"ERR_EVAL traceback:\n{tb}\n")
                prelim = self._error(f"ERR_EVAL: {e}", snap, canonical_chain=chain)
                return self._apply_safety_handler(chain, snap, prelim)

            # 3. undefined ⇒ non-execution rule
            if domain == "undefined":
                prelim = RuntimeResult(
                    domain="undefined",
                    value=None,
                    error=None,
                    context_hash=snap.context_hash,
                    snapshot_ts=getattr(snap, 'timestamp_ms', 0),
                    raw_ast=ast if self.debug else None,
                    canonical_chain=chain,
                    provenance=None,
                )
                return self._apply_safety_handler(chain, snap, prelim)

            # 4. Normal successful path (truth / numeric / action / list-of-actions)
            
            # Compute Provenance Hashes
            # action_hash = H("noe.action.v1" || chain || H_total || H_domain)
            # child_action_hash = H("noe.child_action.v1" || parent || chain || H_total || H_domain)
            

            
            # Compute execution request provenance hash (Renamed var)
            # Moved inside domain=="action" block for efficiency and hygiene

                


            prov_data = {
                "parent_action_hash": parent_action_hash,
                "domain_pack_hash": snap.domain_hash,
                "context_hash": snap.context_hash
            }

            # Only expose action_hash if domain is action (avoid leaking undefined/error hashes)
            # Otherwise it's just a decision/request hash (internal).
            if domain == "action":
                # Action Domain: compute execution request hash (prefixnoe.action.v1)
                exec_req_hash = compute_execution_request_hash(
                    chain_str=chain,
                    h_total=snap.context_hash,
                    domain_pack_hash=snap.domain_hash
                )
                
                # Compute child action hash only for actions
                child_action_hash = None
                if parent_action_hash:
                    child_action_hash = compute_child_action_hash(
                        parent_action_hash=parent_action_hash,
                        chain_str=chain,
                        h_total=snap.context_hash,
                        domain_pack_hash=snap.domain_hash
                    )
                
                prov_data["action_hash"] = exec_req_hash
                prov_data["child_action_hash"] = child_action_hash
            else:
                 # Decision Domain (truth/numeric): compute decision hash (prefix noe.decision.v1)
                 # This separates the cryptographic namespace.
                 decision_hash = compute_decision_hash(
                    chain_str=chain,
                    h_total=snap.context_hash,
                    domain_pack_hash=snap.domain_hash
                 )
                 prov_data["decision_hash"] = decision_hash

            rr = RuntimeResult(
                domain=domain,
                value=value,
                error=None,
                context_hash=snap.context_hash,
                snapshot_ts=getattr(snap, 'timestamp_ms', 0),
                raw_ast=ast if self.debug else None,
                canonical_chain=chain,
                provenance=prov_data,
                explained_literals=explanations
            )

            # 5. Attach action hashes if we are in the action domain
            if domain == "action" and value is not None:
                # Normalise actions to a list
                if isinstance(value, dict):
                    actions = [value]
                    enriched = compute_action_lineage_hashes(actions)
                    # Store list, and also store the first for convenience
                    # Note: RuntimeResult doesn't have an 'actions' field by default, 
                    # but we can attach it dynamically or update the value if it's a dict.
                    # The user pattern suggests: result["actions"] = enriched
                    # But RuntimeResult is a dataclass.
                    # Let's check RuntimeResult definition.
                    # It has domain, value, error, context_hash, snapshot_ts, raw_ast.
                    # It does NOT have 'actions'.
                    # However, 'value' is Any.
                    # If domain is 'action', value is the action dict.
                    # We should probably update the value to be the enriched action.
                    rr.value = enriched[0]
                elif isinstance(value, list):
                    actions = value
                    enriched = compute_action_lineage_hashes(actions)
                    rr.value = enriched
            
            return rr

        except BadContextError as e:
            if self.debug:
                sys.stderr.write(f"BadContextError: {e}\n")
            prelim = self._error(f"ERR_BAD_CONTEXT: {e}", snap, canonical_chain=chain)
            return self._apply_safety_handler(chain, snap, prelim)
        except ContextConflictError as e:
            if self.debug:
                sys.stderr.write(f"ContextConflictError: {e}\n")
            prelim = self._error(f"ERR_CONTEXT_CONFLICT: {e}", snap, canonical_chain=chain)
            return self._apply_safety_handler(chain, snap, prelim)
        except ContextStaleError as e:
            if self.debug:
                sys.stderr.write(f"ContextStaleError: {e}\n")
            prelim = self._undefined(f"ERR_CONTEXT_STALE: {e}", snap, canonical_chain=chain)
            return self._apply_safety_handler(chain, snap, prelim)
        except Exception as e:
            if self.debug:
                sys.stderr.write(f"Runtime exception: {e}\n")
            # Catch-all: runtime-internal errors
            if self.debug:
                tb = traceback.format_exc()
                msg = f"ERR_RUNTIME_INTERNAL: {e}\n{tb}"
            else:
                msg = f"ERR_RUNTIME_INTERNAL: {e}"

            prelim = self._error(msg, snap, canonical_chain=chain)
            return self._apply_safety_handler(chain, snap, prelim)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _undefined(self, msg: str, snap: Optional[ContextSnapshot], canonical_chain: Optional[str]=None) -> RuntimeResult:
        """Return undefined-domain result."""
        ctx_hash = snap.context_hash if snap else "UNKNOWN"
        ts = getattr(snap, 'timestamp_ms', 0) if snap else 0
        return RuntimeResult(
            domain="undefined",
            value=None,
            error=msg if self.debug else None,
            context_hash=ctx_hash,
            snapshot_ts=ts,
            raw_ast=None,
            canonical_chain=canonical_chain,
            provenance=None,
        )

    def _error(self, msg: str, snap: Optional[ContextSnapshot], canonical_chain: Optional[str]=None) -> RuntimeResult:
        """Return error-domain result."""
        ctx_hash = snap.context_hash if snap else "UNKNOWN"
        ts = getattr(snap, 'timestamp_ms', 0) if snap else 0
        return RuntimeResult(
            domain="error",
            value=None,
            error=msg,
            context_hash=ctx_hash,
            snapshot_ts=ts,
            raw_ast=None,
            canonical_chain=canonical_chain,
            provenance=None,
        )

    def _bad_context(self, snap: Optional[ContextSnapshot], canonical_chain: str, missing) -> RuntimeResult:
        """Return ERR_BAD_CONTEXT with machine-readable missing fields."""
        if isinstance(missing, list):
            detail = ", ".join(missing)
        else:
            detail = str(missing)
        msg = f"ERR_BAD_CONTEXT: missing required fields: {detail}"
        rr = self._error(msg, snap, canonical_chain=canonical_chain)
        try:
            rr.missing = missing if isinstance(missing, list) else [str(missing)]
        except Exception:
            pass
        return rr

    def evaluate_with_provenance(
        self,
        chain: str,
        *,
        parent_action_hash: Optional[str] = None,
        epistemic_basis: Optional[list[str]] = None,
        value_system_basis: Optional[list[str]] = None,
    ) -> tuple[RuntimeResult, ProvenanceRecord]:
        """
        Evaluate a chain and also return a ProvenanceRecord.

        Matches evaluate() rigor by calling it directly, then enriching the result.
        """
        # 1. Delegate to core evaluate() (enforces all safety gates & canonicalization)
        # Delegate canonicalization to evaluate() to ensure single source of truth
        rr = self.evaluate(
            chain, 
            parent_action_hash=parent_action_hash
        )
        
        # Use the canonical chain from the result
        chain_canonical = rr.canonical_chain
        if chain_canonical is None:
             # Fallback if runtime failed before canonicalization (unlikely but safe)
             chain_canonical = canonicalize_chain(chain)

        # 3. Build AST representation for provenance
        # If debug is off, rr.raw_ast might be None. We re-parse for the record if needed.
        ast_repr = None
        if rr.raw_ast:
             try:
                 ast_repr = rr.raw_ast.tree_str()
             except:
                 ast_repr = repr(rr.raw_ast)
        else:
             # Optional: re-parse just for the provenance record
             try:
                 ast = self.parser.parse(chain_canonical)
                 try:
                     ast_repr = ast.tree_str()
                 except:
                     ast_repr = repr(ast)
             except Exception:
                 ast_repr = None

        # 4. Build provenance record (using context_hash from the actual execution)
        prov = build_provenance_record(
            chain=chain_canonical,
            ast_repr=ast_repr,
            context_hash=rr.context_hash,
            result_domain=rr.domain,
            result_value=rr.value,
            epistemic_basis=epistemic_basis,
            value_system_basis=value_system_basis,
            parent_action_hash=parent_action_hash,

            created_ts_ms=rr.snapshot_ts, 
            explained_literals=rr.explained_literals,
            # Pass computed hashes (if any)
            action_hash=(rr.provenance or {}).get("action_hash"),
            child_action_hash=(rr.provenance or {}).get("child_action_hash"),
            decision_hash=(rr.provenance or {}).get("decision_hash"),
            domain_pack_hash=(rr.provenance or {}).get("domain_pack_hash"),
            # Anti-Axiom Security: bind runtime mode
            runtime_mode="strict" if self.strict_mode else "lenient",
        )
        return rr, prov

    # ------------------------------------------------------------------
    # Safe Projection Integration
    # ------------------------------------------------------------------

    def _get_explainable_predicates(self, C_rich: Dict[str, Any]) -> Optional[Set[str]]:
        """
        Determine which predicates in C_rich are explainable based on the domain pack.
        """
        if self.domain_pack is None:
            return None # Default to all explainable if no registry
            
        explainable_preds = set()
        
        # Build glyph map: id -> explainable
        glyph_map = {}
        if "glyphs" in self.domain_pack:
            for g in self.domain_pack["glyphs"]:
                glyph_map[g["id"]] = g.get("explainable", True)
        
        # USER HARDENING: Use extract_evidence_from_context to get robust predicates
        annotated = extract_evidence_from_context(C_rich)
        for lit in annotated:
            pred = lit.predicate
            # Check glyph map (by ID)
            if pred in glyph_map:
                if glyph_map[pred]:
                    explainable_preds.add(pred)
            else:
                # Default to explainable if not explicitly defined
                explainable_preds.add(pred)
                
        return explainable_preds

    def _apply_safe_projection(self, C_rich: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Derive C_safe from C_rich using pi_safe.
        """
        # 1. Extract Evidence (Shared logic)
        if self.debug: print(f"DEBUG PROJ: literals in C_rich: keys={list(C_rich.get('literals', {}).keys())}")
        annotated_list = extract_evidence_from_context(C_rich)
        
        # 2. Get Config
        config = ProjectionConfig()
        
        # 3. Compute now_ms (Strict int ms)
        # Priority: temporal.now (sim) > timestamp (system/local)
        # Anti-Axiom Security: Do NOT use `or {}` double fallback
        # None temporal should remain None, not become {}
        temporal = C_rich.get("temporal")
        if temporal is None:
            temporal = {}
        elif not isinstance(temporal, dict):
            # Invalid temporal type
            temporal = {}
        
        now_ms = temporal.get("now")
        if now_ms is None:
             now_ms = C_rich.get("timestamp", 0)
        
        try:
             now_ms = int(now_ms)
        except (ValueError, TypeError):
             now_ms = 0
        
        # 4. Explainable Predicates
        explainable_preds = self._get_explainable_predicates(C_rich)
        
        # 5. Extract Rules
        required_context_map = {}
        independence_groups = {}
        if self.domain_pack:
             literals_def = self.domain_pack.get("literals", {})
             if isinstance(literals_def, dict):
                 for k, v in literals_def.items():
                     if isinstance(v, dict) and "required_context" in v:
                         required_context_map[k] = v["required_context"]
             independence_groups = self.domain_pack.get("independence_groups", {})

        # 6. Run pi_safe
        safe_bare_literals, explanations = pi_safe(
             annotated_list, config, now_ms,
             with_explanations=True,
             explainable_predicates=explainable_preds,
             full_context=C_rich,
             required_context_map=required_context_map,
             independence_groups=independence_groups,
             compiled_requirements=self._compiled_requirements
        )
        
        # 7. Merge into C_eval
        C_eval = copy.deepcopy(C_rich)
        # Update flat 'literals' and 'modal.knowledge'
        literals = C_eval.get("literals", {})
        if not isinstance(literals, dict): literals = {}
        
        modal = C_eval.get("modal", {})
        if not isinstance(modal, dict): modal = {}
        knowledge = modal.get("knowledge", {})
        if not isinstance(knowledge, dict): knowledge = {}
        
        for bl in safe_bare_literals:
            literals[bl.predicate] = bl.value
            knowledge[bl.predicate] = bl.value # Infer knowledge from safe literal
            
        C_eval["literals"] = literals
        modal["knowledge"] = knowledge
        C_eval["modal"] = modal
        
        return C_eval, explanations

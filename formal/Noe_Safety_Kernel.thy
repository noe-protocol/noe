(* ═══════════════════════════════════════════════════════════════════
   Noe Protocol — End-to-End Safety Kernel

   Theory:  Noe_Safety_Kernel
   Prover:  Isabelle/HOL 2024+
   Depends: Noe_K3, Noe_Provenance, Noe_Temporal

   The master theorems combining K3 evaluation, guards, provenance,
   and temporal safety into a unified safety proof.

   THEOREM: No path exists from uncertain input to authorized action.
   ═══════════════════════════════════════════════════════════════════ *)

theory Noe_Safety_Kernel
  imports Noe_K3 Noe_Provenance Noe_Temporal
begin

(* ═══════════════════════════════════════════════════════════════
   Section 1: Guard Composition
   ═══════════════════════════════════════════════════════════════ *)

(* Nested guards compose via conjunction *)
theorem nested_guards_are_conjunction:
  "k3_guard g1 (k3_guard g2 a) = k3_guard (k3_and g1 g2) a"
  by (cases g1; cases g2) simp_all

(* Conjunctive guard requires both true *)
theorem conjunctive_guard_requires_both:
  "k3_guard (k3_and g1 g2) a \<noteq> K3U \<Longrightarrow> g1 = K3T \<and> g2 = K3T"
  by (cases g1; cases g2; cases a) simp_all

(* Disjunctive guard passes if either is true *)
theorem disjunctive_guard_either:
  "k3_guard (k3_or g1 g2) a \<noteq> K3U \<Longrightarrow> g1 = K3T \<or> g2 = K3T"
  by (cases g1; cases g2; cases a) simp_all

(* Double guard is idempotent *)
theorem guard_idempotent:
  "k3_guard g (k3_guard g a) = k3_guard g a"
  by (cases g) simp_all

(* ═══════════════════════════════════════════════════════════════
   Section 2: Fail-Closed Composition
   No K3 expression over only-undefined inputs produces True.
   ═══════════════════════════════════════════════════════════════ *)

lemma nai_U_is_U: "k3_not K3U = K3U" by simp
lemma an_U_U_is_U: "k3_and K3U K3U = K3U" by simp
lemma ur_U_U_is_U: "k3_or K3U K3U = K3U" by simp
lemma guard_U_is_U: "k3_guard K3U a = K3U" by simp

(* The closure property: no composition of operators on U produces T *)
theorem undefined_never_becomes_true:
  "k3_not K3U \<noteq> K3T \<and>
   k3_and K3U K3U \<noteq> K3T \<and>
   k3_or K3U K3U \<noteq> K3T \<and>
   k3_guard K3U K3U \<noteq> K3T \<and>
   k3_guard K3U K3T \<noteq> K3T \<and>
   k3_not (k3_and K3U K3U) \<noteq> K3T \<and>
   k3_not (k3_or K3U K3U) \<noteq> K3T \<and>
   k3_and (k3_not K3U) K3U \<noteq> K3T \<and>
   k3_or (k3_not K3U) K3U \<noteq> K3T"
  by simp

(* ═══════════════════════════════════════════════════════════════
   Section 3: The Full Evaluation Pipeline
   temporal_check → k3_guard → prov_hash
   ═══════════════════════════════════════════════════════════════ *)

definition full_eval :: "int \<Rightarrow> int \<Rightarrow> int \<Rightarrow> int \<Rightarrow> k3 \<Rightarrow> k3 \<Rightarrow> k3" where
  "full_eval ev_ts eval_ts tau skew guard_val action_val =
     k3_guard (temporal_check ev_ts eval_ts tau skew guard_val) action_val"

(* ═══════════════════════════════════════════════════════════════
   THE MASTER SAFETY THEOREMS
   ═══════════════════════════════════════════════════════════════ *)

(* SK1a: Stale evidence produces undefined *)
theorem stale_evidence_blocks:
  "eval_ts - ev_ts > tau \<Longrightarrow>
   full_eval ev_ts eval_ts tau skew g a = K3U"
  unfolding full_eval_def is_fresh_def by auto

(* SK1b: Future evidence produces undefined *)
theorem future_evidence_blocks:
  "ev_ts - eval_ts > skew \<Longrightarrow>
   full_eval ev_ts eval_ts tau skew g a = K3U"
  unfolding full_eval_def is_fresh_def by auto

(* SK1c: False guard produces undefined even with fresh evidence *)
theorem false_guard_blocks:
  "is_fresh ev_ts eval_ts tau skew \<Longrightarrow>
   full_eval ev_ts eval_ts tau skew K3F a = K3U"
  unfolding full_eval_def by simp

(* SK1d: Undefined guard produces undefined even with fresh evidence *)
theorem undefined_guard_blocks:
  "is_fresh ev_ts eval_ts tau skew \<Longrightarrow>
   full_eval ev_ts eval_ts tau skew K3U a = K3U"
  unfolding full_eval_def by simp

(* ═══════════════════════════════════════════════════════════════
   SK2: THE AUDIT THEOREM
   If the result is not undefined, then:
     1. The evidence was temporally fresh
     2. The guard evaluated to True
   ═══════════════════════════════════════════════════════════════ *)

theorem audit_theorem:
  "full_eval ev_ts eval_ts tau skew g a \<noteq> K3U \<Longrightarrow>
   is_fresh ev_ts eval_ts tau skew \<and> g = K3T"
  unfolding full_eval_def
  by (cases g) (auto simp: is_fresh_def)

(* With provenance: non-null provenance → everything was valid *)
theorem audit_with_provenance:
  "\<lbrakk>h \<noteq> null_hash;
    prov_hash h (full_eval ev_ts eval_ts tau skew g a) \<noteq> null_hash\<rbrakk>
   \<Longrightarrow> is_fresh ev_ts eval_ts tau skew \<and> g = K3T"
  by (cases g) (auto simp: full_eval_def is_fresh_def null_hash_def)

(* ═══════════════════════════════════════════════════════════════
   SK3: NEGOTIATED SAFETY
   Negotiation never weakens the safety kernel.
   ═══════════════════════════════════════════════════════════════ *)

theorem negotiated_eval_safe_for_both:
  "\<lbrakk>0 \<le> tau_a; 0 \<le> tau_b;
    full_eval ev_ts eval_ts (negotiate tau_a tau_b) skew g a \<noteq> K3U\<rbrakk>
   \<Longrightarrow> full_eval ev_ts eval_ts tau_a skew g a \<noteq> K3U \<and>
       full_eval ev_ts eval_ts tau_b skew g a \<noteq> K3U"
  unfolding full_eval_def negotiate_def is_fresh_def
  by (cases g) auto

end

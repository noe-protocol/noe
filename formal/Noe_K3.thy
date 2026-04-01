(* ═══════════════════════════════════════════════════════════════════
   Noe Protocol — Formal Verification of K3 Strong Kleene Semantics

   Theory:  Noe_K3
   Prover:  Isabelle/HOL 2024
   Author:  Noe Protocol (machine-assisted)

   This theory formally verifies the three-valued logic (K3 Strong
   Kleene) that underlies Noe's evaluation semantics, as specified
   in NIP-005 and NIP-009.

   To check this file:
     1. Install Isabelle from https://isabelle.in.tum.de
     2. Open this .thy file in Isabelle/jEdit
     3. All lemmas should produce green checkmarks automatically

   Or batch-check from command line:
     isabelle build -D . -o document=false
   ═══════════════════════════════════════════════════════════════════ *)

theory Noe_K3
  imports Main
begin

(* ─── 1. K3 Domain Definition ─────────────────────────────────── *)
(* K3 has exactly three values: True, False, Undefined *)

datatype k3 = K3T | K3F | K3U

(* ─── 2. K3 Operators ─────────────────────────────────────────── *)

(* nai — Negation (NIP-005 §3.1) *)
fun k3_not :: "k3 \<Rightarrow> k3" where
  "k3_not K3T = K3F" |
  "k3_not K3F = K3T" |
  "k3_not K3U = K3U"

(* an — Conjunction, Strong Kleene (NIP-009 §2) *)
(* Key: False dominates. F \<and> U = F *)
fun k3_and :: "k3 \<Rightarrow> k3 \<Rightarrow> k3" where
  "k3_and K3T K3T = K3T" |
  "k3_and K3T K3F = K3F" |
  "k3_and K3T K3U = K3U" |
  "k3_and K3F _   = K3F" |
  "k3_and K3U K3T = K3U" |
  "k3_and K3U K3F = K3F" |
  "k3_and K3U K3U = K3U"

(* ur — Disjunction, Strong Kleene (NIP-009 §2) *)
(* Key: True dominates. T \<or> U = T *)
fun k3_or :: "k3 \<Rightarrow> k3 \<Rightarrow> k3" where
  "k3_or K3F K3F = K3F" |
  "k3_or K3F K3T = K3T" |
  "k3_or K3F K3U = K3U" |
  "k3_or K3T _   = K3T" |
  "k3_or K3U K3F = K3U" |
  "k3_or K3U K3T = K3T" |
  "k3_or K3U K3U = K3U"

(* kra — Guard (NIP-005 §4) *)
(* True passes through; everything else \<rightarrow> undefined *)
fun k3_guard :: "k3 \<Rightarrow> k3 \<Rightarrow> k3" where
  "k3_guard K3T a = a" |
  "k3_guard K3F _ = K3U" |
  "k3_guard K3U _ = K3U"


(* ═══════════════════════════════════════════════════════════════
   Section A: Negation Properties
   ═══════════════════════════════════════════════════════════════ *)

lemma nai_truth_table:
  "k3_not K3T = K3F"
  "k3_not K3F = K3T"
  "k3_not K3U = K3U"
  by simp_all

(* Double negation / involution *)
lemma nai_involution: "k3_not (k3_not p) = p"
  by (cases p) simp_all


(* ═══════════════════════════════════════════════════════════════
   Section B: Conjunction Properties
   ═══════════════════════════════════════════════════════════════ *)

(* Complete truth table *)
lemma an_truth_table:
  "k3_and K3T K3T = K3T"
  "k3_and K3T K3F = K3F"
  "k3_and K3T K3U = K3U"
  "k3_and K3F K3T = K3F"
  "k3_and K3F K3F = K3F"
  "k3_and K3F K3U = K3F"  (* Strong Kleene! *)
  "k3_and K3U K3T = K3U"
  "k3_and K3U K3F = K3F"  (* Strong Kleene! *)
  "k3_and K3U K3U = K3U"
  by simp_all

lemma an_commutative: "k3_and p q = k3_and q p"
  by (cases p; cases q) simp_all

lemma an_associative: "k3_and (k3_and p q) r = k3_and p (k3_and q r)"
  by (cases p; cases q; cases r) simp_all

lemma an_identity: "k3_and K3T p = p"
  by (cases p) simp_all

lemma an_annihilator: "k3_and K3F p = K3F"
  by (cases p) simp_all

lemma an_idempotent: "k3_and p p = p"
  by (cases p) simp_all


(* ═══════════════════════════════════════════════════════════════
   Section C: Disjunction Properties
   ═══════════════════════════════════════════════════════════════ *)

lemma ur_truth_table:
  "k3_or K3T K3T = K3T"
  "k3_or K3T K3F = K3T"
  "k3_or K3T K3U = K3T"  (* Strong Kleene! *)
  "k3_or K3F K3T = K3T"
  "k3_or K3F K3F = K3F"
  "k3_or K3F K3U = K3U"
  "k3_or K3U K3T = K3T"  (* Strong Kleene! *)
  "k3_or K3U K3F = K3U"
  "k3_or K3U K3U = K3U"
  by simp_all

lemma ur_commutative: "k3_or p q = k3_or q p"
  by (cases p; cases q) simp_all

lemma ur_associative: "k3_or (k3_or p q) r = k3_or p (k3_or q r)"
  by (cases p; cases q; cases r) simp_all

lemma ur_identity: "k3_or K3F p = p"
  by (cases p) simp_all

lemma ur_annihilator: "k3_or K3T p = K3T"
  by (cases p) simp_all

lemma ur_idempotent: "k3_or p p = p"
  by (cases p) simp_all


(* ═══════════════════════════════════════════════════════════════
   Section D: De Morgan's Laws
   These hold in K3 Strong Kleene (they do NOT hold in Weak Kleene)
   ═══════════════════════════════════════════════════════════════ *)

theorem demorgan_1: "k3_not (k3_and p q) = k3_or (k3_not p) (k3_not q)"
  by (cases p; cases q) simp_all

theorem demorgan_2: "k3_not (k3_or p q) = k3_and (k3_not p) (k3_not q)"
  by (cases p; cases q) simp_all


(* ═══════════════════════════════════════════════════════════════
   Section E: Distributivity
   ═══════════════════════════════════════════════════════════════ *)

theorem an_distributes_over_ur:
  "k3_and p (k3_or q r) = k3_or (k3_and p q) (k3_and p r)"
  by (cases p; cases q; cases r) simp_all

theorem ur_distributes_over_an:
  "k3_or p (k3_and q r) = k3_and (k3_or p q) (k3_or p r)"
  by (cases p; cases q; cases r) simp_all


(* ═══════════════════════════════════════════════════════════════
   Section F: Absorption Laws (Lattice Properties)
   ═══════════════════════════════════════════════════════════════ *)

theorem absorption_1: "k3_and p (k3_or p q) = p"
  by (cases p; cases q) simp_all

theorem absorption_2: "k3_or p (k3_and p q) = p"
  by (cases p; cases q) simp_all


(* ═══════════════════════════════════════════════════════════════
   Section G: Guard (kra) — Safety Properties
   THE foundational safety property of Noe Protocol.
   ═══════════════════════════════════════════════════════════════ *)

lemma guard_true_passes: "k3_guard K3T a = a"
  by simp

lemma guard_false_blocks: "k3_guard K3F a = K3U"
  by simp

lemma guard_undefined_blocks: "k3_guard K3U a = K3U"
  by simp

(* THE SAFETY INVARIANT:
   If the guard is not provably True, the result is always Undefined.
   This means: undefined chains NEVER produce actions. *)
theorem safety_invariant: "g \<noteq> K3T \<Longrightarrow> k3_guard g a = K3U"
  by (cases g) simp_all

(* Contrapositive: if an action occurred, the guard MUST have been True *)
theorem action_requires_proof: "k3_guard g a \<noteq> K3U \<Longrightarrow> g = K3T"
  by (cases g) simp_all

(* The guard result is always either the action value or Undefined *)
theorem guard_binary: "k3_guard g a = a \<or> k3_guard g a = K3U"
  by (cases g) simp_all


(* ═══════════════════════════════════════════════════════════════
   Section H: Strong Kleene vs Classical Logic
   K3 does NOT satisfy excluded middle or non-contradiction
   for undefined values. This is BY DESIGN.
   ═══════════════════════════════════════════════════════════════ *)

(* Excluded middle fails for Undefined *)
lemma excluded_middle_fails: "k3_or K3U (k3_not K3U) = K3U"
  by simp

(* Non-contradiction fails for Undefined *)
lemma noncontradiction_fails: "k3_and K3U (k3_not K3U) = K3U"
  by simp

(* But both hold for definite values *)
lemma excluded_middle_T: "k3_or K3T (k3_not K3T) = K3T"
  by simp

lemma excluded_middle_F: "k3_or K3F (k3_not K3F) = K3T"
  by simp

lemma noncontradiction_T: "k3_and K3T (k3_not K3T) = K3F"
  by simp

lemma noncontradiction_F: "k3_and K3F (k3_not K3F) = K3F"
  by simp


(* ═══════════════════════════════════════════════════════════════
   Section I: Strong Kleene Characterisation
   Prove that our operators match the Strong Kleene definition
   (and NOT Weak Kleene / Bochvar)
   ═══════════════════════════════════════════════════════════════ *)

(* In Weak Kleene: F \<and> U = U. We prove the opposite. *)
lemma strong_not_weak_and: "k3_and K3F K3U = K3F"
  by simp

(* In Weak Kleene: T \<or> U = U. We prove the opposite. *)
lemma strong_not_weak_or: "k3_or K3T K3U = K3T"
  by simp


(* ═══════════════════════════════════════════════════════════════
   Section J: K3 Forms a Distributive Lattice
   with ordering F < U < T
   ═══════════════════════════════════════════════════════════════ *)

(* Define the information ordering: F \<le> U \<le> T *)
fun k3_leq :: "k3 \<Rightarrow> k3 \<Rightarrow> bool" where
  "k3_leq K3F _ = True" |
  "k3_leq K3U K3F = False" |
  "k3_leq K3U _ = True" |
  "k3_leq K3T K3T = True" |
  "k3_leq K3T _ = False"

lemma k3_leq_refl: "k3_leq p p"
  by (cases p) simp_all

lemma k3_leq_antisym: "\<lbrakk>k3_leq p q; k3_leq q p\<rbrakk> \<Longrightarrow> p = q"
  by (cases p; cases q) simp_all

lemma k3_leq_trans: "\<lbrakk>k3_leq p q; k3_leq q r\<rbrakk> \<Longrightarrow> k3_leq p r"
  by (cases p; cases q; cases r) simp_all

(* an is meet (greatest lower bound) *)
lemma an_is_meet: "k3_and p q = (if k3_leq p q then p else q)"
  by (cases p; cases q) simp_all

(* ur is join (least upper bound) *)
lemma ur_is_join: "k3_or p q = (if k3_leq p q then q else p)"
  by (cases p; cases q) simp_all

end

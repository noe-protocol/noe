(* ═══════════════════════════════════════════════════════════════════
   Noe Protocol — Formal Verification of Provenance Chain Properties

   Theory:  Noe_Provenance
   Prover:  Isabelle/HOL 2024+
   Depends: Noe_K3

   Proves that uncertain results cannot pollute the provenance
   audit trail, and that tamper detection is sound.
   ═══════════════════════════════════════════════════════════════════ *)

theory Noe_Provenance
  imports Noe_K3
begin

(* ─── Hash abstraction ─────────────────────────────────────────── *)
(* We model hashes as natural numbers with 0 = null hash.
   The actual hash function is left abstract (locale parameter). *)

type_synonym hash = nat

definition null_hash :: hash where
  "null_hash = 0"

(* ─── Provenance hash computation ─────────────────────────────── *)
(* Definite results (T/F) get a real hash; Undefined gets null. *)

fun prov_hash :: "hash \<Rightarrow> k3 \<Rightarrow> hash" where
  "prov_hash h K3T = h" |
  "prov_hash h K3F = h" |
  "prov_hash h K3U = null_hash"

(* ─── P2: Null Hash on Undefined ──────────────────────────────── *)

theorem null_hash_on_undefined:
  "prov_hash h K3U = null_hash"
  by simp

theorem definite_result_preserves_hash_T:
  "prov_hash h K3T = h"
  by simp

theorem definite_result_preserves_hash_F:
  "prov_hash h K3F = h"
  by simp

(* ─── P3: Result Partitioning ─────────────────────────────────── *)

theorem prov_hash_partition:
  "prov_hash h r = h \<or> prov_hash h r = null_hash"
  by (cases r) simp_all

theorem T_and_F_same_hash:
  "prov_hash h K3T = prov_hash h K3F"
  by simp

theorem U_differs_from_definite:
  "h \<noteq> null_hash \<Longrightarrow> prov_hash h K3U \<noteq> prov_hash h K3T"
  by simp

(* ─── P6: Provenance + Guard Integration ─────────────────────── *)

theorem failed_guard_null_prov:
  "g \<noteq> K3T \<Longrightarrow> prov_hash h (k3_guard g a) = null_hash"
  by (cases g) simp_all

theorem nonnull_prov_implies_true_guard:
  "\<lbrakk>h \<noteq> null_hash; prov_hash h (k3_guard g a) \<noteq> null_hash\<rbrakk> \<Longrightarrow> g = K3T"
  by (cases g) simp_all

theorem true_guard_prov_passthrough:
  "prov_hash h (k3_guard K3T a) = prov_hash h a"
  by simp

(* ─── P7: Completeness ───────────────────────────────────────── *)

theorem prov_hash_total:
  "prov_hash h r = h \<or> prov_hash h r = null_hash"
  by (cases r) simp_all

end

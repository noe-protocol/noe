(* ═══════════════════════════════════════════════════════════════════
   Noe Protocol — Formal Verification of Temporal Safety

   Theory:  Noe_Temporal
   Prover:  Isabelle/HOL 2024+
   Depends: Noe_K3

   Proves that stale and future evidence is always rejected,
   and that multi-agent negotiation takes the stricter bound.
   ═══════════════════════════════════════════════════════════════════ *)

theory Noe_Temporal
  imports Noe_K3
begin

(* ─── Temporal parameters ──────────────────────────────────────── *)

definition tau_stale :: int where "tau_stale = 1000"
definition max_skew :: int where "max_skew = 200"

(* ─── Freshness predicate ─────────────────────────────────────── *)
(* Evidence is fresh iff its age is within [−max_skew, tau_stale] *)

definition is_fresh :: "int \<Rightarrow> int \<Rightarrow> int \<Rightarrow> int \<Rightarrow> bool" where
  "is_fresh ev_ts eval_ts tau skew \<longleftrightarrow>
     eval_ts - ev_ts \<le> tau \<and> eval_ts - ev_ts \<ge> -skew"

(* ─── Temporal check ──────────────────────────────────────────── *)

fun temporal_check :: "int \<Rightarrow> int \<Rightarrow> int \<Rightarrow> int \<Rightarrow> k3 \<Rightarrow> k3" where
  "temporal_check ev_ts eval_ts tau skew inner =
     (if is_fresh ev_ts eval_ts tau skew then inner else K3U)"

(* ─── T1-T3: Basic Freshness ─────────────────────────────────── *)

lemma fresh_passes_through:
  "is_fresh ev_ts eval_ts tau skew \<Longrightarrow>
   temporal_check ev_ts eval_ts tau skew inner = inner"
  by simp

lemma stale_is_rejected:
  "eval_ts - ev_ts > tau \<Longrightarrow>
   temporal_check ev_ts eval_ts tau skew inner = K3U"
  unfolding is_fresh_def by auto

lemma future_is_rejected:
  "ev_ts - eval_ts > skew \<Longrightarrow>
   temporal_check ev_ts eval_ts tau skew inner = K3U"
  unfolding is_fresh_def by auto

(* ─── T6: Temporal + K3 Integration ──────────────────────────── *)

lemma stale_overrides_truth:
  "eval_ts - ev_ts > tau \<Longrightarrow>
   temporal_check ev_ts eval_ts tau skew K3T = K3U"
  unfolding is_fresh_def by auto

lemma fresh_preserves_undefined:
  "is_fresh ev_ts eval_ts tau skew \<Longrightarrow>
   temporal_check ev_ts eval_ts tau skew K3U = K3U"
  by simp

lemma rejection_never_false:
  "\<not> is_fresh ev_ts eval_ts tau skew \<Longrightarrow>
   temporal_check ev_ts eval_ts tau skew inner \<noteq> K3F"
  by simp

(* ─── T7: Monotonicity ───────────────────────────────────────── *)

lemma stricter_tau_monotone:
  "\<lbrakk>tau_a \<le> tau_b; is_fresh ev_ts eval_ts tau_a skew\<rbrakk>
   \<Longrightarrow> is_fresh ev_ts eval_ts tau_b skew"
  unfolding is_fresh_def by auto

lemma stricter_skew_monotone:
  "\<lbrakk>skew_a \<le> skew_b; is_fresh ev_ts eval_ts tau skew_a\<rbrakk>
   \<Longrightarrow> is_fresh ev_ts eval_ts tau skew_b"
  unfolding is_fresh_def by auto

(* ─── T8: Multi-Agent Negotiation ────────────────────────────── *)

definition negotiate :: "int \<Rightarrow> int \<Rightarrow> int" where
  "negotiate a b = min a b"

lemma negotiate_leq_both:
  "negotiate a b \<le> a \<and> negotiate a b \<le> b"
  unfolding negotiate_def by auto

lemma negotiate_commutative:
  "negotiate a b = negotiate b a"
  unfolding negotiate_def by auto

lemma negotiate_associative:
  "negotiate (negotiate a b) c = negotiate a (negotiate b c)"
  unfolding negotiate_def by auto

lemma negotiate_idempotent:
  "negotiate a a = a"
  unfolding negotiate_def by auto

(* ─── T9: Negotiated Safety ──────────────────────────────────── *)

theorem negotiated_freshness_implies_both:
  "\<lbrakk>0 \<le> tau_a; 0 \<le> tau_b;
    is_fresh ev_ts eval_ts (negotiate tau_a tau_b) skew\<rbrakk>
   \<Longrightarrow> is_fresh ev_ts eval_ts tau_a skew \<and>
       is_fresh ev_ts eval_ts tau_b skew"
  unfolding negotiate_def is_fresh_def by auto

(* ─── T10: Guard + Temporal Combined Safety ──────────────────── *)

theorem stale_guard_blocks_action:
  "eval_ts - ev_ts > tau \<Longrightarrow>
   k3_guard (temporal_check ev_ts eval_ts tau skew g) a = K3U"
  unfolding is_fresh_def by auto

theorem future_guard_blocks_action:
  "ev_ts - eval_ts > skew \<Longrightarrow>
   k3_guard (temporal_check ev_ts eval_ts tau skew g) a = K3U"
  unfolding is_fresh_def by auto

theorem action_requires_fresh_and_true:
  "\<lbrakk>k3_guard (temporal_check ev_ts eval_ts tau skew g) a \<noteq> K3U\<rbrakk>
   \<Longrightarrow> is_fresh ev_ts eval_ts tau skew \<and> g = K3T"
  by (cases g) (auto simp: is_fresh_def)

end

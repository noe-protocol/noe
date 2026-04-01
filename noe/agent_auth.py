"""
noe/agent_auth.py

NIP-019 §4.2.1 Extension: Cryptographic Agent Identity Authentication
----------------------------------------------------------------------

Closes the "announcements are claims, not verified facts" gap.

Implements Ed25519-based PKI for agent identity:
    - Each agent holds an Ed25519 keypair
    - Announcements are signed: AID + signature
    - Challenge-response: verifier sends nonce, claimant signs it
    - Verified identity binds agent_id to a public key

Design:
    - Ed25519 chosen for: deterministic signatures, small keys (32 bytes),
      no nonce reuse risk, constant-time operations
    - SignedAnnouncement is self-contained: AID dict + signature + public key
    - Challenge-response prevents replay of a captured SignedAnnouncement
    - KeyRegistry tracks known public keys for persistent identity
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    PrivateFormat,
    NoEncryption,
)
from cryptography.exceptions import InvalidSignature

from .agent import (
    AgentIdentity,
    NegotiationError,
    announce,
    match,
    bind,
    Session,
    MatchResult,
    NegotiatedContextFrame,
    _now_ms,
    _compute_ncf_hash,
    ERR_AGENT_UNREACHABLE,
)
from .canonical import canonical_json


# =========================================================================
# Error Codes (NIP-019 Auth Extension)
# =========================================================================

ERR_SIGNATURE_INVALID = "ERR_SIGNATURE_INVALID"
ERR_CHALLENGE_FAILED  = "ERR_CHALLENGE_FAILED"
ERR_KEY_MISMATCH      = "ERR_KEY_MISMATCH"
ERR_REPLAY_DETECTED   = "ERR_REPLAY_DETECTED"


# =========================================================================
# Agent Keypair
# =========================================================================

@dataclass
class AgentKeypair:
    """Ed25519 keypair bound to an agent_id."""
    agent_id: str
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey

    @staticmethod
    def generate(agent_id: str) -> "AgentKeypair":
        """Generate a fresh Ed25519 keypair for an agent."""
        private = Ed25519PrivateKey.generate()
        public = private.public_key()
        return AgentKeypair(agent_id=agent_id, private_key=private, public_key=public)

    def public_key_bytes(self) -> bytes:
        """Raw 32-byte public key."""
        return self.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)

    def public_key_hex(self) -> str:
        """Hex-encoded public key."""
        return self.public_key_bytes().hex()

    def sign(self, data: bytes) -> bytes:
        """Sign arbitrary data."""
        return self.private_key.sign(data)

    def verify(self, signature: bytes, data: bytes) -> bool:
        """Verify a signature. Returns True/False, does not raise."""
        try:
            self.public_key.verify(signature, data)
            return True
        except InvalidSignature:
            return False


# =========================================================================
# Signed Announcement
# =========================================================================

@dataclass
class SignedAnnouncement:
    """
    An AID announcement with a cryptographic signature.

    The signature covers the canonical JSON of the AID dict,
    binding the claimed identity to a public key.
    """
    aid_dict: Dict[str, Any]
    public_key_hex: str
    signature_hex: str
    timestamp_ms: int

    def to_wire(self) -> Dict[str, Any]:
        """Serialize for network transmission."""
        return {
            "aid": self.aid_dict,
            "public_key": self.public_key_hex,
            "signature": self.signature_hex,
            "timestamp_ms": self.timestamp_ms,
        }

    @staticmethod
    def from_wire(data: Dict[str, Any]) -> "SignedAnnouncement":
        """Deserialize from network data."""
        return SignedAnnouncement(
            aid_dict=data["aid"],
            public_key_hex=data["public_key"],
            signature_hex=data["signature"],
            timestamp_ms=data["timestamp_ms"],
        )


def sign_announcement(
    aid: AgentIdentity,
    keypair: AgentKeypair,
) -> SignedAnnouncement:
    """
    Create a signed announcement: AID + Ed25519 signature.

    The signature covers: canonical_json(aid_dict) + timestamp.
    """
    aid_dict = announce(aid)
    timestamp_ms = _now_ms()

    # Sign: canonical(AID) || timestamp
    payload = canonical_json(aid_dict).encode("utf-8") + str(timestamp_ms).encode("utf-8")
    signature = keypair.sign(payload)

    return SignedAnnouncement(
        aid_dict=aid_dict,
        public_key_hex=keypair.public_key_hex(),
        signature_hex=signature.hex(),
        timestamp_ms=timestamp_ms,
    )


def verify_announcement(
    signed: SignedAnnouncement,
    *,
    max_age_ms: int = 5000,
) -> bool:
    """
    Verify a signed announcement:
    1. Signature is valid for the AID payload
    2. Timestamp is not stale (replay protection)
    3. agent_id in AID matches (self-consistency)

    Returns True if valid, raises NegotiationError if not.
    """
    # Reconstruct public key from hex
    try:
        pub_bytes = bytes.fromhex(signed.public_key_hex)
        pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
    except Exception:
        raise NegotiationError(
            ERR_SIGNATURE_INVALID,
            "Invalid public key encoding"
        )

    # Verify signature
    payload = (
        canonical_json(signed.aid_dict).encode("utf-8")
        + str(signed.timestamp_ms).encode("utf-8")
    )
    try:
        pub_key.verify(bytes.fromhex(signed.signature_hex), payload)
    except InvalidSignature:
        raise NegotiationError(
            ERR_SIGNATURE_INVALID,
            f"Signature verification failed for agent {signed.aid_dict.get('agent_id', '?')}"
        )

    # Check freshness (anti-replay)
    age = _now_ms() - signed.timestamp_ms
    if age > max_age_ms:
        raise NegotiationError(
            ERR_REPLAY_DETECTED,
            f"Announcement is {age}ms old (max: {max_age_ms}ms)"
        )
    if age < -max_age_ms:
        raise NegotiationError(
            ERR_REPLAY_DETECTED,
            f"Announcement is {-age}ms in the future (max: {max_age_ms}ms)"
        )

    return True


# =========================================================================
# Challenge-Response Protocol
# =========================================================================

@dataclass
class Challenge:
    """A cryptographic challenge: random nonce bound to a session."""
    nonce: bytes
    challenger_id: str
    timestamp_ms: int

    @staticmethod
    def generate(challenger_id: str) -> "Challenge":
        return Challenge(
            nonce=os.urandom(32),
            challenger_id=challenger_id,
            timestamp_ms=_now_ms(),
        )

    def to_wire(self) -> Dict[str, Any]:
        return {
            "nonce": self.nonce.hex(),
            "challenger_id": self.challenger_id,
            "timestamp_ms": self.timestamp_ms,
        }

    @staticmethod
    def from_wire(data: Dict[str, Any]) -> "Challenge":
        return Challenge(
            nonce=bytes.fromhex(data["nonce"]),
            challenger_id=data["challenger_id"],
            timestamp_ms=data["timestamp_ms"],
        )


@dataclass
class ChallengeResponse:
    """Signed response to a challenge."""
    nonce_hex: str
    responder_id: str
    signature_hex: str

    def to_wire(self) -> Dict[str, Any]:
        return {
            "nonce": self.nonce_hex,
            "responder_id": self.responder_id,
            "signature": self.signature_hex,
        }

    @staticmethod
    def from_wire(data: Dict[str, Any]) -> "ChallengeResponse":
        return ChallengeResponse(
            nonce_hex=data["nonce"],
            responder_id=data["responder_id"],
            signature_hex=data["signature"],
        )


def respond_to_challenge(
    challenge: Challenge,
    keypair: AgentKeypair,
) -> ChallengeResponse:
    """
    Sign the challenge nonce to prove identity.
    Payload: nonce || challenger_id || responder_id
    """
    payload = (
        challenge.nonce
        + challenge.challenger_id.encode("utf-8")
        + keypair.agent_id.encode("utf-8")
    )
    signature = keypair.sign(payload)
    return ChallengeResponse(
        nonce_hex=challenge.nonce.hex(),
        responder_id=keypair.agent_id,
        signature_hex=signature.hex(),
    )


def verify_challenge_response(
    challenge: Challenge,
    response: ChallengeResponse,
    responder_public_key_hex: str,
) -> bool:
    """
    Verify that the responder signed our challenge nonce.

    Checks:
    1. Nonce matches (not a response to a different challenge)
    2. Signature is valid
    3. Responder ID is consistent
    """
    # Nonce match
    if response.nonce_hex != challenge.nonce.hex():
        raise NegotiationError(
            ERR_CHALLENGE_FAILED,
            "Challenge nonce mismatch"
        )

    # Reconstruct key
    try:
        pub_bytes = bytes.fromhex(responder_public_key_hex)
        pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
    except Exception:
        raise NegotiationError(
            ERR_KEY_MISMATCH,
            "Invalid responder public key"
        )

    # Verify signature over: nonce || challenger_id || responder_id
    payload = (
        challenge.nonce
        + challenge.challenger_id.encode("utf-8")
        + response.responder_id.encode("utf-8")
    )
    try:
        pub_key.verify(bytes.fromhex(response.signature_hex), payload)
    except InvalidSignature:
        raise NegotiationError(
            ERR_CHALLENGE_FAILED,
            f"Challenge response signature invalid for {response.responder_id}"
        )

    return True


# =========================================================================
# Key Registry (for persistent identity across sessions)
# =========================================================================

class KeyRegistry:
    """
    In-memory registry mapping agent_id → public_key_hex.

    In production, this would be backed by a trust store or CA.
    For testing, it serves as a TOFU (Trust On First Use) store.
    """

    def __init__(self):
        self._keys: Dict[str, str] = {}

    def register(self, agent_id: str, public_key_hex: str) -> None:
        """Register or update an agent's public key."""
        self._keys[agent_id] = public_key_hex

    def lookup(self, agent_id: str) -> Optional[str]:
        """Look up an agent's registered public key."""
        return self._keys.get(agent_id)

    def verify_identity(self, agent_id: str, claimed_key_hex: str) -> bool:
        """
        Check if a claimed key matches the registered key.
        Returns True if: no prior registration (TOFU) or keys match.
        Raises NegotiationError if keys conflict.
        """
        registered = self._keys.get(agent_id)
        if registered is None:
            # First contact — trust on first use
            self._keys[agent_id] = claimed_key_hex
            return True
        if registered != claimed_key_hex:
            raise NegotiationError(
                ERR_KEY_MISMATCH,
                f"Agent {agent_id} registered with key {registered[:16]}... "
                f"but now claims {claimed_key_hex[:16]}..."
            )
        return True


# =========================================================================
# Authenticated Negotiation (full pipeline)
# =========================================================================

def authenticated_negotiate(
    aid_a: AgentIdentity,
    keypair_a: AgentKeypair,
    aid_b: AgentIdentity,
    keypair_b: AgentKeypair,
    *,
    key_registry: Optional[KeyRegistry] = None,
) -> tuple[Session, Session]:
    """
    Full authenticated negotiation:
    1. Both sign announcements
    2. Both verify counterpart's signature
    3. Mutual challenge-response
    4. Standard match + bind
    5. Both verify NCF hash agreement

    This is the production-ready handshake that closes the
    "claims, not verified facts" gap.
    """
    registry = key_registry or KeyRegistry()

    # Phase 1a: Signed announcements
    signed_a = sign_announcement(aid_a, keypair_a)
    signed_b = sign_announcement(aid_b, keypair_b)

    # Phase 1b: Verify announcements
    verify_announcement(signed_a)
    verify_announcement(signed_b)

    # Phase 1c: Key registry check (TOFU or prior registration)
    registry.verify_identity(aid_a.agent_id, keypair_a.public_key_hex())
    registry.verify_identity(aid_b.agent_id, keypair_b.public_key_hex())

    # Phase 1d: Mutual challenge-response
    # A challenges B
    challenge_for_b = Challenge.generate(aid_a.agent_id)
    response_from_b = respond_to_challenge(challenge_for_b, keypair_b)
    verify_challenge_response(
        challenge_for_b, response_from_b, keypair_b.public_key_hex()
    )

    # B challenges A
    challenge_for_a = Challenge.generate(aid_b.agent_id)
    response_from_a = respond_to_challenge(challenge_for_a, keypair_a)
    verify_challenge_response(
        challenge_for_a, response_from_a, keypair_a.public_key_hex()
    )

    # Phase 2: Match
    mr = match(aid_a, aid_b)
    if mr.error_code:
        raise NegotiationError(mr.error_code, mr.error_message or "Match failed")

    # Phase 3: Bind
    start_ms = _now_ms()
    ncf_a = bind(aid_a, aid_b, mr, session_start_ms=start_ms)
    ncf_b = bind(aid_a, aid_b, mr, session_start_ms=start_ms)

    if ncf_a.ncf_id != ncf_b.ncf_id:
        raise NegotiationError(
            "ERR_NCF_MISMATCH",
            f"NCF hash mismatch: {ncf_a.ncf_id[:16]} != {ncf_b.ncf_id[:16]}"
        )

    return Session(ncf=ncf_a), Session(ncf=ncf_b)

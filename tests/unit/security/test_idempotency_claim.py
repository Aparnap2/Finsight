from __future__ import annotations

import threading

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


def _store(engine=None):
    from shared.safety.idempotency import IdempotencyStore

    if engine is None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return IdempotencyStore(engine)


class TestIdempotencyClaimContract:
    def test_first_claim_is_fresh_replay_and_conflict(self) -> None:
        from shared.safety.idempotency import ClaimOutcome

        store = _store()
        assert store.claim("t-acme", "k1", "hash-a") is ClaimOutcome.FRESH
        assert store.claim("t-acme", "k1", "hash-a") is ClaimOutcome.REPLAY
        assert store.claim("t-acme", "k1", "hash-b") is ClaimOutcome.CONFLICT
        assert store.payload_hash_for("t-acme", "k1") == "hash-a"

    def test_conflicting_claim_does_not_overwrite(self) -> None:
        store = _store()
        store.claim("t-acme", "k2", "hash-x")
        store.claim("t-acme", "k2", "hash-y")
        assert store.payload_hash_for("t-acme", "k2") == "hash-x"

    def test_concurrent_claims_produce_exactly_one_fresh(self, tmp_path) -> None:
        from shared.safety.idempotency import ClaimOutcome

        db = tmp_path / "race.db"
        engine = create_engine(
            f"sqlite:///{db}",
            connect_args={"timeout": 15, "check_same_thread": False},
        )
        store = _store(engine)
        outcomes = []
        errors = []
        barrier = threading.Barrier(4)

        def worker(i: int) -> None:
            try:
                barrier.wait(timeout=5)
                outcomes.append(store.claim("t-acme", "race", f"hash-{i % 2}"))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert errors == []
        assert outcomes.count(ClaimOutcome.FRESH) == 1
        final = store.payload_hash_for("t-acme", "race")
        assert final in {"hash-0", "hash-1"}
        # No torn state: a second concurrent batch must be stable replays/conflicts.
        again = [store.claim("t-acme", "race", final) for _ in range(3)]
        assert again == [ClaimOutcome.REPLAY] * 3

    def test_sequential_replays_are_stable(self) -> None:
        from shared.safety.idempotency import ClaimOutcome

        store = _store()
        assert store.claim("t-acme", "k3", "h") is ClaimOutcome.FRESH
        for _ in range(3):
            assert store.claim("t-acme", "k3", "h") is ClaimOutcome.REPLAY
        assert store.claim("t-acme", "k3", "other") is ClaimOutcome.CONFLICT
        assert store.payload_hash_for("t-acme", "k3") == "h"

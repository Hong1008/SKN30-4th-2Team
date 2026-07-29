import pytest

from workshield_infra.lifecycle import Discovery, ReconcileAction, decide


@pytest.mark.parametrize(
    ("discovery", "replacement", "expected"),
    [
        (Discovery(exists=False), False, ReconcileAction.CREATE),
        (
            Discovery(exists=True, owned=True, matches=True),
            False,
            ReconcileAction.REUSE,
        ),
        (
            Discovery(exists=True, owned=True, mutable_drift=True),
            False,
            ReconcileAction.UPDATE,
        ),
        (
            Discovery(exists=True, owned=True, immutable_drift=True),
            False,
            ReconcileAction.REFUSE,
        ),
        (
            Discovery(exists=True, owned=True, immutable_drift=True),
            True,
            ReconcileAction.REPLACE,
        ),
        (Discovery(exists=True, owned=False), True, ReconcileAction.REFUSE),
        (Discovery(exists=True, ambiguous=True), True, ReconcileAction.REFUSE),
    ],
)
def test_reconcile_state_table(
    discovery: Discovery,
    replacement: bool,
    expected: ReconcileAction,
) -> None:
    assert decide(discovery, replacement_approved=replacement) is expected

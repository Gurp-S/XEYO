from engine.abort import AbortController


def test_parent_reset_does_not_revive_cancelled_descendants():
    root = AbortController()
    child = root.child()
    grandchild = child.child()
    seen = []
    grandchild.on_abort(seen.append)
    root.abort('cancel old turn')
    root.reset()
    assert not root.aborted
    assert child.aborted and grandchild.aborted
    assert child.reason == grandchild.reason == 'cancel old turn'
    assert seen == ['cancel old turn']
    assert not root.child().aborted


def test_local_child_cancel_preserves_its_reason_when_parent_later_cancels():
    root = AbortController()
    child = root.child()
    child.abort('local')
    root.abort('parent')
    assert child.reason == 'local'
    assert root.reason == 'parent'

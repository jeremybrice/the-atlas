from atlas.contracts.errors import (
    AtlasError,
    RetriableError,
    FatalError,
    PermissionDeniedError,
    ClaudeCodeError,
    SkillNotFoundError,
    SkillInvocationError,
)


def test_atlas_error_carries_correlation_id():
    err = AtlasError("something broke", correlation_id="abc-123")
    assert err.correlation_id == "abc-123"
    assert str(err) == "something broke"


def test_retriable_error_has_max_retries():
    err = RetriableError("transient failure", max_retries=5)
    assert err.max_retries == 5
    assert isinstance(err, AtlasError)


def test_fatal_error_is_not_retriable():
    err = FatalError("permanent failure")
    assert isinstance(err, AtlasError)
    assert not isinstance(err, RetriableError)


def test_permission_denied_is_fatal():
    err = PermissionDeniedError("not allowed")
    assert isinstance(err, FatalError)


def test_claude_code_error_is_retriable():
    err = ClaudeCodeError("rate limited", max_retries=2)
    assert isinstance(err, RetriableError)
    assert err.max_retries == 2


def test_cause_chaining():
    root = ClaudeCodeError("CLI timeout")
    wrapped = SkillInvocationError("skill failed", cause=root)
    assert wrapped.cause is root
    assert wrapped.correlation_id is None


def test_skill_not_found_is_fatal():
    err = SkillNotFoundError("no such skill: foo.bar")
    assert isinstance(err, FatalError)


def test_error_hierarchy_isinstance_checks():
    """Verify callers can branch on RetriableError vs FatalError."""
    retriable = SkillInvocationError("oops")
    fatal = SkillNotFoundError("gone")

    assert isinstance(retriable, RetriableError)
    assert not isinstance(retriable, FatalError)
    assert isinstance(fatal, FatalError)
    assert not isinstance(fatal, RetriableError)

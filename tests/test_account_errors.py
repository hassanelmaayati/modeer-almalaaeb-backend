"""Account error handling rolls back conflicts and preserves infrastructure errors."""
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from sqlalchemy.exc import IntegrityError

from services.accounts import commit_account


@pytest.mark.parametrize('constraint,status', [
    ('users_user_name_key', 400), ('users_email_key', 400), ('users_google_subject_key', 409), ('another_unique_constraint', 409),
])
def test_account_uniqueness_errors_are_normalized_after_rollback(constraint, status):
    original = SimpleNamespace(pgcode='23505', diag=SimpleNamespace(constraint_name=constraint))
    error = IntegrityError('test statement', {}, original)
    rolled_back = []
    def commit():
        raise error
    db = SimpleNamespace(commit=commit, rollback=lambda: rolled_back.append(True))
    with pytest.raises(HTTPException) as rejected:
        commit_account(db)
    assert rejected.value.status_code == status and rolled_back == [True]


@pytest.mark.parametrize('code', ['23514', '23503', None])
def test_non_uniqueness_database_failures_are_not_hidden_as_account_duplicates(code):
    error = IntegrityError('test statement', {}, SimpleNamespace(pgcode=code))
    rolled_back = []
    def commit():
        raise error
    db = SimpleNamespace(commit=commit, rollback=lambda: rolled_back.append(True))
    with pytest.raises(IntegrityError) as rejected:
        commit_account(db)
    assert rejected.value is error and rolled_back == [True]

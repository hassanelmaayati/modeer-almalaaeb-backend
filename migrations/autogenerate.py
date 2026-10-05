"""Schema comparison rules shared by Alembic and migration verification."""
import re

from geoalchemy2.alembic_helpers import render_item
from sqlalchemy import text


def extension_relations(connection):
    """Return relation identities owned by installed PostgreSQL extensions."""
    return set(connection.execute(text(
        "SELECT n.nspname, c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_depend d ON d.classid = 'pg_class'::regclass AND d.objid = c.oid "
        "WHERE d.refclassid = 'pg_extension'::regclass AND d.deptype = 'e'"
    )).all())


def _friend_index_signature(index, dialect):
    # PostgreSQL pretty-prints CASE expressions with extra whitespace and
    # parentheses. This index uses identifiers only, so those changes are safe
    # to normalize without masking changed expressions or predicates.
    def canonical(expression):
        sql = expression if isinstance(expression, str) else str(
            expression.compile(dialect=dialect,
                               compile_kwargs={"literal_binds": True,
                                               "include_table": False}))
        return re.sub(r"[\s()]", "", sql).lower()

    predicate = index.dialect_options["postgresql"].get("where")
    return (index.unique, tuple(canonical(value) for value in index.expressions),
            canonical(predicate) if predicate is not None else None)


def migration_options(connection=None):
    owned = extension_relations(connection) if connection is not None else set()
    default_schema = connection.dialect.default_schema_name if connection is not None else "public"

    def include_object(obj, name, kind, reflected, compare_to):
        if kind == "table" and (obj.schema or default_schema, name) in owned:
            return False
        if (connection is not None and kind == "index"
                and name == "uq_memberships_friend_pair"
                and obj.table.name == "memberships"
                and (obj.table.schema or default_schema) == "public"
                and compare_to is not None):
            if (_friend_index_signature(obj, connection.dialect)
                    == _friend_index_signature(compare_to, connection.dialect)):
                return False
        return True

    return {"include_object": include_object, "compare_type": True,
            "compare_server_default": True, "render_item": render_item}

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class every ORM model inherits from. Models are added starting Phase 2."""

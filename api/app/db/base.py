from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all identity/membership tables.

    The engine + file caches (ChainCache/FileCache) own league analysis state;
    this metadata covers only users and league memberships.
    """

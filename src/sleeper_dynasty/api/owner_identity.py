"""Explicit, league-confirmed owner links over unchanged provider data."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field, replace


@dataclass
class OwnerIdentity:
    aliases: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.aliases, dict) or not isinstance(self.names, dict):
            raise TypeError("Invalid owner identity mapping.")
        for source, target in self.aliases.items():
            if not all(isinstance(v, str) and v.strip() for v in (source, target)):
                raise ValueError("Invalid owner identity source or target.")
            if self.aliases.get(target, target) != target or target not in self.names:
                raise ValueError("Owner identity target must be a named canonical owner.")
        if any(not isinstance(n, str) or not n.strip() for n in self.names.values()):
            raise ValueError("Owner identity names must not be empty.")

    @property
    def version(self) -> str:
        if not self.aliases:
            return ""
        payload = json.dumps({"aliases": self.aliases, "names": self.names}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def resolve(self, uid: str) -> str:
        return self.aliases.get(uid, uid)


class OwnerIdentityClient:
    """Translate owner IDs, never infer identity from names or roster slots.

    Bundle fetches use ``source`` and persist its unmodified output. Translation
    happens after cache reads/writes, so a corrected mapping can rebuild history
    without losing evidence or re-fetching every sealed season.
    """

    def __init__(self, source, identity: OwnerIdentity):
        self.source = source
        self.identity = identity
        self._unlinked = set()

    def __getattr__(self, name):
        return getattr(self.source, name)

    def _resolve(self, uid):
        if uid not in self.identity.aliases:
            self._unlinked.add(uid)
        return self.identity.resolve(uid)

    def _people(self, people, name_key):
        result = {}
        for uid, person in people.items():
            target = self._resolve(uid)
            if target in result:
                raise ValueError("Two teams in the same season map to one owner; correct the owner links.")
            info = dict(person)
            if target in self.identity.names:
                info[name_key] = self.identity.names[target]
                info["franchise_name"] = self.identity.names[target]
            result[target] = info
        return result

    async def get_users(self, league_id):
        return self._people(await self.source.get_users(league_id), "display_name")

    async def get_rosters(self, league_id):
        rosters = await self.source.get_rosters(league_id)
        resolved = [self._resolve(r.owner_id) for r in rosters]
        if len(set(resolved)) != len(resolved):
            raise ValueError("Two teams in the same season map to one owner; correct the owner links.")
        return [replace(r, owner_id=uid, owner_name=self.identity.names.get(uid, r.owner_name))
                for r, uid in zip(rosters, resolved, strict=True)]

    def bundle(self, value):
        result = copy.deepcopy(value)
        for key, name_key in (("users", "display_name"), ("owners", "owner_name")):
            if key in result:
                result[key] = self._people(result[key], name_key)
        if "roster_to_user" in result:
            result["roster_to_user"] = {r: self._resolve(u) for r, u in result["roster_to_user"].items()}
            values = list(result["roster_to_user"].values())
            if len(values) != len(set(values)):
                raise ValueError("Two teams in the same season map to one owner; correct the owner links.")
        return result

    @property
    def warnings(self):
        warnings = list(getattr(self.source, "warnings", []))
        if not self._unlinked:
            warnings = [w for w in warnings if not w.startswith("Yahoo hides manager IDs.")]
        return warnings


def source_client(client):
    return client.source if isinstance(client, OwnerIdentityClient) else client


def resolve_owner_bundle(client, bundle):
    return client.bundle(bundle) if isinstance(client, OwnerIdentityClient) else bundle

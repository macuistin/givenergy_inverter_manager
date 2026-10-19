"""
system_types.py: what kind of GivEnergy system GivTCP is showing, which inverter to manage, and
whether the system has changed since it was last looked at.

GivTCP publishes one device for each inverter-like unit: a hybrid, an AC-coupled inverter, an
All-In-One, a three-phase inverter, a Gateway, an EMS. This module works on plain facts about each
device (its entity name suffixes, its `Invertor_Type` text, its GivTCP version) and never on a
serial prefix alone, because prefixes are only a hint. The facts come from
inverter/givtcp/discovery.py.

Three jobs:

  classify          the kind of one device, from what it publishes
  select_controller which device to manage when several are found, and when to ask
  SystemIdentity    a small record of kind, controller and battery modules, with a hash and a
                    plain description of what changed, so an upgrade of GivTCP that changes the
                    system is noticed and never switches the controller silently

Only hybrids and All-In-Ones have been tested on real hardware, and only one hybrid. Everything
else is classified from GivTCP's published datapoint list and tested against fixtures.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum


class SystemKind(StrEnum):
    """The kind of device GivTCP publishes."""

    HYBRID = "hybrid"
    AC_COUPLED = "ac_coupled"
    ALL_IN_ONE = "all_in_one"
    THREE_PHASE = "three_phase"
    GATEWAY = "gateway"
    EMS = "ems"
    UNKNOWN = "unknown"


# What each kind is called in the setup screens, in plain words.
KIND_LABELS: dict[SystemKind, str] = {
    SystemKind.HYBRID: "hybrid inverter",
    SystemKind.AC_COUPLED: "AC-coupled inverter",
    SystemKind.ALL_IN_ONE: "All-In-One",
    SystemKind.THREE_PHASE: "three-phase inverter",
    SystemKind.GATEWAY: "Gateway",
    SystemKind.EMS: "EMS",
    SystemKind.UNKNOWN: "inverter of an unrecognised type",
}

# The kinds tested against real hardware. The others are tested against fixtures only, and the
# setup screens and the README say so.
TESTED_ON_REAL_HARDWARE: frozenset[SystemKind] = frozenset({SystemKind.HYBRID})

# Datapoints that exist on one kind only (GivTCP's datapoint reference). The entity suffix is what
# GivTCP's own name becomes in Home Assistant.
GATEWAY_SUFFIXES = ("_gateway_state", "_gateway_mode", "_parallel_total_aio_number")
EMS_SUFFIXES = ("_plant_status", "_inverter_count")
THREE_PHASE_SUFFIXES = (
    "_grid_phase_1_voltage",
    "_load_phase_1_power",
    "_export_phase_1_power",
    "_meter_import_power",
    "_force_charge_enable",
)
# The AC-coupled and All-In-One models publish no PV string values.
PV_STRING_SUFFIX = "_pv_power_string_1"


@dataclass(frozen=True)
class Classification:
    """The kind found, why, and how sure."""

    kind: SystemKind
    evidence: tuple[str, ...]
    confidence: str  # "high" when two independent signals agree, else "medium" or "low"


def classify(suffixes: Collection[str], invertor_type: str | None) -> Classification:
    """The kind of one device from the entity suffixes it publishes and its `Invertor_Type` text.

    A datapoint that exists on one kind only decides first: a Gateway, an EMS or a three-phase
    inverter says so by what it publishes. The text GivTCP gives as the inverter type separates
    the rest. Where the text is missing or not recognised, a device with the usual power and
    charge entities is a hybrid, which is the baseline, and one without them is unknown.
    """
    present = set(suffixes)
    text = _normalised(invertor_type)
    for kind, markers in (
        (SystemKind.GATEWAY, GATEWAY_SUFFIXES),
        (SystemKind.EMS, EMS_SUFFIXES),
        (SystemKind.THREE_PHASE, THREE_PHASE_SUFFIXES),
    ):
        hits = tuple(m for m in markers if m in present)
        if hits:
            agrees = _kind_from_text(text) in (kind, None)
            evidence = (*(f"publishes {m.lstrip('_')}" for m in hits[:2]),)
            return Classification(kind, evidence, "high" if agrees and text else "medium")
    from_text = _kind_from_text(text)
    if from_text is not None:
        return Classification(from_text, (f"inverter type {invertor_type}",), "high")
    if "_pv_power" in present and ("_soc" in present or "_battery_soc" in present):
        return Classification(SystemKind.HYBRID, ("the usual power entities",), "low")
    return Classification(SystemKind.UNKNOWN, (), "low")


def _normalised(text: str | None) -> str:
    return "".join(c for c in str(text or "").lower() if c.isalnum())


def _kind_from_text(text: str) -> SystemKind | None:
    """The kind an `Invertor_Type` string names, None when it is empty or not recognised.

    Only one real value is known (`Hybrid_gen3`). The others are matched by the words GivEnergy
    uses for the models, loosely, because the exact strings were not seen.
    """
    if not text:
        return None
    for needle, kind in (
        ("gateway", SystemKind.GATEWAY),
        ("ems", SystemKind.EMS),
        ("allinone", SystemKind.ALL_IN_ONE),
        ("aio", SystemKind.ALL_IN_ONE),
        ("3ph", SystemKind.THREE_PHASE),
        ("threephase", SystemKind.THREE_PHASE),
        ("hybrid", SystemKind.HYBRID),
    ):
        if needle in text:
            return kind
    if text == "ac" or text.startswith("accoupled"):
        return SystemKind.AC_COUPLED
    return None


@dataclass(frozen=True)
class InverterFacts:
    """What the selection rules and the identity need to know about one device."""

    serial: str
    prefix: str
    kind: SystemKind
    complete: bool  # every required power entity is present
    can_schedule: bool  # every charge control entity is present
    version: str | None = None
    modules: int | None = None
    # The number of All-In-One units a Gateway says are in parallel. None when it does not say.
    parallel_units: int | None = None
    # The suffixes of the entities the plan reads and writes, for the identity hash.
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class Selection:
    """The result of the selection rules."""

    controller: InverterFacts | None
    ask: bool  # more than one device could be managed and nothing says which
    units: tuple[InverterFacts, ...] = ()  # devices behind a Gateway, read-only
    others: tuple[InverterFacts, ...] = ()  # devices found and not chosen
    note: str = ""


def select_controller(found: Sequence[InverterFacts]) -> Selection:
    """Which device to manage, following the rules for each layout.

    One device: use it. A Gateway over two or more All-In-Ones: manage the Gateway, whose units
    are information only. A Gateway over one All-In-One: manage the All-In-One. Several other
    devices: ask, because adding two inverters together would double count the house, and a
    wrong guess writes to the wrong one. Devices that are not inverters never reach this point.
    """
    devices = sorted(found, key=lambda d: d.serial)
    if not devices:
        return Selection(None, ask=False)
    if len(devices) == 1:
        return Selection(devices[0], ask=False)
    gateways = [d for d in devices if d.kind is SystemKind.GATEWAY]
    rest = [d for d in devices if d.kind is not SystemKind.GATEWAY]
    if len(gateways) == 1:
        gateway = gateways[0]
        parallel = (gateway.parallel_units or 0) >= 2 or len(rest) >= 2
        if parallel or not rest:
            return Selection(
                gateway,
                ask=False,
                units=tuple(rest),
                note="The units behind the Gateway are read-only. The Gateway is managed.",
            )
        if len(rest) == 1:
            return Selection(
                rest[0],
                ask=False,
                others=(gateway,),
                note="One All-In-One and a Gateway: the All-In-One is managed directly.",
            )
    ordered = sorted(devices, key=lambda d: (not d.complete, d.serial))
    return Selection(
        ordered[0],
        ask=True,
        others=tuple(ordered[1:]),
        note="Several inverters were found. Choose the one to manage. They are never added up.",
    )


# ── Identity ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SystemIdentity:
    """What the integration last saw of the system it manages."""

    kind: str
    controller: str  # the serial of the managed device
    modules: int | None
    version: str | None
    roles_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "controller": self.controller,
            "modules": self.modules,
            "version": self.version,
            "roles": self.roles_digest,
        }

    @classmethod
    def from_dict(cls, stored: object) -> SystemIdentity | None:
        """The identity a store holds, None when it holds nothing usable."""
        if not isinstance(stored, dict):
            return None
        kind, controller = stored.get("kind"), stored.get("controller")
        if not isinstance(kind, str) or not isinstance(controller, str) or not controller:
            return None
        modules = stored.get("modules")
        version = stored.get("version")
        return cls(
            kind,
            controller,
            modules if isinstance(modules, int) else None,
            version if isinstance(version, str) else None,
            str(stored.get("roles") or ""),
        )

    @property
    def hash(self) -> str:
        """One short value for the parts whose change needs the user's say-so."""
        raw = f"{self.kind}|{self.controller.lower()}|{self.modules}|{self.roles_digest}"
        return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:12]  # noqa: S324


def identity_of(facts: InverterFacts) -> SystemIdentity:
    """The identity of one managed device."""
    digest = hashlib.sha1(  # noqa: S324
        "|".join(sorted(facts.roles)).encode(), usedforsecurity=False
    ).hexdigest()[:12]
    return SystemIdentity(facts.kind.value, facts.serial, facts.modules, facts.version, digest)


def what_changed(old: SystemIdentity, new: SystemIdentity) -> list[str]:
    """What differs, in plain words, for the repair. Empty when the system is the same.

    A change of version alone, or of which entities a role reads, is not a different system.
    The kind, the managed device and the battery module count are.
    """
    changes: list[str] = []
    if old.kind != new.kind:
        changes.append(f"type {_label(old.kind)} to {_label(new.kind)}")
    if old.controller.lower() != new.controller.lower():
        changes.append(f"managed inverter {old.controller} to {new.controller}")
    if old.modules != new.modules:
        changes.append(f"battery modules {_count(old.modules)} to {_count(new.modules)}")
    return changes


def entities_changed(old: SystemIdentity, new: SystemIdentity) -> bool:
    """True when the set of entities the plan uses changed, without a different system."""
    return old.roles_digest != new.roles_digest


def _label(kind: str) -> str:
    try:
        return KIND_LABELS[SystemKind(kind)]
    except ValueError:
        return kind


def _count(modules: int | None) -> str:
    return "unknown" if modules is None else str(modules)

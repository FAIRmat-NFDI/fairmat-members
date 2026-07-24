#!/usr/bin/env python3
"""Generate individual Person ``*.archive.json`` files from the members CSV.

This replaces the former NOMAD parser: instead of parsing the spreadsheet
inside NOMAD, this script is run locally and the resulting archive files are
uploaded to the oasis, where NOMAD's built-in archive parser turns each file
into an editable Person entry.

The Person sections are built with the plugin's own schema classes, so all
controlled vocabularies (member type, areas, tasks, mailing lists, ...) are
validated while generating.  Rows that fail validation are reported and
skipped, never written.

Usage (from the plugin root, inside the distro environment)::

    uv run python scripts/generate_member_archives.py
    uv run python scripts/generate_member_archives.py local/members.csv -o local/archives_20260723

Input and output live under ``local/`` on purpose: the roster contains
personal data and ``local/`` is git-ignored in this public repository.

Mapping notes (agreed with the data owner)
-------------------------------------------
* ``Type`` == 'PI deputy'  ->  member_type 'PI' (they deputise for a PI; the
  'Deputy for X' note is kept in ``notes``).
* Areas are NOT stored on the top-level ``area`` field (deliberately unused:
  everyone works across several areas with no primary).  Instead every area a
  person touches is represented inside ``fairmat_roles``:
    - specific roles carry their own area (Area Leader -> its area, Deputy Area
      Leader -> its area, Task Leader / Participant -> the area of the task);
    - the union of every area letter seen across the Area Leader, Deputy Area
      Leader, Task Leader and Participant columns is computed, and for any area
      in that union NOT already covered by a specific role a
      ``role='Member', area=<that area>`` assignment is added.
* Task codes ('A1', 'G3', ...) map to the full task enum values
  ('Task A1 - Synthesis Methods', ...) derived from the schema's ``TASKS``.
* Invitation cells: 'Yes' -> invited; 'upon request' -> invited_to left empty
  with a note on the Event invitation; 'No'/blank -> not invited.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

from nomad.datamodel import EntryArchive, EntryMetadata

from fairmat_members.schema_packages.schema_package import (
    FAIRMAT_AREAS,
    TASKS,
    Affiliation,
    EventInvitation,
    ExternalProject,
    FAIRmatRoleAssignment,
    Person,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Column names (CSV header row)
# ---------------------------------------------------------------------------

COL_LAST_NAME = 'Last Name'
COL_FIRST_NAME = 'First Name'
COL_EMAIL = 'Email'
COL_AFFILIATION = 'Affiliation'
COL_AFFILIATION_ROR = 'Affiliation ROR'
COL_CITY = 'City'
COL_COUNTRY = 'Country'
COL_MEMBER_TYPE = 'Type'
COL_AREA_LEADER = 'Area Leader'
COL_DEPUTY_AL = 'Deputy Area Leader'
COL_TASK_LEADER = 'Task Leader'
COL_PARTICIPANT = 'Participant'
# The CSV 'Member' column holds FAIRmat 1 area letters for coworkers,
# collaborators and alumni (rows whose role columns are empty).  Each such
# letter is remapped to its FAIRmat 2 area (see F1_TO_F2_AREA) and assigned as
# a role='Member' entry.  The role columns above are already FAIRmat 2.
COL_MEMBER = 'Member'
COL_NOTES = 'Comment'
COL_INVITE_MEETING = 'Invitation to project meeting'
COL_INVITE_RETREAT = 'Invitation to the retreat'
COL_REIMBURSEMENT = 'Reimbursement'
COL_MAIN_MAIL = 'Main Mail'
COL_ORCID = 'ORCID'
COL_EXTERNAL_PROJECTS = 'External projects'

# ---------------------------------------------------------------------------
# Controlled vocabulary maps (lower-case key -> canonical schema value)
# ---------------------------------------------------------------------------

# CSV 'Type' -> member_type enum.  'PI deputy' -> 'PI' per data owner.
# 'External' is folded into 'Collaborator': all externals are collaborators.
MEMBER_TYPE_MAP = {
    'pi': 'PI',
    'pi deputy': 'PI',
    'coworker': 'Coworker',
    'coordinator': 'Coordinator',
    'collaborator': 'Collaborator',
    'external': 'Collaborator',
    'alumni': 'Alumni',
}

# Area letter -> full area enum value ('A' -> 'Area A - Synthesis').  Built from
# the schema so it can never drift out of sync.  The special 'FAIRmat1 Area E -
# Use Cases' entry has no single letter and is intentionally excluded here.
_AREA_BY_LETTER: dict[str, str] = {}
for _area in FAIRMAT_AREAS:
    _m = re.match(r'Area\s+([A-H])\s*-', _area)
    if _m:
        _AREA_BY_LETTER[_m.group(1)] = _area

# The legacy first-period area, resolved from the schema so the exact string
# stays in sync (used for the dissolved FAIRmat 1 Area E, see F1_TO_F2_AREA).
_USE_CASES_AREA = next((a for a in FAIRMAT_AREAS if a.startswith('FAIRmat1')), None)

# FAIRmat 1 -> FAIRmat 2 area remap for the CSV 'Member' column (data owner):
#   F1 A/B/C stay A/B/C; F1 D -> F2 E; F1 F -> F2 G; F1 G -> F2 H.
#   F1 E is dissolved in FAIRmat 2 and is mapped to the legacy 'FAIRmat1 Area E
#   - Use Cases' entry.  F2 D and F2 F are new areas with no FAIRmat 1 source.
#   F1 H has no occurrences in the data and is intentionally left unmapped (a
#   warning is emitted if it ever appears).
F1_TO_F2_AREA: dict[str, str | None] = {
    'A': _AREA_BY_LETTER.get('A'),
    'B': _AREA_BY_LETTER.get('B'),
    'C': _AREA_BY_LETTER.get('C'),
    'D': _AREA_BY_LETTER.get('E'),
    'E': _USE_CASES_AREA,
    'F': _AREA_BY_LETTER.get('G'),
    'G': _AREA_BY_LETTER.get('H'),
}

# Task code -> full task enum value ('A1' -> 'Task A1 - Synthesis Methods').
# The dash in TASKS is an en dash (U+2013); match either dash so the source
# stays robust to editing.
_TASK_BY_CODE: dict[str, str] = {}
for _task in TASKS:
    _m = re.match(r'Task\s+([A-H]\d)\s*[-–]', _task)
    if _m:
        _TASK_BY_CODE[_m.group(1)] = _task

MAIN_MAIL_MAP = {
    'pi': 'fairmat2-pi@listen.physik.hu-berlin.de',
    'coworker': 'fairmat-coworkers@listen.physik.hu-berlin.de',
    'coordinator': 'fairmat-coordinators@listen.physik.hu-berlin.de',
    'team': 'fairmat-team@listen.physik.hu-berlin.de',
    'hq': 'fairmat-hq@listen.physik.hu-berlin.de',
    # 'indiv. mail' / 'indiv. Mail' -> no mailing list (handled as unmapped).
}

REIMB_MAP = {
    'all events': 'All events',
    'requires approval': 'Requires approval',
    'no': 'No',
}

# 'Upon request of Area coordinator' is no longer an invited_to enum value; the
# nuance is captured as a note appended to the Event invitation notes instead.
INVITED_UPON_REQUEST_NOTE = 'Invited upon request of Area coordinator.'


# ---------------------------------------------------------------------------
# Cell parsing helpers
# ---------------------------------------------------------------------------


def clean(value) -> str:
    if value is None:
        return ''
    s = re.sub(r'\s+', ' ', str(value).replace('\r', ' ').strip())
    return '' if s.lower() in ('nan', 'none') else s


def split_multi(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r'[,;\n|]+', raw) if p.strip()]


def area_of_letter(letter: str) -> str | None:
    return _AREA_BY_LETTER.get(letter.strip().upper()[:1] if letter else '')


def area_of_token(token: str) -> str | None:
    """Area enum for a bare area letter ('G') or a task code ('G3')."""
    token = token.strip()
    if not token:
        return None
    return area_of_letter(token[0])


def task_of_code(code: str) -> str | None:
    return _TASK_BY_CODE.get(code.strip().upper())


def f2_area_of_f1_member(token: str) -> tuple[str | None, bool]:
    """Remap a FAIRmat 1 'Member' column letter to its FAIRmat 2 area.

    Returns (area_value, known).  `known` is False when the F1 letter is not in
    the remap table (so the caller can warn); `area_value` may still be None for
    a mapped-but-empty target.
    """
    letter = token.strip().upper()[:1] if token else ''
    if letter not in F1_TO_F2_AREA:
        return None, False
    return F1_TO_F2_AREA[letter], True


def invited_state(raw: str) -> str:
    """'yes' | 'upon_request' | 'no' for one invitation cell."""
    low = raw.strip().lower()
    if low == 'yes':
        return 'yes'
    if low.startswith('upon request'):
        return 'upon_request'
    return 'no'


def parse_invited_to(meet_raw: str, retreat_raw: str) -> tuple[str | None, bool]:
    """Combine the two invitation cells into an invited_to enum value.

    Returns (invited_to, upon_request).  'Yes' on both -> 'Both'; on one -> that
    meeting.  If neither is a plain 'Yes' but at least one is 'upon request',
    invited_to stays None and upon_request is True (the caller records the
    nuance as a note).  Otherwise (None, False).
    """
    meet = invited_state(meet_raw)
    retreat = invited_state(retreat_raw)
    if meet == 'yes' and retreat == 'yes':
        return 'Both', False
    if meet == 'yes':
        return 'Project Meeting', False
    if retreat == 'yes':
        return 'Users Meeting', False
    if 'upon_request' in (meet, retreat):
        return None, True
    return None, False


# ---------------------------------------------------------------------------
# Row -> Person
# ---------------------------------------------------------------------------


class _RoleBuilder:
    """Accumulates the fairmat_roles for one member from the CSV role columns.

    `covered_areas` are areas already tied to a concrete role; `union_areas`
    are every area letter seen at all.  After the specific roles and the Member
    column are added, any union area not yet covered becomes a `Member` entry.
    """

    def __init__(self, who: str, warnings: list[str]) -> None:
        self.who = who
        self.warnings = warnings
        self.roles: list[FAIRmatRoleAssignment] = []
        self.covered_areas: set[str] = set()
        self.union_areas: set[str] = set()

    def _add(self, role: str, area: str | None, task: str | None = None) -> None:
        self.roles.append(FAIRmatRoleAssignment(role=role, area=area, task=task))
        if area:
            self.covered_areas.add(area)
            self.union_areas.add(area)

    def add_leader(self, role: str, raw: str) -> None:
        """Area Leader / Deputy Area Leader — a bare area letter (or task code)."""
        if raw:
            self._add(role, area_of_token(raw))

    def add_tasks(self, role: str, codes: list[str]) -> None:
        """Task Leader / Participant — one or more task codes."""
        for code in codes:
            task = task_of_code(code)
            if task is None:
                self.warnings.append(f'{self.who}: unmapped {role} task code {code!r}')
            self._add(role, area_of_token(code), task)

    def add_members_from_f1(self, tokens: list[str]) -> None:
        """CSV 'Member' column: FAIRmat 1 area letters remapped to FAIRmat 2."""
        for token in tokens:
            area, known = f2_area_of_f1_member(token)
            if not known:
                self.warnings.append(
                    f'{self.who}: unmapped FAIRmat 1 Member area {token!r}'
                )
            elif area is None:
                # A recognised F1 letter that deliberately maps to no F2 area.
                self.warnings.append(
                    f'{self.who}: FAIRmat 1 Member area {token!r} has no FAIRmat 2 target'
                )
            elif area not in self.covered_areas:
                self._add('Member', area)

    def finish(self) -> list[FAIRmatRoleAssignment]:
        """Complete the union with Member entries for any uncovered area."""
        for area in sorted(self.union_areas - self.covered_areas):
            self.roles.append(FAIRmatRoleAssignment(role='Member', area=area))
        return self.roles


def build_roles(get, who: str, warnings: list[str]) -> list[FAIRmatRoleAssignment]:
    """Build the fairmat_roles list from the CSV role columns.

    Specific FAIRmat 2 roles (Area Leader / Deputy Area Leader / Task Leader /
    Participant) keep their own area; the CSV 'Member' column holds FAIRmat 1
    area letters that are remapped F1 -> F2 as role='Member'; and any area seen
    but not tied to a specific role is added as a role='Member' entry.
    """
    builder = _RoleBuilder(who, warnings)
    builder.add_leader('Area Leader', get(COL_AREA_LEADER))
    builder.add_leader('Deputy Area Leader', get(COL_DEPUTY_AL))
    builder.add_tasks('Task Leader', split_multi(get(COL_TASK_LEADER)))
    builder.add_tasks('Participant', split_multi(get(COL_PARTICIPANT)))
    builder.add_members_from_f1(split_multi(get(COL_MEMBER)))
    return builder.finish()


def build_person(row: dict, warnings: list[str]) -> tuple[Person, str]:
    """Build a validated Person from one CSV row.

    Returns (person, entry_name).  Appends non-fatal issues to `warnings`.
    Raises on schema validation errors (invalid enum values etc.).
    """
    get = lambda col: clean(row.get(col, ''))  # noqa: E731

    first_name = get(COL_FIRST_NAME)
    last_name = get(COL_LAST_NAME)
    who = f'{first_name} {last_name}'.strip()

    member_type = None
    mtype_raw = get(COL_MEMBER_TYPE)
    if mtype_raw:
        member_type = MEMBER_TYPE_MAP.get(mtype_raw.lower())
        if member_type is None:
            warnings.append(f'{who}: unmapped member type {mtype_raw!r}')

    affiliations = []
    if any(
        get(c) for c in (COL_AFFILIATION, COL_AFFILIATION_ROR, COL_CITY, COL_COUNTRY)
    ):
        affiliations = [
            Affiliation(
                institution_name=get(COL_AFFILIATION) or None,
                ror_id=get(COL_AFFILIATION_ROR) or None,
                city=get(COL_CITY) or None,
                country=get(COL_COUNTRY) or None,
            )
        ]

    fairmat_roles = build_roles(get, who, warnings)

    mailing_lists = []
    main_mail_raw = get(COL_MAIN_MAIL)
    if main_mail_raw:
        canonical = MAIN_MAIL_MAP.get(main_mail_raw.lower())
        if canonical:
            mailing_lists = [canonical]
        elif not main_mail_raw.lower().startswith('indiv'):
            # 'indiv. mail' means a personal address, not a list: skip quietly.
            warnings.append(f'{who}: unmapped Main Mail {main_mail_raw!r}')

    event_invitation = None
    invited, upon_request = parse_invited_to(
        get(COL_INVITE_MEETING), get(COL_INVITE_RETREAT)
    )
    reimb_raw = get(COL_REIMBURSEMENT)
    reimb = REIMB_MAP.get(reimb_raw.lower()) if reimb_raw else None
    if reimb_raw and reimb is None:
        warnings.append(f'{who}: unmapped reimbursement {reimb_raw!r}')
    event_notes = INVITED_UPON_REQUEST_NOTE if upon_request else None
    if invited or reimb or event_notes:
        event_invitation = EventInvitation(
            invited_to=invited, reimbursement=reimb, notes=event_notes
        )

    external_projects = [
        ExternalProject(project_name=name)
        for name in split_multi(get(COL_EXTERNAL_PROJECTS))
    ]

    person = Person(
        first_name=first_name or None,
        last_name=last_name or None,
        email=get(COL_EMAIL) or None,
        orcid=get(COL_ORCID) or None,
        member_type=member_type,
        notes=get(COL_NOTES) or None,
        affiliations=affiliations,
        fairmat_roles=fairmat_roles,
        mailing_lists=mailing_lists or None,
        event_invitation=event_invitation,
        external_projects=external_projects,
    )
    return person, who or 'FAIRmat member'


def child_filename(first_name: str, last_name: str, idx: int, used: set[str]) -> str:
    safe_last = re.sub(r'[^\w]', '_', last_name or '')[:30]
    safe_first = re.sub(r'[^\w]', '_', first_name or '')[:20]
    base = f'member_{safe_last}_{safe_first}'.strip('_') or f'member_{idx}'
    filename = f'{base}.archive.json'
    if filename in used:
        filename = f'{base}_{idx}.archive.json'
    used.add(filename)
    return filename


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def read_csv_text(path: str) -> str:
    """Read the CSV trying UTF-8 (with/without BOM) first, then Latin-1."""
    raw = Path(path).read_bytes()
    for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f'Cannot decode {path} with any supported encoding')


def main() -> int:
    argparser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    argparser.add_argument(
        'csv_file',
        nargs='?',
        default=str(REPO_ROOT / 'local' / 'members.csv'),
        help='input members CSV (default: local/members.csv)',
    )
    argparser.add_argument(
        '-o',
        '--output',
        default=str(
            REPO_ROOT / 'local' / f'archives_{date.today().strftime("%Y%m%d")}'
        ),
        help='output directory (default: local/archives_<today>)',
    )
    args = argparser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    created, skipped, errors = 0, 0, 0
    warnings: list[str] = []
    used_filenames: set[str] = set()

    csv_text = read_csv_text(args.csv_file)
    for idx, raw_row in enumerate(csv.DictReader(csv_text.splitlines()), start=1):
        row = {clean(k): v for k, v in raw_row.items() if k}
        if not (clean(row.get(COL_LAST_NAME)) or clean(row.get(COL_FIRST_NAME))):
            skipped += 1
            continue
        try:
            person, entry_name = build_person(row, warnings)
        except Exception as exc:
            errors += 1
            who = f'{clean(row.get(COL_FIRST_NAME))} {clean(row.get(COL_LAST_NAME))}'
            print(f'ERROR row {idx} ({who.strip()}): {exc}', file=sys.stderr)
            continue

        archive = EntryArchive(
            data=person, metadata=EntryMetadata(entry_name=entry_name)
        )
        filename = child_filename(
            person.first_name or '', person.last_name or '', idx, used_filenames
        )
        with open(out_dir / filename, 'w', encoding='utf-8') as out:
            json.dump(archive.m_to_dict(), out, indent=2, ensure_ascii=False)
        created += 1

    for w in warnings:
        print(f'WARNING {w}', file=sys.stderr)

    print(
        f'{created} archive files written to {out_dir} '
        f'({skipped} empty rows skipped, {errors} rows failed, '
        f'{len(warnings)} warnings)'
    )
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())

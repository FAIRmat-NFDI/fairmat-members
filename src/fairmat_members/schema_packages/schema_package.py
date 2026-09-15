from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomad.datamodel.datamodel import EntryArchive
    from structlog.stdlib import BoundLogger

from fairmat_onboarding.schema_packages.schema_package import (
    PIOnboardingQuestionnaire,
)
from nomad.config import config
from nomad.datamodel.data import ArchiveSection, Schema, UseCaseElnCategory
from nomad.datamodel.metainfo.annotations import ELNAnnotation, ELNComponentEnum
from nomad.metainfo import (
    MEnum,
    Quantity,
    SchemaPackage,
    Section,
    SubSection,
)

configuration = config.get_plugin_entry_point(
    'fairmat_members.schema_packages:schema_package_entry_point'
)

m_package = SchemaPackage()

# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

MEMBER_TYPE = MEnum(
    'PI',
    'Coworker',
    'Coordinator',
    'Collaborator',
    'Alumni',
)

FAIRMAT_ROLE_VOCAB = MEnum(
    'Area Leader',
    'Deputy Area Leader',
    'Task Leader',
    'Participant',
    'Member',
    'Area Coordinator',
    'Technical Coordinator',
    'Scientific Coordinator',
)

# Convention (previously tribal knowledge, now checked in Person.normalize):
# the 'Participant' role is used for PI-type members, while 'Member' is used
# for coworkers and collaborators.  These maps say which member_type each of
# those two roles expects; a mismatch produces a non-blocking warning, never a
# hard error (other roles such as Area Leader are unconstrained).
ROLE_EXPECTED_MEMBER_TYPES = {
    'Participant': {'PI'},
    'Member': {'Coworker', 'Collaborator'},
}

# Display order for the deduplicated `fairmat_role_terms` mirror (leadership /
# coordination roles first, then the broad Participant / Member roles).  Roles
# not listed here sort last, alphabetically.
ROLE_DISPLAY_ORDER = [
    'Area Leader',
    'Deputy Area Leader',
    'Area Coordinator',
    'Technical Coordinator',
    'Scientific Coordinator',
    'Task Leader',
    'Participant',
    'Member',
]

# Human-readable area labels, kept consistent across all FAIRmat plugins
# (fairmat-members, fairmat-onboarding, fairmat-events-form): the word 'Area',
# the letter, a ' - ' separator, then the name.  The trailing 'FAIRmat1 Area E
# - Use Cases' entry covers alumni from the first FAIRmat funding period.  An
# MEnum binds to a single quantity shape, so keep the raw values in a plain
# list and build a fresh MEnum per quantity.
FAIRMAT_AREAS = [
    'Area A - Synthesis',
    'Area B - Experiment',
    'Area C - Computation',
    'Area D - Data modeling and interoperability',
    'Area E - Digital infrastructure',
    'Area F - Enabling data-driven science',
    'Area G - Outreach',
    'Area H - Management',
    'FAIRmat1 Area E - Use Cases',
]

# All FAIRmat tasks, sorted alphabetically by task code (A1, A2, ... G3).
TASKS = [
    'Task A1 – Synthesis Methods',
    'Task A2 – Processing',
    'Task A3 – Functional Materials',
    'Task B1 – Hyperspectral Imaging',
    'Task B2 – Basic Characterization',
    'Task B3 – Time-resolved Experiments',
    'Task B4 – Multi-technique Experiments',
    'Task C1 – Ground-state and Electronic Structure',
    'Task C2 – Multi-excitations and Dynamics',
    'Task C3 – Multiscale Modeling',
    'Task D1 – Data Models and Standards',
    'Task D2 – Data Quality and Curation',
    'Task D3 – Workflows',
    'Task E1 – Infrastructure Operation and Maintenance',
    'Task E2 – Data Federation and Integration',
    'Task E3 – Experiment Control and Automation',
    'Task E4 – AI-ready Infrastructure',
    'Task F1 – Data Exploration and Integration',
    'Task F2 – Machine Learning for Characterization and Laboratory Analysis',
    'Task F3 – Benchmarking and Community Challenges',
    'Task G1 – Community Engagement',
    'Task G2 – Training',
    'Task G3 – Interconnectivity',
]

PROJECT_TYPE = MEnum(
    'CRC',
    'RTG',
    'FOR',
    'Cluster of Excellence',
    'Industry',
    'NFDI Initiative',
    'International Initiative',
    'EU Project',
    'Infrastructure Project',
    'Other',
)

# NOTE: an MEnum instance binds to a single quantity definition (its shape is
# taken from that definition), so it must NOT be shared between quantities
# with different shapes.  Keep the raw values in a plain list and construct a
# fresh MEnum per quantity.
MAILING_LISTS = [
    'fairmat-area-leaders@listen.physik.hu-berlin.de',
    'fairmat-coordinators@listen.physik.hu-berlin.de',
    'fairmat-hq@listen.physik.hu-berlin.de',
    'fairmat-team@listen.physik.hu-berlin.de',
    'fairmat-coworkers@listen.physik.hu-berlin.de',
    'fairmat2-area-a@listen.physik.hu-berlin.de',
    'fairmat2-area-b@listen.physik.hu-berlin.de',
    'fairmat2-area-c@listen.physik.hu-berlin.de',
    'fairmat2-area-d@listen.physik.hu-berlin.de',
    'fairmat2-area-e@listen.physik.hu-berlin.de',
    'fairmat2-area-f@listen.physik.hu-berlin.de',
    'fairmat2-area-g@listen.physik.hu-berlin.de',
    'fairmat2-pi@listen.physik.hu-berlin.de',
]

INVITED_TO = MEnum(
    'Project Meeting',
    'Users Meeting',
    'Both',
)

REIMBURSEMENT = MEnum(
    'All events',
    'Requires approval',
    'No',
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique_clean(values) -> list[str]:
    out: list[str] = []
    for value in values or []:
        if value is None:
            continue
        cleaned = value.strip() if isinstance(value, str) else value
        if not cleaned:
            continue
        if cleaned not in out:
            out.append(cleaned)
    return out


def _area_letter(area: str | None) -> str | None:
    """Compact letter for a FAIRmat area value.

    'Area B - Experiment' -> 'B'; the legacy 'FAIRmat1 Area E - Use Cases'
    entry -> 'E1' (kept distinct from the FAIRmat 2 'E' and sorted last).
    Returns None for anything unrecognised.
    """
    if not area:
        return None
    if area.startswith('FAIRmat1'):
        return 'E1'
    prefix = 'Area '
    if area.startswith(prefix) and len(area) > len(prefix):
        letter = area[len(prefix)]
        if letter.isalpha():
            return letter.upper()
    return None


def _ensure_url(value, base: str):
    """Return `value` as a full URL under `base`.

    A value already starting with 'http' is returned unchanged (trimmed).  A
    bare identifier (e.g. an ORCID '0009-0002-...' or a ROR id '04tavf782') is
    prefixed with `base`.  Idempotent: re-running on an already-prefixed value
    leaves it untouched, so it is safe to call on every save.  `base` must end
    with a trailing slash.
    """
    if not value:
        return value
    cleaned = value.strip() if isinstance(value, str) else value
    if not cleaned or not isinstance(cleaned, str):
        return cleaned
    if cleaned.lower().startswith('http'):
        return cleaned
    return base + cleaned.lstrip('/')


ORCID_BASE = 'https://orcid.org/'
ROR_BASE = 'https://ror.org/'


# ---------------------------------------------------------------------------
# Sub-sections
# ---------------------------------------------------------------------------


class ExpertiseTerm(ArchiveSection):
    """Search-indexable mirror of a single expertise keyword.

    The app cannot use the list-valued `expertise` quantity as a search
    quantity, so `Person.normalize` mirrors it into this repeating
    subsection with a scalar `value`.
    """

    m_def = Section(a_eln={'hide': ['value']})
    value = Quantity(type=str)


class MailingListTerm(ArchiveSection):
    """Search-indexable mirror of a single mailing list subscription."""

    m_def = Section(a_eln={'hide': ['value']})
    value = Quantity(type=MEnum(MAILING_LISTS))


class FairmatRoleTerm(ArchiveSection):
    """Deduplicated, ordered mirror of a single distinct FAIRmat role.

    A member may hold the same role (e.g. 'Participant') across several tasks,
    which makes the raw `fairmat_roles.role` list repeat that value.  The app's
    results table cannot deduplicate a column, so `Person.normalize` mirrors the
    *distinct* roles into this repeating subsection (ordered by
    `ROLE_DISPLAY_ORDER`) and the app points its 'FAIRmat role' column here.
    """

    m_def = Section(a_eln={'hide': ['value']})
    value = Quantity(type=FAIRMAT_ROLE_VOCAB)


class FairmatAreaTerm(ArchiveSection):
    """Deduplicated mirror of a single distinct area (full value).

    A member's areas live per-role inside `fairmat_roles`; the top-level `area`
    field is intentionally unused.  `Person.normalize` collects the distinct
    areas across all roles into this repeating subsection.  The value is the
    full 'Area X - Name' string, identical to the one used by
    fairmat-events-form and fairmat-onboarding, so all three plugins share one
    search facet.  The app's compact 'Area' column reads
    `FairmatAreaLetterTerm` below instead.
    """

    m_def = Section(a_eln={'hide': ['value']})
    value = Quantity(type=MEnum(FAIRMAT_AREAS), label_quantity='value')


class FairmatAreaLetterTerm(ArchiveSection):
    """Compact-letter mirror of the same areas, for the app's 'Area' column.

    'Area B - Experiment' -> 'B'; 'E1' marks the legacy
    'FAIRmat1 Area E - Use Cases' entry, kept distinct from the FAIRmat 2 'E'
    and sorted last.  Display only: filtering and dashboards use the full
    values in `FairmatAreaTerm`.
    """

    m_def = Section(a_eln={'hide': ['value']})
    value = Quantity(type=str, label_quantity='value')


class Affiliation(ArchiveSection):
    """Organizational affiliation of a FAIRmat member."""

    m_def = Section(label_quantity='institution_name')

    institution_name = Quantity(
        type=str,
        label='Institution name',
        description='Name of the institution or organization.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    department = Quantity(
        type=str,
        label='Department',
        description='Department or group within the institution.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    city = Quantity(
        type=str,
        label='City',
        description='City where the institution is located.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    country = Quantity(
        type=str,
        label='Country',
        description='Country where the institution is located.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    ror_id = Quantity(
        type=str,
        label='ROR ID',
        description=(
            'Research Organization Registry (ROR) identifier for the institution. '
            'Enter the full URL (https://ror.org/xxxxxxxxx) or just the bare id; '
            'the "https://ror.org/" prefix is added automatically. Use the launch '
            'button to open the ROR record.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.URLEditQuantity),
    )

    def normalize(self, archive, logger) -> None:
        super().normalize(archive, logger)
        self.ror_id = _ensure_url(self.ror_id, ROR_BASE)


class FAIRmatRoleAssignment(ArchiveSection):
    """A FAIRmat role held by a member within a specific area."""

    m_def = Section(label_quantity='role')

    role = Quantity(
        type=FAIRMAT_ROLE_VOCAB,
        label='Role',
        description=(
            'FAIRmat organizational role. Convention: use "Participant" for '
            'PI-type members and "Member" for coworkers and collaborators.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )

    area = Quantity(
        type=MEnum(FAIRMAT_AREAS),
        label='Area',
        description='FAIRmat area associated with this role.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )

    task = Quantity(
        type=MEnum(TASKS),
        label='Task',
        description='Specific FAIRmat task or responsibility within the area (optional).',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )


class ExternalProject(ArchiveSection):
    """An external project or collaboration a FAIRmat member is involved in."""

    m_def = Section(label_quantity='project_name')

    project_name = Quantity(
        type=str,
        label='Project name',
        description='Name of the external project or initiative.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    project_type = Quantity(
        type=PROJECT_TYPE,
        label='Project type',
        description='Type or category of the external project.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )

    role_in_project = Quantity(
        type=str,
        label='Role in project',
        description='Role or function of this person within the project.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    institution_or_partner = Quantity(
        type=str,
        label='Institution / partner',
        description='Institution or partner organization involved in this project.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    website = Quantity(
        type=str,
        label='Website',
        description='URL of the project website.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.URLEditQuantity),
    )

    notes = Quantity(
        type=str,
        label='Notes',
        description='Any additional notes about this project involvement.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )


class EventInvitation(ArchiveSection):
    """FAIRmat internal event invitation and reimbursement status for a member."""

    m_def = Section()

    invited_to = Quantity(
        type=INVITED_TO,
        label='Invited to',
        description='Which FAIRmat internal meetings this member is invited to.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )

    reimbursement = Quantity(
        type=REIMBURSEMENT,
        label='Reimbursement',
        description='Reimbursement eligibility for FAIRmat event attendance.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )

    notes = Quantity(
        type=str,
        label='Notes',
        description='Additional notes about event invitation or reimbursement.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )


# ---------------------------------------------------------------------------
# Main schema – Person
# ---------------------------------------------------------------------------


class Person(Schema):
    """
    Schema for a FAIRmat member profile.

    Captures identity, member type, expertise, institutional affiliations,
    FAIRmat organizational roles, external project involvement, and mailing
    list memberships.

    Future extensions (ORCID sync, ROR IDs, GitHub/LinkedIn
    profiles, publications, supervisor relationships, etc.) can be added as
    new quantities or subsections without breaking existing data.
    """

    m_def = Section(
        label='FAIRmat Member',
        categories=[UseCaseElnCategory],
        # NOTE: 'order' is NOT a valid section-level ELN key (it belongs under
        # 'properties'), and providing it as a stray top-level key is what broke
        # editability here while the identical events-form pattern worked.  The
        # form renders quantities in *definition* order anyway, so the field
        # order (ending with the read-only `summary`) is controlled by the order
        # the quantities are declared in this class, not by an annotation.
        a_eln={
            'hide': [
                'lab_id',
                'expertise_terms',
                'mailing_list_terms',
                'fairmat_role_terms',
                'fairmat_area_terms',
                'fairmat_area_letter_terms',
            ],
        },
    )

    # -- Identity -------------------------------------------------------------

    first_name = Quantity(
        type=str,
        label='First name',
        description='First (given) name of the member.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    last_name = Quantity(
        type=str,
        label='Last name',
        description='Last (family) name of the member.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    email = Quantity(
        type=str,
        label='Email',
        description='Primary email address of the member.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    orcid = Quantity(
        type=str,
        label='ORCID',
        default=ORCID_BASE,
        description=(
            'ORCID identifier of the member. Enter the full URL '
            '(https://orcid.org/0000-0000-0000-0000) or just the bare id; '
            'the "https://orcid.org/" prefix is added automatically. Use the '
            'launch button to open the ORCID record.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.URLEditQuantity),
    )

    onboarding_entries = Quantity(
        type=PIOnboardingQuestionnaire,
        shape=['*'],
        label='Onboarding entries',
        description=(
            'References to the PI onboarding questionnaire entries of this '
            'member. Filled automatically during processing by matching the '
            'member email against the NOMAD (Keycloak) account that created '
            'the questionnaire; additional entries can be linked manually.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.ReferenceEditQuantity),
    )

    # -- Classification -------------------------------------------------------

    member_type = Quantity(
        type=MEMBER_TYPE,
        label='Member type',
        description='Category of membership within FAIRmat.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )

    expertise = Quantity(
        type=str,
        shape=['*'],
        label='Expertise',
        description=(
            'Areas of scientific or technical expertise. '
            'Add one keyword or phrase per entry.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    # -- Subsections ----------------------------------------------------------

    affiliations = SubSection(
        section_def=Affiliation,
        label='Affiliations',
        description=(
            'Institutional affiliations of this member. '
            'Add one entry per affiliation. '
            'Future versions may resolve institution names via ROR identifiers.'
        ),
        repeats=True,
    )

    fairmat_roles = SubSection(
        section_def=FAIRmatRoleAssignment,
        label='FAIRmat roles',
        description='FAIRmat organizational roles held by this member.',
        repeats=True,
    )

    external_projects = SubSection(
        section_def=ExternalProject,
        label='External projects',
        description=(
            'External projects and collaborations this member is involved in.'
        ),
        repeats=True,
    )

    mailing_lists = Quantity(
        type=MEnum(MAILING_LISTS),
        shape=['*'],
        label='Mailing lists',
        description='FAIRmat mailing lists this member is subscribed to. Multiple selections allowed.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.AutocompleteEditQuantity),
    )

    # Hidden mirrors of the list-valued `expertise` and `mailing_lists`
    # quantities.  The scalar `value` inside these repeating subsections is
    # what the FAIRmat Members app uses for search, filtering, and columns
    # (list quantities are not allowed as app search quantities).
    expertise_terms = SubSection(section_def=ExpertiseTerm, repeats=True)
    mailing_list_terms = SubSection(section_def=MailingListTerm, repeats=True)

    # Hidden, deduplicated + ordered mirror of the distinct roles held across
    # `fairmat_roles`, so the app's 'FAIRmat role' column shows each role once
    # (e.g. a single 'Participant') instead of one entry per task.
    fairmat_role_terms = SubSection(section_def=FairmatRoleTerm, repeats=True)

    # Hidden, deduplicated mirror of the distinct areas held across
    # `fairmat_roles` (the top-level `area` field is intentionally unused).
    # Full 'Area X - Name' values, shared as one facet with the other plugins.
    fairmat_area_terms = SubSection(section_def=FairmatAreaTerm, repeats=True)

    # Hidden, deduplicated compact letters for the app's 'Area' column.
    fairmat_area_letter_terms = SubSection(
        section_def=FairmatAreaLetterTerm, repeats=True
    )

    event_invitation = SubSection(
        section_def=EventInvitation,
        label='Event invitation',
        description='Internal event invitation and reimbursement status for this member.',
    )

    notes = Quantity(
        type=str,
        label='Notes',
        description='Any additional notes about this member.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )

    # -- Auto-generated read-only summary --------------------------------------
    # Defined as the LAST quantity on purpose: this ELN form renders quantities
    # in definition order (the a_eln 'order' key is not honoured here — the GUI
    # reads a_display.order / a_eln.properties.order instead), so putting
    # `summary` last is what places it at the bottom of the overview, below
    # Notes.  It is the only non-editable field (a_display editable=False).
    summary = Quantity(
        type=str,
        label='Summary',
        description=(
            'Auto-generated, read-only overview of the most important '
            'information about this member. Rebuilt on every save.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.RichTextEditQuantity),
        a_display={'editable': False},
    )

    def _find_onboarding_entries(self, archive, logger) -> list[str]:
        """Find all PIOnboardingQuestionnaire entries created by this member.

        The member's email is resolved to a NOMAD (Keycloak) account and the
        entry index is searched for questionnaires whose main author has that
        user_id.  Runs only server-side; in client/test contexts the lookup
        is skipped silently.  Questionnaires uploaded on behalf of a member
        carry the uploader's user_id and are NOT found — link those manually
        until the schemas carry an explicit user_id quantity.
        """
        if not self.email:
            return []
        try:
            from nomad.datamodel import User
            from nomad.search import search

            user = User.get(email=self.email.strip().lower())
            if user is None or not user.user_id:
                logger.info(
                    'no NOMAD account found for member email; '
                    'onboarding entries not linked',
                    member_email=self.email,
                )
                return []

            searcher_id = None
            if archive.metadata is not None and archive.metadata.main_author:
                searcher_id = archive.metadata.main_author.user_id
            results = search(
                owner='all',
                query={
                    'section_defs.definition_qualified_name': (
                        'fairmat_onboarding.schema_packages.'
                        'schema_package.PIOnboardingQuestionnaire'
                    ),
                    'main_author.user_id': user.user_id,
                },
                user_id=searcher_id,
            )
            return [
                f'../uploads/{entry["upload_id"]}/archive/{entry["entry_id"]}#/data'
                for entry in results.data
            ]
        except Exception as exc:
            logger.info(
                'onboarding entry lookup skipped',
                member_email=self.email,
                reason=str(exc),
            )
            return []

    def normalize(self, archive: 'EntryArchive', logger: 'BoundLogger') -> None:
        super().normalize(archive, logger)

        # Normalize the ORCID to a full URL so the launch button works and the
        # stored value shows the full https://orcid.org/... address.
        self.orcid = _ensure_url(self.orcid, ORCID_BASE)

        # Link all onboarding questionnaires of this member (matched via the
        # Keycloak user_id behind the member email).  Manually added
        # references are kept; discovered ones are merged in.
        existing = {
            getattr(ref, 'm_proxy_value', None)
            for ref in (self.onboarding_entries or [])
        }
        discovered = [
            url
            for url in self._find_onboarding_entries(archive, logger)
            if url not in existing
        ]
        if discovered:
            self.onboarding_entries = list(self.onboarding_entries or []) + discovered

        # Mirror list quantities into the hidden *_terms subsections so the
        # app can search and display them via a scalar `value` path.
        self.expertise_terms = [
            ExpertiseTerm(value=v) for v in _unique_clean(self.expertise)
        ]
        self.mailing_list_terms = [
            MailingListTerm(value=v) for v in _unique_clean(self.mailing_lists)
        ]

        # Deduplicate the roles held across fairmat_roles and order them
        # (leadership roles first, then Participant/Member) so the app column
        # shows each role once instead of repeating 'Participant' per task.
        distinct_roles = _unique_clean(
            role_assignment.role for role_assignment in (self.fairmat_roles or [])
        )
        distinct_roles.sort(
            key=lambda role: (
                ROLE_DISPLAY_ORDER.index(role)
                if role in ROLE_DISPLAY_ORDER
                else len(ROLE_DISPLAY_ORDER),
                role,
            )
        )
        self.fairmat_role_terms = [
            FairmatRoleTerm(value=role) for role in distinct_roles
        ]

        # Collect the distinct areas held across all roles (top-level `area` is
        # intentionally unused).  The full values feed the shared search facet;
        # the letters feed the app's compact 'Area' column.  Both are sorted
        # alphabetically with the legacy Use Cases entry ('E1') last.
        distinct_areas = _unique_clean(
            role_assignment.area for role_assignment in (self.fairmat_roles or [])
        )
        distinct_areas.sort(key=lambda area: (area.startswith('FAIRmat1'), area))
        self.fairmat_area_terms = [
            FairmatAreaTerm(value=area) for area in distinct_areas
        ]

        distinct_area_letters = _unique_clean(
            _area_letter(area) for area in distinct_areas
        )
        distinct_area_letters.sort(key=lambda letter: (letter == 'E1', letter))
        self.fairmat_area_letter_terms = [
            FairmatAreaLetterTerm(value=letter) for letter in distinct_area_letters
        ]

        # Soft-check the Participant/Member role convention against member_type.
        # Non-blocking: a mismatch is logged as a warning (visible in the entry
        # processing log) so the data owner can fix it, but the entry is still
        # accepted.  Skipped when member_type is unset (nothing to compare).
        if self.member_type:
            for role_assignment in self.fairmat_roles or []:
                expected = ROLE_EXPECTED_MEMBER_TYPES.get(role_assignment.role)
                if expected and self.member_type not in expected:
                    logger.warning(
                        'role does not match member type by convention',
                        role=role_assignment.role,
                        member_type=self.member_type,
                        expected_member_types=sorted(expected),
                    )

        # Derive the entry name from the person's name so it stays meaningful
        # regardless of how the entry was created or edited.  Without this, a
        # GUI edit + save drops the file-provided entry_name and NOMAD falls
        # back to the raw mainfile name (e.g. 'member_Last_First.archive.json').
        display_name = ' '.join(
            part for part in (self.first_name, self.last_name) if part
        ).strip()
        if display_name and archive.metadata is not None:
            archive.metadata.entry_name = display_name

        # Build the read-only overview summary last, so it reflects every value
        # normalised above (roles, mirrors, entry name, ...).
        self.summary = self._build_summary(display_name)

    # -- Read-only overview summary -------------------------------------------
    # The summary is a nested, bulleted HTML block built from small per-section
    # helpers so no single method grows too complex.  Sections are ordered by
    # administrative relevance: contact, roles/areas (leadership first), event
    # logistics, mailing lists, affiliations, projects, then expertise/onboarding.

    _LEADERSHIP_ROLES = {'Area Leader', 'Deputy Area Leader', 'Task Leader'}

    @staticmethod
    def _esc(value) -> str:
        return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    @classmethod
    def _li(cls, label: str, value: str) -> str:
        return f'<li><b>{cls._esc(label)}:</b> {cls._esc(value)}</li>'

    @classmethod
    def _group(cls, label: str, items: list[str]) -> str:
        """A heading <li> with a nested <ul> of pre-built <li> items."""
        return f'<li><b>{cls._esc(label)}</b><ul>{"".join(items)}</ul></li>'

    def _distinct_areas(self) -> list[str]:
        return _unique_clean(r.area for r in (self.fairmat_roles or []))

    def _build_summary(self, display_name: str) -> str:
        """Assemble the read-only rich-text (HTML) overview summary."""
        header = self._summary_header(display_name)
        items: list[str] = []
        for section in (
            self._summary_contact(),
            self._summary_roles(),
            self._summary_mailing_lists(),
            self._summary_affiliations(),
            self._summary_projects(),
            self._summary_extra(),
        ):
            items.extend(section)
        return f'{header}<ul>{"".join(items)}</ul>'

    def _summary_header(self, display_name: str) -> str:
        header = f'<b>{self._esc(display_name or "(no name)")}</b>'
        if self.member_type:
            header += f' — {self._esc(self.member_type)}'
        roles = self.fairmat_roles or []
        n_lead = sum(1 for r in roles if r.role in self._LEADERSHIP_ROLES)
        stat_bits = []
        if self._distinct_areas():
            stat_bits.append(f'{len(self._distinct_areas())} area(s)')
        if roles:
            stat_bits.append(f'{len(roles)} role(s)')
        if n_lead:
            stat_bits.append(f'{n_lead} leadership role(s)')
        if stat_bits:
            header += f'<br><i>{self._esc(" · ".join(stat_bits))}</i>'
        return header

    def _summary_contact(self) -> list[str]:
        # Email is intentionally omitted from the summary.  ORCID is shown only
        # when it holds a real id, not the bare 'https://orcid.org/' default.
        items = []
        if self.orcid and self.orcid.rstrip('/') != ORCID_BASE.rstrip('/'):
            items.append(self._li('ORCID', self.orcid))
        return items

    # Roles that read naturally with "of" (leadership/ownership); everything
    # else ('Participant', 'Member', ...) reads with "in".
    _ROLE_PREPOSITION = {
        'Area Leader': 'of',
        'Deputy Area Leader': 'of',
        'Task Leader': 'of',
    }

    @classmethod
    def _role_phrase(cls, role: str | None, task: str | None) -> str | None:
        """Grammatically phrase one role, e.g. 'Task Leader of Task F1 – …',
        'Participant in Task C2 – …', or just 'Area Leader' when task-less."""
        if not role:
            return None
        if not task:
            return cls._esc(role)
        preposition = cls._ROLE_PREPOSITION.get(role, 'in')
        return f'{cls._esc(role)} {preposition} {cls._esc(task)}'

    def _summary_roles(self) -> list[str]:
        """Group the member's roles by area, nesting each role under its area:

            Area C - Computation
                - Participant in Task C2 – …
                - Participant in Task C3 – …
        """
        # Preserve first-seen area order; roles with no area go under a
        # catch-all bucket so nothing is silently dropped.
        by_area: dict[str, list[str]] = {}
        for r in self.fairmat_roles or []:
            phrase = self._role_phrase(r.role, r.task)
            if not phrase:
                continue
            key = r.area or ''
            by_area.setdefault(key, []).append(f'<li>{phrase}</li>')
        if not by_area:
            return []
        area_groups = []
        for area, role_items in by_area.items():
            label = area if area else 'No area assigned'
            area_groups.append(self._group(label, role_items))
        return [self._group('Areas and roles', area_groups)]

    def _summary_mailing_lists(self) -> list[str]:
        ml_items = [
            f'<li>{self._esc(m)}</li>' for m in _unique_clean(self.mailing_lists)
        ]
        return [self._group('Mailing lists', ml_items)] if ml_items else []

    def _summary_affiliations(self) -> list[str]:
        aff_items = []
        for aff in self.affiliations or []:
            line_bits = [
                bit
                for bit in (aff.institution_name, aff.department, aff.city, aff.country)
                if bit
            ]
            if not line_bits:
                continue
            # ROR id is intentionally omitted from the summary.
            aff_items.append(f'<li>{self._esc(", ".join(line_bits))}</li>')
        return [self._group('Affiliations', aff_items)] if aff_items else []

    def _summary_projects(self) -> list[str]:
        proj_items = []
        for proj in self.external_projects or []:
            bits = [b for b in (proj.project_name, proj.project_type) if b]
            if bits:
                proj_items.append(f'<li>{self._esc(" — ".join(bits))}</li>')
        return [self._group('External projects', proj_items)] if proj_items else []

    def _summary_extra(self) -> list[str]:
        items = []
        if self.expertise:
            items.append(
                self._li('Expertise', ', '.join(_unique_clean(self.expertise)))
            )
        n_onboarding = len(self.onboarding_entries or [])
        if n_onboarding:
            items.append(self._li('Onboarding questionnaires', str(n_onboarding)))
        return items


m_package.__init_metainfo__()

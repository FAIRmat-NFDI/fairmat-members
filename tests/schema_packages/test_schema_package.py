import os.path

from nomad.client import normalize_all, parse


def test_schema_package():
    test_file = os.path.join('tests', 'data', 'test.archive.yaml')
    entry_archive = parse(test_file)[0]
    normalize_all(entry_archive)

    data = entry_archive.data
    assert data.first_name == 'Jane'
    assert data.last_name == 'Doe'
    assert data.member_type == 'PI'
    assert data.affiliations[0].institution_name == 'HU Berlin'
    assert data.fairmat_roles[1].role == 'Area Leader'
    assert data.fairmat_roles[1].area == 'Area A - Synthesis'
    assert data.fairmat_roles[1].task == 'Task A1 – Synthesis Methods'

    # normalize() expands bare ORCID / ROR ids into full URLs so the launch
    # button works and the stored value shows the full address
    assert data.orcid == 'https://orcid.org/0009-0002-0896-320X'
    assert data.affiliations[0].ror_id == 'https://ror.org/01hcx6992'

    # normalize() derives the entry name from the person's name
    assert entry_archive.metadata.entry_name == 'Jane Doe'

    # normalize() mirrors the list quantities into the hidden, searchable
    # *_terms subsections used by the app
    assert [t.value for t in data.expertise_terms] == ['NeXus', 'FAIR data']
    assert [t.value for t in data.mailing_list_terms] == [
        'fairmat-coordinators@listen.physik.hu-berlin.de'
    ]

    # normalize() mirrors the distinct roles into fairmat_role_terms,
    # deduplicated (two 'Participant' roles collapse to one) and ordered with
    # leadership roles first, then Participant/Member
    assert [t.value for t in data.fairmat_role_terms] == [
        'Area Leader',
        'Participant',
    ]

    # normalize() mirrors the distinct areas twice: the full 'Area X - Name'
    # values feed the search facet shared with fairmat-events-form and
    # fairmat-onboarding, the compact letters feed the app's 'Area' column
    assert [t.value for t in data.fairmat_area_terms] == [
        'Area A - Synthesis',
        'Area B - Experiment',
        'Area C - Computation',
    ]
    assert [t.value for t in data.fairmat_area_letter_terms] == ['A', 'B', 'C']

    # normalize() builds a read-only rich-text overview summary with the key
    # member information, as a nested bulleted (<ul>/<li>) structure
    assert data.summary
    assert '<b>Jane Doe</b>' in data.summary
    # Email is intentionally NOT included in the summary
    assert 'jane.doe@example.com' not in data.summary
    # nested list structure and grouped sections
    assert '<ul>' in data.summary and '<li>' in data.summary
    # roles are grouped by area, nested under an 'Areas and roles' section,
    # with each area heading and grammatically phrased roles beneath it
    assert '<b>Areas and roles</b>' in data.summary
    assert '<b>Area A - Synthesis</b>' in data.summary
    assert '<b>Area C - Computation</b>' in data.summary
    # grammatically phrased, task-bound roles: 'of' for leaders, 'in' for others
    assert 'Area Leader of Task A1 – Synthesis Methods' in data.summary
    assert 'Participant in Task C1 – Ground-state and Electronic Structure' in data.summary
    assert '<b>Affiliations</b>' in data.summary
    assert '<b>Mailing lists</b>' in data.summary
    # Event invitation is intentionally NOT included in the summary
    assert 'Event invitation' not in data.summary
    # ROR id is omitted from the summary, but the affiliation itself is kept
    assert 'HU Berlin' in data.summary
    assert 'ror.org' not in data.summary
    # header stat line
    assert 'role(s)' in data.summary


def test_legacy_use_cases_area():
    """The FAIRmat 1 'Use Cases' area keeps its own letter and sorts last."""
    import logging

    from nomad.datamodel import EntryArchive

    from fairmat_members.schema_packages.schema_package import (
        FAIRmatRoleAssignment,
        Person,
    )

    person = Person(first_name='Jane', last_name='Doe')
    person.fairmat_roles = [
        FAIRmatRoleAssignment(role='Participant', area='FAIRmat1 Area E - Use Cases'),
        FAIRmatRoleAssignment(
            role='Participant', area='Area E - Digital infrastructure'
        ),
        FAIRmatRoleAssignment(role='Participant', area='Area B - Experiment'),
    ]
    person.normalize(EntryArchive(data=person), logging.getLogger(__name__))

    assert [t.value for t in person.fairmat_area_terms] == [
        'Area B - Experiment',
        'Area E - Digital infrastructure',
        'FAIRmat1 Area E - Use Cases',
    ]
    assert [t.value for t in person.fairmat_area_letter_terms] == ['B', 'E', 'E1']

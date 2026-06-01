"""catalog — domain layer.

The bibliographic side of the system. `BibliographicRecord` is the aggregate
root; everything else here (`Contributor`, `Isbn`, `Titn`) is a value object
that lives inside a record.

Holdings (`Copy`, `Branch`) live in a separate bounded context.
"""

from bibliohack.catalog.domain.contributor import Contributor, ContributorRole
from bibliohack.catalog.domain.isbn import Isbn
from bibliohack.catalog.domain.literary_profile import (
    Audience,
    LiteraryForm,
    LiteraryProfile,
    SearchScope,
    classify_literary_profile,
)
from bibliohack.catalog.domain.record import (
    BibliographicRecord,
    BibliographicRecordId,
)
from bibliohack.catalog.domain.titn import Titn

__all__ = [
    "Audience",
    "BibliographicRecord",
    "BibliographicRecordId",
    "Contributor",
    "ContributorRole",
    "Isbn",
    "LiteraryForm",
    "LiteraryProfile",
    "SearchScope",
    "Titn",
    "classify_literary_profile",
]

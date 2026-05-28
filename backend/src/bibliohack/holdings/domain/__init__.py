"""holdings — domain layer.

Physical/virtual copies of bibliographic records, grouped by branch. Copies
and branches reference records by `BibliographicRecordId` only — they don't
import the `BibliographicRecord` aggregate. The two contexts talk via ids.
"""

from bibliohack.holdings.domain.branch import Branch, BranchCode
from bibliohack.holdings.domain.copy import Copy, CopyId

__all__ = ["Branch", "BranchCode", "Copy", "CopyId"]

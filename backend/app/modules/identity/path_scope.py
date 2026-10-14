from typing import Annotated

from fastapi import Path


def validate_college_id(cid: Annotated[int, Path(gt=0, le=2**63 - 1)]) -> int:
    """Declare and validate the prefix parameter for handlers reused as college aliases."""
    return cid

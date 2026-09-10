class NotFoundError(Exception):
    """Raised by the service layer when a requested entity doesn't exist.

    Phase 3's API layer maps this to a 404 response; kept here (rather than as an
    HTTPException) so services stay usable outside a request context too.
    """

from functools import lru_cache
from .repository import PostgresRepository
from .service import CRMTools


@lru_cache
def get_tools() -> CRMTools:
    return CRMTools(PostgresRepository())

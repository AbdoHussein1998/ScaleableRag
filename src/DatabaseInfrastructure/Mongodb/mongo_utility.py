"""
Constants for MongoDB Controller.
"""
from enum import Enum


class UpdateOperation(Enum):
    """Supported MongoDB update operations for bulk updates."""
    SET = "set"
    PUSH = "push"
    PUSH_BOUNDED = "push_bounded"
    CURRENT_DATE = "current_date"
    SET_ON_INSERT = "set_on_insert"
    UNSET = "unset"
    INC = "inc"
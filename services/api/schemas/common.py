from typing import Annotated, Union
from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema

def validate_snowflake(v: Union[str, int]) -> int:
    """
    Validates that the input is a valid snowflake (integer or string).
    Returns integer for internal storage.
    """
    try:
        val = int(v)
        if val < 0:
            raise ValueError("Snowflake cannot be negative")
        return val
    except (ValueError, TypeError):
        raise ValueError(f"Invalid snowflake format: {v}")

def serialize_snowflake(v: int) -> str:
    """
    Serializes integer snowflake to string for JSON output.
    """
    return str(v)

# Custom Snowflake type
# - Validates int/str -> int
# - Serializes int -> str
# - JSON Schema type = string
Snowflake = Annotated[
    int,
    BeforeValidator(validate_snowflake),
    PlainSerializer(serialize_snowflake, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": "^[0-9]+$"}, mode="serialization"),
    WithJsonSchema({"type": "string", "pattern": "^[0-9]+$"}, mode="validation"),
]

"""Response model mapping — auto-deserialize API responses into typed objects."""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional, Type, TypeVar, get_type_hints

T = TypeVar("T")


def map_response(data: Any, model: Type[T]) -> T:
    """Deserialize a dict (or list of dicts) into a typed dataclass instance.

    Handles nested dataclasses, lists of dataclasses, and Optional fields.

    Usage::

        @dataclass
        class User:
            id: int
            name: str
            email: Optional[str] = None

        user = map_response({"id": 1, "name": "Alice"}, User)
        # → User(id=1, name="Alice", email=None)

        users = map_response([{"id": 1, "name": "Alice"}], list[User])
        # → [User(id=1, name="Alice", email=None)]

    Args:
        data: Raw dict or list from the API response.
        model: Target type (a dataclass, or list[DataclassType]).

    Returns:
        An instance of the target type.

    Raises:
        TypeError: If model is not a supported type.
        ValueError: If data cannot be mapped to the model.
    """
    origin = getattr(model, "__origin__", None)

    # Handle list[Model]
    if origin is list:
        args = getattr(model, "__args__", ())
        if not args:
            return data  # type: ignore[return-value]
        inner_type = args[0]
        if not isinstance(data, list):
            raise ValueError(
                f"Expected list for {model}, got {type(data).__name__}"
            )
        return [map_response(item, inner_type) for item in data]  # type: ignore[return-value]

    # Handle plain dataclasses
    if dataclasses.is_dataclass(model) and isinstance(model, type):
        return _map_dataclass(data, model)

    # Passthrough for built-in types
    if model in (str, int, float, bool):
        return model(data)  # type: ignore[return-value]

    # If model is dict or Any, return as-is
    return data  # type: ignore[return-value]


def map_response_list(data: list[Any], model: Type[T]) -> list[T]:
    """Convenience: map a list of dicts to a list of model instances.

    Args:
        data: List of dicts from the API response.
        model: Target dataclass type for each item.

    Returns:
        List of model instances.
    """
    return [map_response(item, model) for item in data]


def _map_dataclass(data: Any, model: Type[T]) -> T:
    """Map a dict to a dataclass, handling nested dataclasses."""
    if not isinstance(data, dict):
        raise ValueError(
            f"Cannot map {type(data).__name__} to {model.__name__}: expected dict"
        )

    hints = get_type_hints(model)
    fields = {f.name for f in dataclasses.fields(model)}
    kwargs: Dict[str, Any] = {}

    for field_name in fields:
        if field_name not in data:
            continue

        value = data[field_name]
        if value is None:
            kwargs[field_name] = None
            continue

        field_type = hints.get(field_name, Any)
        kwargs[field_name] = _coerce_value(value, field_type)

    # Include unknown keys? No — only map known fields.
    return model(**kwargs)  # type: ignore[call-arg]


def _coerce_value(value: Any, target_type: Any) -> Any:
    """Coerce a value to the target type, handling nested structures."""
    # Unwrap Optional[X] → X
    origin = getattr(target_type, "__origin__", None)
    args = getattr(target_type, "__args__", ())

    if origin is type(None):
        return value

    # Optional[X] is Union[X, None]
    if _is_optional(target_type):
        inner = _unwrap_optional(target_type)
        if value is None:
            return None
        return _coerce_value(value, inner)

    # list[X]
    if origin is list and args:
        inner_type = args[0]
        if isinstance(value, list):
            return [_coerce_value(item, inner_type) for item in value]
        return value

    # dict[K, V]
    if origin is dict:
        return value

    # Nested dataclass
    if dataclasses.is_dataclass(target_type) and isinstance(target_type, type):
        if isinstance(value, dict):
            return _map_dataclass(value, target_type)
        return value

    return value


def _is_optional(tp: Any) -> bool:
    """Check if a type is Optional[X] (i.e., Union[X, None])."""
    import typing
    origin = getattr(tp, "__origin__", None)
    if origin is typing.Union:
        args = getattr(tp, "__args__", ())
        return type(None) in args
    return False


def _unwrap_optional(tp: Any) -> Any:
    """Extract X from Optional[X]."""
    args = getattr(tp, "__args__", ())
    non_none = [a for a in args if a is not type(None)]
    return non_none[0] if non_none else type(None)

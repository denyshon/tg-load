def deep_merge(base: dict, override: dict) -> dict:
    """Returns `base`, overriding non-dict keys present in `override` with the values from `override`. Nested dicts are merged recursively."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key] = deep_merge(base[key], value)
        else:
            base[key] = value
    return base

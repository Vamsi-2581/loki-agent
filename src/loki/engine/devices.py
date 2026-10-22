"""Mobile device emulation: friendly aliases resolved against Playwright's device catalog."""

from difflib import get_close_matches
import re

DEVICE_ALIASES = {
    "iphone": "iPhone 17",
    "iphone-15": "iPhone 15",
    "iphone15": "iPhone 15",
    "iphone-15-pro": "iPhone 15 Pro",
    "iphone-16": "iPhone 16",
    "iphone16": "iPhone 16",
    "iphone-16-pro": "iPhone 16 Pro",
    "iphone16pro": "iPhone 16 Pro",
    "iphone-17": "iPhone 17",
    "iphone17": "iPhone 17",
    "iphone-17-pro": "iPhone 17 Pro",
    "iphone17pro": "iPhone 17 Pro",
    "iphone-14": "iPhone 14",
    "iphone14": "iPhone 14",
    "iphone-13": "iPhone 13",
    "iphone13": "iPhone 13",
    "iphone-se": "iPhone SE",
    "pixel": "Pixel 10",
    "pixel-7": "Pixel 7",
    "pixel7": "Pixel 7",
    "pixel-8": "Pixel 8",
    "pixel-9": "Pixel 9",
    "pixel-10": "Pixel 10",
    "pixel10": "Pixel 10",
    "ipad": "iPad Pro 11",
    "ipad-pro": "iPad Pro 11",
    "ipad-mini": "iPad Mini",
    "galaxy-s24": "Galaxy S24",
    "galaxy-z-fold-7": "Galaxy Z Fold 7",
    "galaxy-z-flip-7": "Galaxy Z Flip 7",
    "galaxy": "Galaxy S24",
}


def resolve_device(
    device_name: str | None,
    orientation: str = "portrait",
    devices: dict | None = None,
) -> tuple[str | None, dict | None]:
    """Resolves friendly device aliases (e.g. 'iphone-15', 'pixel-7') to Playwright device descriptors."""
    if not device_name or not devices:
        return None, None

    clean_name = device_name.strip()
    is_landscape = orientation.lower() == "landscape"
    target = DEVICE_ALIASES.get(clean_name.lower(), clean_name)

    # Check for landscape variant directly in devices catalog
    if is_landscape:
        landscape_candidate = f"{target} landscape"
        if landscape_candidate in devices:
            return landscape_candidate, dict(devices[landscape_candidate])

    # Direct match in devices catalog
    if target in devices:
        desc = dict(devices[target])
        if is_landscape and "viewport" in desc:
            vp = desc["viewport"]
            desc["viewport"] = {
                "width": max(vp["width"], vp["height"]),
                "height": min(vp["width"], vp["height"]),
            }
        return target, desc

    # Case-insensitive substring lookup
    for key, val in devices.items():
        if target.lower() in key.lower():
            if is_landscape and "landscape" in key.lower():
                return key, dict(val)
            elif not is_landscape and "landscape" not in key.lower():
                return key, dict(val)

    return None, None


def suggest_device_names(device_name: str, devices: dict | None = None, limit: int = 3) -> list[str]:
    """Suggest supported aliases or Playwright device names for an unknown device."""
    if limit <= 0 or not device_name.strip():
        return []

    names_by_normalized: dict[str, str] = {}

    def add_name(name: str) -> None:
        normalized = re.sub(r"[^a-z0-9]", "", name.lower())
        if not normalized:
            return
        current = names_by_normalized.get(normalized)
        if current is None or ("-" in name and "-" not in current):
            names_by_normalized[normalized] = name

    for name in DEVICE_ALIASES:
        add_name(name)
    for name in DEVICE_ALIASES.values():
        add_name(name)
    for name in devices or {}:
        add_name(name)

    normalized_input = re.sub(r"[^a-z0-9]", "", device_name.lower())
    if not normalized_input or normalized_input in names_by_normalized:
        return []

    closest = get_close_matches(normalized_input, list(names_by_normalized), n=limit * 3, cutoff=0.5)
    suggestions: list[str] = []
    seen_devices: set[str] = set()
    for normalized_name in closest:
        name = names_by_normalized[normalized_name]
        resolved_name = DEVICE_ALIASES.get(name.lower(), name)
        normalized_device = re.sub(r"[^a-z0-9]", "", resolved_name.lower())
        if normalized_device in seen_devices:
            continue
        seen_devices.add(normalized_device)
        suggestions.append(name)
        if len(suggestions) == limit:
            break
    return suggestions

"""Measurement transformations shared by live plotters."""


def process_ivt(payload, kind):
    """Append current density and power to raw I-V-time measurement rows."""
    data = payload["data"]
    area = payload["pixel"]["area"]
    processed = []
    for element in data:
        current_density = element[1] * 1000 / area
        power = element[0] * current_density
        processed.append(tuple(element + [current_density, power]))
    return processed

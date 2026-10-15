import dataclasses
import hashlib
import json
from datetime import date, datetime


def fingerprint(value):
    def normalized(item):
        if dataclasses.is_dataclass(item):
            return normalized(dataclasses.asdict(item))
        if isinstance(item, dict):
            return sorted((str(key), normalized(child)) for key, child in item.items())
        if isinstance(item, (set, frozenset)):
            return sorted(normalized(child) for child in item)
        if isinstance(item, (list, tuple)):
            return [normalized(child) for child in item]
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        return item

    return hashlib.sha256(json.dumps(normalized(value), ensure_ascii=False).encode()).hexdigest()

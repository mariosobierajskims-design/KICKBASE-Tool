from typing import Any, Iterable, Sequence


def pick(d: dict, *keys: str, default: Any = None) -> Any:
    """Return the first present, non-None value among several candidate key names.

    The unofficial Kickbase v4 API is not fully documented with response examples,
    so field names are looked up defensively through a list of plausible aliases
    instead of a single hard-coded key.
    """
    if not isinstance(d, dict):
        return default
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


def pick_nested(d: dict, *paths: Sequence[str], default: Any = None) -> Any:
    for path in paths:
        cur: Any = d
        ok = True
        for part in path:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return default


def as_list(data: Any, *keys: str) -> list:
    """Kickbase list endpoints sometimes wrap the array in an object under a
    varying key (e.g. "players", "it", "pl") and sometimes return a bare list."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        found = pick(data, *keys)
        if isinstance(found, list):
            return found
        for value in data.values():
            if isinstance(value, list):
                return value
    return []


def rank_with_ties(values: dict, higher_is_better: bool) -> dict:
    """Rank a {id: value} mapping, 1 = best. Ties share the average rank.
    Missing (None) values get the worst possible rank so incomplete data is
    penalized instead of silently ignored.
    """
    n = len(values)
    present = {k: v for k, v in values.items() if v is not None}
    ranks: dict = {}
    if present:
        ordered = sorted(present.items(), key=lambda kv: kv[1], reverse=higher_is_better)
        i = 0
        while i < len(ordered):
            j = i
            while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
                j += 1
            avg_rank = (i + 1 + j + 1) / 2
            for k in range(i, j + 1):
                ranks[ordered[k][0]] = avg_rank
            i = j + 1
    for key in values:
        if key not in ranks:
            ranks[key] = float(n)
    return ranks


def mean(values: Iterable[float]):
    values = list(values)
    if not values:
        return None
    return sum(values) / len(values)

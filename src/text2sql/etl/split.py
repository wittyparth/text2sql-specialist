"""Stage 07 + sampling: split by domain, build the frozen eval/val sets, sample the training mix."""

import random
from collections import defaultdict

from .config import Config
from .records import Record


class SplitError(AssertionError):
    pass


def split_domains(domains: list[str], n_test: int, n_val: int, seed: int) -> dict[str, list[str]]:
    picked = random.Random(seed).sample(sorted(domains), n_test + n_val)
    test, val = picked[:n_test], picked[n_test:]
    train = sorted(set(domains) - set(picked))
    return {"test_heldout": sorted(test), "val": sorted(val), "train": train}


def assign_splits(records: list[Record], cfg: Config) -> dict[str, list[str]]:
    gretel_domains = sorted({r.domain for r in records if r.source == "gretel"})
    if len(gretel_domains) < cfg.split.test_domains + cfg.split.val_domains + 1:
        raise SplitError(f"only {len(gretel_domains)} domains, not enough to split")
    plan = split_domains(gretel_domains, cfg.split.test_domains, cfg.split.val_domains, cfg.seed)
    lookup = {d: s for s, doms in plan.items() for d in doms}
    for rec in records:
        if rec.status != "kept":
            continue
        rec.split = "train" if rec.source == "sqlcc" else lookup[rec.domain]
    assert_disjoint(plan)
    return plan


def assert_disjoint(plan: dict[str, list[str]]) -> None:
    for a, b in (("train", "test_heldout"), ("train", "val"), ("val", "test_heldout")):
        shared = set(plan[a]) & set(plan[b])
        if shared:
            raise SplitError(f"domains in both {a} and {b}: {sorted(shared)}")


def allocate_weighted(
    weights: dict[str, float], available: dict[str, int], total: int, caps: dict[str, int]
) -> dict[str, int]:
    """Fill a quota by class weight, redistributing whatever a thin class can't supply."""
    alloc = dict.fromkeys(available, 0)
    while sum(alloc.values()) < total:
        room = {
            c: min(available[c], caps.get(c, total)) - alloc[c]
            for c in available
            if weights.get(c, 0) > 0
        }
        room = {c: r for c, r in room.items() if r > 0}
        if not room:
            break
        left = total - sum(alloc.values())
        wsum = sum(weights[c] for c in room)
        gave = 0
        for c in sorted(room):
            give = min(room[c], max(1, int(left * weights[c] / wsum)))
            give = min(give, left - gave)
            alloc[c] += give
            gave += give
            if gave >= left:
                break
    return alloc


def allocate_stratified(available: dict[str, int], total: int, floor: int) -> dict[str, int]:
    """Proportional allocation with a per-class floor so rare classes stay reportable."""
    alloc = {c: min(n, floor) for c, n in available.items()}
    left = total - sum(alloc.values())
    spare = {c: available[c] - alloc[c] for c in available}
    pool = sum(spare.values())
    if left <= 0 or pool == 0:
        return alloc
    extra = {c: min(spare[c], int(left * spare[c] / pool)) for c in sorted(spare)}
    for c in sorted(spare, key=lambda c: (-(left * spare[c] / pool - extra[c]), c)):
        if sum(extra.values()) >= min(left, pool):
            break
        if extra[c] < spare[c]:
            extra[c] += 1
    return {c: alloc[c] + extra[c] for c in alloc}


def _by_class(recs: list[Record]) -> dict[str, list[Record]]:
    out = defaultdict(list)
    for r in sorted(recs, key=lambda r: r.id):
        out[r.complexity_derived].append(r)
    return out


def _draw(groups: dict[str, list[Record]], alloc: dict[str, int], seed: int) -> list[Record]:
    rng = random.Random(seed)
    chosen = []
    for c in sorted(groups):
        chosen += rng.sample(groups[c], alloc.get(c, 0))
    return chosen


def eval_eligible(rec: Record) -> bool:
    return (
        rec.status == "kept"
        and rec.validation_level == "result"
        and not rec.result_empty
        and not rec.time_dependent
    )


def pick_eval_set(records: list[Record], cfg: Config) -> list[Record]:
    pool = [r for r in records if r.split == "test_heldout" and eval_eligible(r)]
    groups = _by_class(pool)
    alloc = allocate_stratified(
        {c: len(v) for c, v in groups.items()}, cfg.split.eval_size, cfg.split.eval_floor_per_class
    )
    return sorted(_draw(groups, alloc, cfg.seed), key=lambda r: r.id)


def pick_val_set(records: list[Record], cfg: Config) -> list[Record]:
    pool = sorted((r for r in records if r.split == "val" and eval_eligible(r)), key=lambda r: r.id)
    n = min(cfg.split.val_size, len(pool))
    return sorted(random.Random(cfg.seed).sample(pool, n), key=lambda r: r.id)


def pick_train_mix(records: list[Record], cfg: Config) -> list[Record]:
    gretel = _by_class([r for r in records if r.split == "train" and r.source == "gretel"])
    avail = {c: len(v) for c, v in gretel.items()}
    caps = {"basic": int(cfg.sample.gretel * cfg.sample.basic_cap)}
    alloc = allocate_weighted(cfg.sample.class_weights, avail, cfg.sample.gretel, caps)
    chosen = _draw(gretel, alloc, cfg.seed)
    sqlcc = sorted(
        (r for r in records if r.split == "train" and r.source == "sqlcc"), key=lambda r: r.id
    )
    n = min(cfg.sample.sqlcc, len(sqlcc))
    chosen += random.Random(cfg.seed + 1).sample(sqlcc, n)
    return sorted(chosen, key=lambda r: r.id)

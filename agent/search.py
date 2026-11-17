"""Budgeted abstract search; transition must return an independent state."""
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from typing import Callable, Hashable, Protocol


class SearchState(Protocol):
    def key(self) -> Hashable: ...
    def score(self) -> float: ...
    def success(self) -> bool: ...


@dataclass
class SearchResult:
    actions: list
    state: SearchState
    evaluations: int
    cancelled: bool


def beam_search(initial, candidates, transition: Callable, *, width=8, depth=10,
                budget=1000, cancelled=lambda: False):
    if min(width, depth, budget) < 1:
        raise ValueError("budgets must be positive")
    frontier = [(initial, [])]
    best = frontier[0]
    evaluations = 0
    seen = {initial.key()}
    for _ in range(depth):
        children = []
        for state, path in frontier:
            if state.success():
                return SearchResult(path, state, evaluations, False)
            for action in candidates:
                if cancelled() or evaluations >= budget:
                    return SearchResult(best[1], best[0], evaluations, cancelled())
                child = transition(state, action)
                evaluations += 1
                if child.key() in seen:
                    continue
                seen.add(child.key())
                item = (child, path + [action])
                children.append(item)
                if child.score() > best[0].score():
                    best = item
                if child.success():
                    return SearchResult(item[1], child, evaluations, False)
        frontier = sorted(children, key=lambda x: x[0].score(), reverse=True)[:width]
        if not frontier:
            break
    return SearchResult(best[1], best[0], evaluations, False)


def astar(start, goal, neighbors, heuristic=lambda _: 0, budget=1000):
    serial = count()
    queue = [(heuristic(start), next(serial), 0, start, [start])]
    costs = {start: 0}
    for _ in range(budget):
        if not queue:
            break
        _, _, cost, node, path = heappop(queue)
        if cost != costs[node]:
            continue
        if node == goal:
            return path
        for target, weight in neighbors(node):
            if weight < 0:
                raise ValueError("negative edge")
            new = cost + weight
            if new < costs.get(target, float("inf")):
                costs[target] = new
                heappush(queue, (new+heuristic(target), next(serial), new, target, path+[target]))
    return None


def mpc(state, candidates, transition, **budgets):
    result = beam_search(state, candidates, transition, **budgets)
    return result.actions[:1], result

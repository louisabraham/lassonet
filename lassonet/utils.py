from itertools import zip_longest
from typing import Iterable

import scipy.stats
import torch


def eval_on_path(model, path, X_test, y_test, *, score_function=None):
    if score_function is None:
        score_fun = model.score
    else:
        assert callable(score_function)

        def score_fun(X_test, y_test):
            return score_function(y_test, model.predict(X_test))

    score = []
    for save in path:
        model.load(save.state_dict)
        score.append(score_fun(X_test, y_test))
    return score


if hasattr(torch.Tensor, "scatter_reduce_"):
    # version >= 1.12
    def scatter_reduce(input, dim, index, reduce, *, output_size=None):
        src = input
        if output_size is None:
            output_size = index.max() + 1
        return torch.empty(output_size, device=input.device).scatter_reduce(
            dim=dim, index=index, src=src, reduce=reduce, include_self=False
        )

else:
    scatter_reduce = torch.scatter_reduce


def scatter_logsumexp(input, index, *, dim=-1, output_size=None):
    """Inspired by torch_scatter.logsumexp
    Uses torch.scatter_reduce for performance
    """
    max_value_per_index = scatter_reduce(
        input, dim=dim, index=index, output_size=output_size, reduce="amax"
    )
    max_per_src_element = max_value_per_index.gather(dim, index)
    recentered_scores = input - max_per_src_element
    sum_per_index = scatter_reduce(
        recentered_scores.exp(),
        dim=dim,
        index=index,
        output_size=output_size,
        reduce="sum",
    )
    return max_value_per_index + sum_per_index.log()


def log_substract(x, y):
    """log(exp(x) - exp(y))"""
    return x + torch.log1p(-(y - x).exp())


def confidence_interval(data, confidence=0.95):
    if isinstance(data[0], Iterable):
        return [confidence_interval(d, confidence) for d in data]
    return scipy.stats.t.interval(
        confidence,
        len(data) - 1,
        scale=scipy.stats.sem(data),
    )[1]


def selection_probability(paths):
    """
    Compute the selection probability of each variable at each lambda value.
    The lambda paths must be the same for all models.
    The individual curves are smoothed to that they are monotonically decreasing.

    Returns an array of shape (n_lambdas, n_variables)
    containing the probability of each variable being selected at each lambda value
    """
    n_models = len(paths)

    all_selected = []
    selected = torch.ones_like(paths[0][0].selected)
    iterable = zip_longest(
        *[[it.selected for it in path] for path in paths],
        fillvalue=torch.zeros_like(paths[0][0].selected),
    )
    for its in iterable:
        sel = sum(its) / n_models
        selected = torch.minimum(selected, sel)
        all_selected.append(selected)
    return all_selected

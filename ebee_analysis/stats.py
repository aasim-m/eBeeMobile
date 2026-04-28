import math


def percentile(sorted_values, fraction):
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[int(position)])

    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    weight = position - lower
    return float(lower_value + (upper_value - lower_value) * weight)


def mean(values):
    return sum(values) / len(values) if values else 0.0


def stdev(values):
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def ratio(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def format_ratio(numerator, denominator):
    value = ratio(numerator, denominator)
    return f"{value:.2f}x" if denominator else "0.00x"


def number(value):
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value))}"
    return f"{value:.2f}"


def percent(value):
    return f"{value * 100:.2f}%"


def safe_float(metadata, key, default):
    raw = metadata.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def safe_float_value(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def rank_values(values):
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    idx = 0
    while idx < len(indexed):
        jdx = idx + 1
        while jdx < len(indexed) and indexed[jdx][1] == indexed[idx][1]:
            jdx += 1
        average_rank = (idx + jdx - 1) / 2.0 + 1.0
        for pos in range(idx, jdx):
            ranks[indexed[pos][0]] = average_rank
        idx = jdx
    return ranks


def pearson_correlation(xs, ys):
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0

    mean_x = mean(xs)
    mean_y = mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    denominator = denom_x * denom_y
    if denominator == 0:
        return 0.0
    return numerator / denominator


def spearman_correlation(xs, ys):
    return pearson_correlation(rank_values(xs), rank_values(ys))


def linear_fit(xs, ys):
    if len(xs) != len(ys) or not xs:
        return 0.0, 0.0

    mean_x = mean(xs)
    mean_y = mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0, mean_y
    slope = numerator / denominator
    intercept = mean_y - slope * mean_x
    return slope, intercept


def regression_error(xs, ys, slope, intercept):
    if not xs:
        return 0.0, 0.0
    predictions = [slope * x + intercept for x in xs]
    errors = [pred - y for pred, y in zip(predictions, ys)]
    mae = mean([abs(error) for error in errors])
    rmse = math.sqrt(mean([error ** 2 for error in errors]))
    return mae, rmse


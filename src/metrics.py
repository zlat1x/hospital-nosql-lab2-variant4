"""Pure-Python latency summaries, usable without database drivers."""
import statistics


def percentile(values, percent):
    values = sorted(values)
    if not values:
        raise ValueError("Empty samples")
    pos = (len(values) - 1) * percent / 100
    i = int(pos)
    fract = pos - i
    return values[i] * (1 - fract) + values[min(i + 1, len(values) - 1)] * fract


def summarize(ms):
    return {"n": len(ms), "mean_ms": round(statistics.mean(ms), 4),
            "p50_ms": round(statistics.median(ms), 4),
            "p95_ms": round(percentile(ms, 95), 4),
            "min_ms": round(min(ms), 4), "max_ms": round(max(ms), 4),
            "estimated_ops_per_sec_sequential": round(1000 / statistics.mean(ms), 2)}

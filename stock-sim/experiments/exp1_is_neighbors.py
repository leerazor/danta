"""exp-1 IS 2단계: 1단계 상위 후보의 이웃 파라미터·위상 점검(뾰족한 최적값 걸러내기). OOS는 돌리지 않는다.

실행: uv run python experiments/exp1_is_neighbors.py
"""
from __future__ import annotations

import sys

import pandas as pd

import common
import candidates as cand
from exp1_is import half_returns
from stock_sim import data


def grid() -> list[tuple[str, str, dict]]:
    B = cand.BASE
    g: list[tuple[str, str, dict]] = [("0 기준", "L20 N5 주간", dict(B))]
    for k in (3, 4, 6):
        for off in range(k if k == 4 else 1):
            g.append(("B 주기 위상", f"{k}주 offset{off}", {**B, "every_weeks": k, "week_offset": off}))
    for off in (1, 2, 3):   # offset으로 생기는 초기 현금 기간의 영향 분리용: 기준 전략도 같은 만큼 늦게 시작
        g.append(("B 주기 위상", f"1주 offset{off}(대조)", {**B, "week_offset": off}))
    for k in (0.6, 0.7, 0.8, 0.9):
        g.append(("G 거래량 급감 청산", f"vol5/vol20<{k}", {**B, "vol_exit": k}))
    for x in (0.20, 0.25, 0.30):
        g.append(("G 추적 손절", f"고점 -{int(x * 100)}%", {**B, "trail_stop": x}))
    for n in (50, 60, 70):
        g.append(("C KOSPI 필터", f"KOSPI>SMA{n}", {**B, "kospi_sma": n}))
    for L in (30, 40, 50, 60, 70):
        g.append(("A1 lookback", f"L{L}", {**B, "lookback_days": L}))
    for s, l in ((5, 40), (10, 40), (5, 60), (5, 70), (10, 60)):
        g.append(("E 거래대금 가중", f"mom×value({s}/{l})",
                  {**B, "score": "mom_x_value", "value_short": s, "value_long": l}))
    return g


def main() -> int:
    cfg = common.load_cfg()
    prices, kospi, _ = common.load_prices(cfg)
    calendar = data.build_calendar(prices)
    first_is = next(i for i, d in enumerate(calendar) if d >= common.IS_START)
    rows = []
    for fam, label, params in grid():
        if cand.warmup_needed(params) > first_is:
            print(f"워밍업 부족으로 건너뜀: {fam} {label}")
            continue
        r = common.run(prices, kospi, calendar, cand.STRAT, params, common.IS_START, common.IS_END, cfg)
        h1, h2 = half_returns(r, cfg["capital"])
        rows.append({"축": fam, "파라미터": label, "IS%": r["ret"] * 100, "전반%": h1 * 100,
                     "후반%": h2 * 100, "체결": r["trades"], "MDD%": r["mdd"] * 100,
                     "회전율": r["turnover"]})
    df = pd.DataFrame(rows)
    df["초과%p"] = df["IS%"] - rows[0]["IS%"]
    pd.set_option("display.width", 250, "display.max_rows", 200, "display.unicode.east_asian_width", True)
    print(df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

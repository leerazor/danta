"""exp-1 선택 구간(IS) 실험. OOS(2026-08-29 이후)는 이 스크립트에서 돌리지 않는다.

한 번에 한 축만 기준 전략(20일·5종목·주간)에서 바꾼다. 난수 없음, 캐시만 읽는다(API 호출 0).
실행: uv run python experiments/exp1_is.py
"""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd

import common
import candidates as cand
from stock_sim import data
from stock_sim.strategy import STRATEGIES

MID = date(2026, 2, 27)      # IS 전반/후반 경계(안정성 참고용. 선택 기준은 IS 전체 수익률)


def grid() -> list[tuple[str, str, dict]]:
    B = cand.BASE
    g: list[tuple[str, str, dict]] = [("0 기준", "L20 N5 주간", dict(B))]
    for L in (5, 10, 40, 60):
        g.append(("A1 lookback", f"L{L}", {**B, "lookback_days": L}))
    for n in (1, 2, 3, 4):
        g.append(("A2 top_n", f"N{n}", {**B, "top_n": n}))
    g.append(("B 주기", "매일", {**B, "rebalance": "daily"}))
    for k in (2, 4):
        g.append(("B 주기", f"{k}주", {**B, "every_weeks": k}))
    for n in (10, 20, 40, 60):
        g.append(("C KOSPI 필터", f"KOSPI>SMA{n}", {**B, "kospi_sma": n}))
    for n in (10, 20, 40, 60):
        g.append(("D 종목 추세", f"종가>SMA{n}", {**B, "stock_sma": n}))
    g.append(("D 종목 추세", "모멘텀>0", {**B, "abs_mom": True}))
    for s, l in ((5, 20), (5, 60), (10, 60), (20, 60)):
        g.append(("E 거래대금 가중", f"mom×value({s}/{l})",
                  {**B, "score": "mom_x_value", "value_short": s, "value_long": l}))
    for k in (0.8, 1.0, 1.2):
        g.append(("E 거래대금 필터", f"value(5/20)>={k}",
                  {**B, "value_ratio_min": k, "value_short": 5, "value_long": 20}))
    for N in (10, 20, 40, 60):
        for k in (1.0, 1.5, 2.0):
            g.append(("F 거래량 돌파", f"{N}일 신고가 vol>={k}x, 청산 SMA20",
                      {**B, "mode": "breakout", "breakout_days": N, "breakout_vol_k": k,
                       "exit_sma": 20}))
    for x in (0.05, 0.08, 0.10, 0.15, 0.20):
        g.append(("G 추적 손절", f"고점 -{int(x * 100)}%", {**B, "trail_stop": x}))
    for k in (0.5, 0.7):
        g.append(("G 거래량 급감 청산", f"vol5/vol20<{k}", {**B, "vol_exit": k}))
    return g


def half_returns(r: dict, capital: int) -> tuple[float, float]:
    eq = dict(zip(r["dates"], r["equity"]))
    mid = max(d for d in r["dates"] if d <= MID)
    return eq[mid] / capital - 1.0, r["equity"][-1] / eq[mid] - 1.0


def self_checks(prices, kospi, calendar, cfg) -> None:
    # 1) BASE 파라미터의 후보 함수가 src의 momentum_topn과 같은 결과를 내는가
    ref = STRATEGIES["momentum_topn"]
    days = [d for d in calendar if common.IS_START <= d <= common.IS_END]
    sch = ref["schedule"](calendar, days[0], days[-1], cand.BASE)
    a = ref["targets"](prices, calendar, sch, cand.BASE)
    b = cand.targets(prices, calendar, cand.schedule(calendar, days[0], days[-1], cand.BASE),
                     cand.BASE, kospi)
    same = (list(a["fill_date"]) == list(b["fill_date"]) and list(a["code"]) == list(b["code"]))
    print(f"[점검] BASE 후보 함수 == src momentum_topn 목표: {same}")
    # 2) look-ahead: 중간 날짜 이후 데이터를 잘라도 그 이전 신호의 목표가 같아야 한다
    cut = MID
    p2 = {c: df[df["date"] <= pd.Timestamp(cut)].reset_index(drop=True) for c, df in prices.items()}
    k2 = kospi[kospi["date"] <= pd.Timestamp(cut)].reset_index(drop=True)
    cal2 = [d for d in calendar if d <= cut]
    bad = []
    for fam, label, params in grid():
        full = cand.targets(prices, calendar, cand.schedule(calendar, days[0], days[-1], params), params, kospi)
        part = cand.targets(p2, cal2, cand.schedule(cal2, days[0], cut, params), params, k2)
        f = full[full["fill_date"] <= cut]
        if not (list(f["fill_date"]) == list(part["fill_date"]) and list(f["code"]) == list(part["code"])
                and list(f["rank"]) == list(part["rank"])):
            bad.append(f"{fam} {label}")
    print(f"[점검] 미래 데이터 절단 후 과거 목표 불변: {'전부 통과' if not bad else '실패 ' + str(bad)}")


def main() -> int:
    cfg = common.load_cfg()
    prices, kospi, notes = common.load_prices(cfg)
    if notes:
        print("데이터 주의:", notes)
    calendar = data.build_calendar(prices)
    first_is = next(i for i, d in enumerate(calendar) if d >= common.IS_START)
    print(f"달력 {calendar[0]} ~ {calendar[-1]} ({len(calendar)}일), IS 첫 거래일 {calendar[first_is]}, "
          f"그 이전 워밍업 {first_is}일")
    issues = data.check_data(prices, calendar)
    print(f"데이터 이슈(결측·이상 등락): {[(x['code'], x['stock'], str(x['date']), x['value']) for x in issues]}")
    self_checks(prices, kospi, calendar, cfg)
    rows = []
    for fam, label, params in grid():
        need = cand.warmup_needed(params)
        if need > first_is:
            print(f"워밍업 부족으로 건너뜀: {fam} {label} (필요 {need}, 확보 {first_is})")
            continue
        r = common.run(prices, kospi, calendar, cand.STRAT, params, common.IS_START, common.IS_END, cfg)
        h1, h2 = half_returns(r, cfg["capital"])
        rows.append({"축": fam, "파라미터": label, "IS%": r["ret"] * 100, "전반%": h1 * 100,
                     "후반%": h2 * 100, "체결": r["trades"], "청산": r["closed"],
                     "MDD%": r["mdd"] * 100, "회전율": r["turnover"], "평균보유": r["avg_pos"],
                     "비용(만원)": r["cost"] / 1e4})
    base = rows[0]
    df = pd.DataFrame(rows)
    df["초과%p"] = df["IS%"] - base["IS%"]
    pd.set_option("display.width", 250, "display.max_rows", 200, "display.unicode.east_asian_width", True)
    print(f"\nIS {r['dates'][0]} ~ {r['dates'][-1]} ({r['days']}거래일)  "
          f"KOSPI buy&hold {r['kospi'] * 100:.2f}%  유니버스 동일가중 buy&hold {r['ew'] * 100:.2f}%")
    print(df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print("\n== IS 수익률 순 ==")
    print(df.sort_values("IS%", ascending=False).head(15).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

"""result.json -> 정적 HTML 대시보드 렌더러.

계약: docs/architecture.md 1.8절, 5.2절.
- 표준 라이브러리 + jinja2 만 쓴다. stock_sim 의 다른 모듈을 import 하지 않는다.
- 수치 계산(합계·비율·좌표)을 하지 않는다. 필터는 표시 변환만 한다.

단독 실행(stock-sim/ 폴더에서):
    uv run --with jinja2 python src/stock_sim/render.py \
        --result docs/result.example.json \
        --template templates/dashboard.html.j2 \
        --out output/dashboard.example.html
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Undefined

logger = logging.getLogger(__name__)

NULL_TEXT = "–"
SIGN_COLORS = {"pos": "#1428A0", "neg": "#B0472F", "zero": "#6E7688"}
SUPPORTED_MAJOR = "1"


def _is_null(value) -> bool:
    if isinstance(value, Undefined):
        str(value)  # StrictUndefined: 빠진 키는 조용히 '–'가 되지 않고 UndefinedError 를 낸다
    return value is None or isinstance(value, str)


def won(value) -> str:
    """101858842 -> '101,858,842원'. null -> '–'."""
    if _is_null(value):
        return NULL_TEXT
    return f"{int(round(value)):,}원"


def signed_won(value) -> str:
    """-516743 -> '-516,743원', 906237 -> '+906,237원', 0 -> '0원'."""
    if _is_null(value):
        return NULL_TEXT
    n = int(round(value))
    if n > 0:
        return f"+{n:,}원"
    return f"{n:,}원"


def pct(value) -> str:
    """33.3333 -> '33.33%'. null -> '–'."""
    if _is_null(value):
        return NULL_TEXT
    text = f"{value:.2f}"
    if text == "-0.00":
        text = "0.00"
    return f"{text}%"


def signed_pct(value) -> str:
    """1.8588 -> '+1.86%', -2.1491 -> '-2.15%', 0 -> '0.00%'."""
    if _is_null(value):
        return NULL_TEXT
    text = f"{value:.2f}"
    if text in ("0.00", "-0.00"):
        return "0.00%"
    if value > 0:
        return f"+{text}%"
    return f"{text}%"


def sign_color(sign) -> str:
    """'pos' -> 블루, 'neg' -> 손실색, 그 외(zero·null) -> 회색."""
    return SIGN_COLORS.get(sign, SIGN_COLORS["zero"])


FILTERS = {
    "won": won,
    "signed_won": signed_won,
    "pct": pct,
    "signed_pct": signed_pct,
    "sign_color": sign_color,
}


def render(result_path: Path, template_path: Path, out_path: Path) -> Path:
    """result.json 을 템플릿에 넣어 HTML 로 쓴다. 쓴 파일 경로를 돌려준다."""
    result_path = Path(result_path)
    template_path = Path(template_path)
    out_path = Path(out_path)

    if not result_path.is_file():
        raise FileNotFoundError(f"result 파일이 없습니다: {result_path}")
    if not template_path.is_file():
        raise FileNotFoundError(f"템플릿 파일이 없습니다: {template_path}")

    with result_path.open("r", encoding="utf-8") as f:
        result = json.load(f)

    version = str(result.get("schema_version", "")) if isinstance(result, dict) else ""
    if version.split(".")[0] != SUPPORTED_MAJOR:
        raise ValueError(
            f"지원하지 않는 schema_version 입니다: {version!r} (major {SUPPORTED_MAJOR} 필요)"
        )

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent), encoding="utf-8"),
        autoescape=True,
        undefined=StrictUndefined,
    )
    env.filters.update(FILTERS)
    html = env.get_template(template_path.name).render(**result)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    logger.info("대시보드 렌더 완료: %s", out_path)
    return out_path


def _main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]  # stock-sim/
    parser = argparse.ArgumentParser(description="result.json 을 HTML 대시보드로 렌더한다.")
    parser.add_argument("--result", type=Path, default=root / "output" / "result.json")
    parser.add_argument("--template", type=Path, default=root / "templates" / "dashboard.html.j2")
    parser.add_argument("--out", type=Path, default=root / "output" / "dashboard.html")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        render(result_path=args.result, template_path=args.template, out_path=args.out)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main())

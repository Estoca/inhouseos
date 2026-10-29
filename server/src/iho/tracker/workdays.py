"""Dias uteis no Brasil: segunda a sexta menos feriados nacionais (fixos e moveis) e os
extras de EXTRA_HOLIDAYS (AAAA-MM-DD, separados por virgula). Ferias e ausencias de cada
pessoa entram por `absences`, nao aqui. Quando o escritorio (escritorio.estoca.cloud)
expuser ferias e feriados por pessoa, esta fonte passa a ser a dele; ate la, este calculo."""
from datetime import date, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from iho.tracker.config import settings

SP = ZoneInfo("America/Sao_Paulo")


def easter(year: int) -> date:
    """Pascoa gregoriana (algoritmo anonimo)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=16)
def national_holidays(year: int) -> frozenset[date]:
    p = easter(year)
    fixed = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)]
    movable = [p - timedelta(days=48), p - timedelta(days=47), p - timedelta(days=2), p + timedelta(days=60)]
    return frozenset([date(year, m, d) for m, d in fixed] + movable)


def extra_holidays() -> frozenset[date]:
    out = set()
    for raw in settings.extra_holidays.split(","):
        raw = raw.strip()
        if raw:
            out.add(date.fromisoformat(raw))
    return frozenset(out)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in national_holidays(d.year) and d not in extra_holidays()


def business_days(start: date, end: date) -> list[date]:
    """Dias uteis em [start, end], inclusive, em ordem."""
    out, d = [], start
    while d <= end:
        if is_business_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def last_business_days(end: date, n: int) -> list[date]:
    """Os ultimos n dias uteis terminando em `end` (inclusive se for util), em ordem."""
    out, d = [], end
    while len(out) < n and d > end - timedelta(days=n * 4 + 30):
        if is_business_day(d):
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))

"""NASA POWER daily weather connector (feeds ``fact_weather_daily``).

Free, key-less official API. Config-driven (region coordinates in
``configs/ingestion/sources.yaml``). Rows become ``NormalizedRecord``s with
deterministic provenance; the fetch function is injectable so tests never touch
the network.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta

from etl.contracts import FactFamily, NormalizedRecord
from etl.ingestion.config import WeatherSpec
from etl.provenance import attach_provenance
from etl.sources.base import BaseSource

NASA_FILL = -999.0
NASA_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

#: fetch(lat, lon, start, end, params) -> {api_param: {date: value}}
WeatherFetch = Callable[[float, float, date, date, list[str]], dict[str, dict[date, float]]]


def _nasa_power_fetch(
    lat: float, lon: float, start: date, end: date, params: list[str]
) -> dict[str, dict[date, float]]:
    import requests

    query = {
        "parameters": ",".join(params),
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    }
    response = requests.get(NASA_URL, params=query, timeout=30)
    response.raise_for_status()
    parameter = response.json()["properties"]["parameter"]

    out: dict[str, dict[date, float]] = {}
    for api_param, series in parameter.items():
        day_values: dict[date, float] = {}
        for key, value in series.items():
            if value == NASA_FILL:  # missing data sentinel
                continue
            day_values[date(int(key[:4]), int(key[4:6]), int(key[6:8]))] = float(value)
        out[api_param] = day_values
    return out


class NasaPowerSource(BaseSource):
    family = FactFamily.weather_daily

    def __init__(
        self, specs: list[WeatherSpec], *, start: date, end: date, fetch: WeatherFetch | None = None
    ) -> None:
        self._specs = specs
        self._start = start
        self._end = end
        self._fetch = fetch or _nasa_power_fetch
        self.source_code = specs[0].source_code if specs else "NASA_POWER"

    def collect(self) -> Iterable[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        for spec in self._specs:
            data = self._fetch(spec.latitude, spec.longitude, self._start, self._end, list(spec.parameters))
            for api_param, series in data.items():
                metric = spec.parameters.get(api_param, api_param.lower())
                for obs, value in series.items():
                    payload = {
                        "commodity_code": spec.commodity_code,
                        "region_code": spec.region_code,
                        "data_source_code": spec.source_code,
                        "metric_code": metric,
                        "observation_date": obs.isoformat(),
                        "value": value,
                        "latitude": spec.latitude,
                        "longitude": spec.longitude,
                    }
                    record = NormalizedRecord(
                        family=FactFamily.weather_daily,
                        data_source_code=spec.source_code,
                        commodity_code=spec.commodity_code,
                        region_code=spec.region_code,
                        metric_code=metric,
                        observation_date=obs,
                        release_date=obs + timedelta(days=spec.release_lag_days),
                        value=value,
                    )
                    records.append(
                        attach_provenance(
                            record,
                            payload,
                            source_code=spec.source_code,
                            origin=f"{spec.region_code}:{metric}",
                            key=obs.isoformat(),
                        )
                    )
        return records

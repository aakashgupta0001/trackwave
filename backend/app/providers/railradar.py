"""RailRadar adapter.

Connects to RailRadar live API (https://api.railradar.in/v1) using the configured API key.
Provides live train state, train schedule, and station live board.
"""

import logging
from datetime import date, datetime, time, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import EventType
from app.providers.base import (
    ProviderDataError,
    ProviderNotFoundError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RailwayDataProvider,
)
from app.providers.models import (
    ProviderName,
    ProviderStatus,
    StationBoard,
    StationBoardEntry,
    TrainSchedule,
    TrainScheduleStop,
    TrainState,
)
from app.providers.retry import retry_with_backoff
from app.repositories import station_repository

logger = logging.getLogger(__name__)

STATION_ALIASES: dict[str, str] = {
    "VGLJ": "JHS",  # Veerangana Lakshmibai Jhansi -> Jhansi Junction
    "PRYJ": "ALD",  # Prayagraj -> Allahabad
    "DDU": "MGS",   # Pt. Deen Dayal Upadhyaya -> Mughalsarai
    "BSBS": "MUV",  # Banaras -> Manduadih
    "AY": "FD",     # Ayodhya Cantt -> Faizabad
    "RKMP": "BPL",  # Rani Kamlapati -> Bhopal Junction
}


def _parse_time(val: str | None) -> time | None:
    """Parse time from 'HH:MM', 'HH:MM:SS', or full ISO datetime string."""
    if not val:
        return None
    val = val.strip()
    if "T" in val:
        try:
            return datetime.fromisoformat(val).time()
        except ValueError:
            pass
    try:
        return time.fromisoformat(val)
    except ValueError:
        parts = val.split(":")
        if len(parts) >= 2:
            try:
                return time(int(parts[0]), int(parts[1]))
            except ValueError:
                return None
    return None


class RailRadarProvider(RailwayDataProvider):
    name = ProviderName.RAILRADAR

    _STATUS_PATH = "/trains/{train_number}/live"
    _ROUTE_PATH = "/trains/{train_number}"
    _STATION_PATH = "/stations/{station_code}/live"

    def __init__(self) -> None:
        self._settings = get_settings()
        self._last_success: datetime | None = None
        self._last_failure: datetime | None = None
        self._last_error: str | None = None
        self._last_latency_ms: float | None = None
        self._station_coords: dict[str, tuple[float, float]] = {}

    @property
    def _configured(self) -> bool:
        s = self._settings
        return bool(s.RAILRADAR_ENABLED and s.RAILRADAR_API_KEY and s.RAILRADAR_BASE_URL)

    @property
    def _base_url(self) -> str:
        url = self._settings.RAILRADAR_BASE_URL.rstrip("/")
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        return url

    @property
    def _available(self) -> bool:
        """True once a call has succeeded and is more recent than any failure."""
        if not self._configured or self._last_success is None:
            return False
        return self._last_failure is None or self._last_success > self._last_failure

    def _require_configured(self) -> None:
        if not self._configured:
            reason = (
                "RailRadar is not configured: set RAILRADAR_ENABLED=true, RAILRADAR_API_KEY "
                "and RAILRADAR_BASE_URL."
            )
            self._last_failure = datetime.now(timezone.utc)
            self._last_error = reason
            raise ProviderUnavailableError(reason)

    async def _request(self, path: str) -> dict:
        self._require_configured()
        s = self._settings
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {s.RAILRADAR_API_KEY}"}

        async def _call() -> httpx.Response:
            async with httpx.AsyncClient(timeout=s.PROVIDER_TIMEOUT_SECONDS) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 404:
                    err_msg = f"Resource not found: {path}"
                    try:
                        err_payload = resp.json()
                        if isinstance(err_payload, dict) and "error" in err_payload:
                            err_msg = err_payload["error"].get("message") or err_msg
                    except Exception:
                        pass
                    raise ProviderNotFoundError(err_msg)
                if resp.status_code in (401, 403):
                    raise ProviderUnavailableError(f"RailRadar authentication failed (HTTP {resp.status_code})")
                if resp.status_code == 429:
                    raise ProviderUnavailableError("RailRadar rate limit exceeded")
                resp.raise_for_status()
                return resp

        started = datetime.now(timezone.utc)
        try:
            response = await retry_with_backoff(
                _call, max_attempts=3, retry_on=(httpx.TransportError,)
            )
        except (ProviderNotFoundError, ProviderUnavailableError):
            self._last_failure = datetime.now(timezone.utc)
            raise
        except httpx.TimeoutException as exc:
            self._last_failure = datetime.now(timezone.utc)
            self._last_error = "timeout"
            logger.warning("provider=RAILRADAR status=failure error=timeout")
            raise ProviderTimeoutError("RailRadar request timed out") from exc
        except httpx.HTTPError as exc:
            self._last_failure = datetime.now(timezone.utc)
            self._last_error = f"http_error:{type(exc).__name__}"
            logger.warning("provider=RAILRADAR status=failure error=%s", type(exc).__name__)
            raise ProviderUnavailableError(f"RailRadar request failed: {type(exc).__name__}") from exc

        self._last_latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        self._last_success = datetime.now(timezone.utc)
        self._last_error = None
        logger.info("provider=RAILRADAR status=success latency_ms=%.1f", self._last_latency_ms)

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderDataError("RailRadar returned a non-JSON response") from exc

        if isinstance(payload, dict) and payload.get("success") is False:
            err = payload.get("error", {})
            msg = err.get("message") or "RailRadar API returned failure"
            code = err.get("code")
            if code in ("TRAIN_NOT_FOUND", "STATION_NOT_FOUND", "NOT_FOUND"):
                raise ProviderNotFoundError(f"RailRadar: {msg}")
            raise ProviderUnavailableError(f"RailRadar error: {msg}")

        return payload

    async def get_train_status(self, session: AsyncSession, train_number: str, journey_date: date) -> TrainState:
        payload = await self._request(self._STATUS_PATH.format(train_number=train_number))
        data = payload.get("data", payload)
        try:
            curr = data.get("currentLocation") or {}
            station_code = data.get("station_code") or curr.get("stationCode")
            section_code = data.get("section_code") or curr.get("sectionCode")

            status_str = (data.get("status") or curr.get("status") or "").lower()
            if status_str == "departed":
                event_type = EventType.DEPARTURE
            elif status_str in ("arrived", "at-station"):
                event_type = EventType.ARRIVAL
            else:
                event_type = EventType.POSITION_UPDATE

            ts_str = data.get("lastUpdatedAt") or data.get("timestamp")
            if not ts_str:
                raise ProviderDataError("RailRadar status response missing required timestamp")
            ts = datetime.fromisoformat(ts_str)

            delay = data.get("delayMinutes")
            if delay is None:
                delay = data.get("delay_minutes")
            if delay is None:
                delay = curr.get("delayMinutes")
            if delay is None:
                delay = curr.get("delay_minutes")

            speed = data.get("speed_kmph")
            if speed is None:
                speed = curr.get("speed_kmph")
            if speed is None:
                train_meta = data.get("train") or {}
                speed = train_meta.get("avgSpeed")
            if speed is not None:
                speed = float(speed)

            lat = data.get("latitude") or curr.get("latitude") or curr.get("lat")
            lng = data.get("longitude") or curr.get("longitude") or curr.get("lng")

            # Check in-memory route station coords cache
            if (lat is None or lng is None) and station_code in self._station_coords:
                lat, lng = self._station_coords[station_code]

            # Check DB station table with alias support (e.g. VGLJ -> JHS, PRYJ -> ALD, RKMP -> BPL)
            effective_station_code = STATION_ALIASES.get(station_code, station_code) if station_code else None
            db_station = None
            if effective_station_code and session is not None:
                db_station = await station_repository.get_by_code(session, effective_station_code)
                if db_station and db_station.latitude is not None and db_station.longitude is not None:
                    if lat is None or lng is None:
                        lat = float(db_station.latitude)
                        lng = float(db_station.longitude)

            # Fallback coordinates from source/destination if matching
            if station_code and (lat is None or lng is None):
                train_meta = data.get("train") or {}
                for endpoint_key in ("source", "destination"):
                    ep = train_meta.get(endpoint_key)
                    if isinstance(ep, dict) and ep.get("code") in (station_code, effective_station_code):
                        lat = ep.get("lat")
                        lng = ep.get("lng")
                        break

            # If still missing coordinates, fetch route once to populate station coordinate cache
            if (lat is None or lng is None) and station_code and session is not None:
                try:
                    await self.get_train_route(session, train_number)
                    if station_code in self._station_coords:
                        lat, lng = self._station_coords[station_code]
                except Exception:
                    pass

            # If the station matches a digital twin alias (e.g. VGLJ -> JHS), normalize to DB station code
            normalized_station_code = station_code
            if db_station is not None:
                normalized_station_code = db_station.station_code

            return TrainState(
                train_number=train_number,
                journey_date=journey_date,
                timestamp=ts,
                latitude=float(lat) if lat is not None else None,
                longitude=float(lng) if lng is not None else None,
                speed_kmph=speed,
                station_code=normalized_station_code,
                section_code=section_code,
                delay_minutes=delay,
                event_type=event_type,
                data_source=ProviderName.RAILRADAR,
                retrieved_at=datetime.now(timezone.utc),
                metadata={
                    "train_name": data.get("trainName") or data.get("train_name"),
                    "tracking_mode": data.get("trackingMode") or data.get("tracking_mode"),
                    "status": data.get("status"),
                    "is_live": data.get("isLive", True),
                    "previous_halt": data.get("previousHalt"),
                    "next_halt": data.get("nextHalt"),
                    "current_location": curr,
                },
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderDataError(f"Could not normalize RailRadar status response: {exc}") from exc

    async def get_train_route(self, session: AsyncSession, train_number: str) -> TrainSchedule:
        payload = await self._request(self._ROUTE_PATH.format(train_number=train_number))
        data = payload.get("data", payload)
        try:
            train_meta = data.get("train") or {}
            src = train_meta.get("source") or data.get("source", "")
            source_code = src.get("code") if isinstance(src, dict) else str(src or "")
            dst = train_meta.get("destination") or data.get("destination", "")
            dest_code = dst.get("code") if isinstance(dst, dict) else str(dst or "")

            stops = []
            route_stops = data.get("route") or data.get("stations", [])
            for s in route_stops:
                stn = s.get("station")
                stn_code = s.get("station_code") or (stn.get("code") if isinstance(stn, dict) else s.get("stationCode", ""))
                stn_name = s.get("station_name") or (stn.get("name") if isinstance(stn, dict) else s.get("stationName"))
                if isinstance(stn, dict) and "lat" in stn and "lng" in stn:
                    try:
                        self._station_coords[stn_code] = (float(stn["lat"]), float(stn["lng"]))
                    except (ValueError, TypeError):
                        pass
                seq = s.get("sequence_number") or s.get("sequence", len(stops) + 1)
                arr = s.get("scheduled_arrival") or s.get("arrival") or s.get("scheduledArrival")
                dep = s.get("scheduled_departure") or s.get("departure") or s.get("scheduledDeparture")
                dist = s.get("distance_km") or s.get("distance", 0.0)
                stops.append(
                    TrainScheduleStop(
                        sequence_number=int(seq),
                        station_code=stn_code,
                        station_name=stn_name,
                        scheduled_arrival=_parse_time(arr),
                        scheduled_departure=_parse_time(dep),
                        distance_km=float(dist) if dist is not None else None,
                    )
                )

            return TrainSchedule(
                train_number=train_number,
                source=source_code,
                destination=dest_code,
                stations=stops,
                data_source=ProviderName.RAILRADAR,
                retrieved_at=datetime.now(timezone.utc),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderDataError(f"Could not normalize RailRadar route response: {exc}") from exc

    async def get_station_status(self, session: AsyncSession, station_code: str) -> StationBoard:
        payload = await self._request(self._STATION_PATH.format(station_code=station_code))
        data = payload.get("data", payload)
        try:
            entries = []
            for item in (data.get("trains") or []):
                t_info = item.get("train") or {}
                stop_info = item.get("stop") or {}
                live_info = item.get("live") or {}
                t_num = item.get("train_number") or t_info.get("number", "")
                t_name = item.get("train_name") or t_info.get("name")
                arr = item.get("scheduled_arrival") or stop_info.get("arrival")
                dep = item.get("scheduled_departure") or stop_info.get("departure")
                delay = item.get("delay_minutes") or live_info.get("delayMinutes")
                st = item.get("status") or live_info.get("type") or "RUNNING"
                entries.append(
                    StationBoardEntry(
                        train_number=str(t_num),
                        train_name=t_name,
                        scheduled_arrival=_parse_time(arr),
                        scheduled_departure=_parse_time(dep),
                        delay_minutes=delay,
                        status=st,
                    )
                )

            return StationBoard(
                station_code=station_code,
                timestamp=datetime.now(timezone.utc),
                trains=entries,
                data_source=ProviderName.RAILRADAR,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderDataError(f"Could not normalize RailRadar station response: {exc}") from exc

    async def probe(self) -> bool:
        """Lightweight connectivity probe."""
        if not self._configured:
            return False
        try:
            await self._request("/trains/12002")
            return True
        except Exception:
            return False

    async def get_status(self) -> ProviderStatus:
        if self._configured and self._last_success is None and self._last_failure is None:
            await self.probe()

        return ProviderStatus(
            provider=self.name,
            enabled=self._settings.RAILRADAR_ENABLED,
            available=self._available,
            last_success=self._last_success,
            last_failure=self._last_failure,
            latency_ms=self._last_latency_ms,
            error=self._last_error if self._settings.RAILRADAR_ENABLED else "RAILRADAR_ENABLED is false",
            configured=self._configured,
            provider_type="REAL",
        )

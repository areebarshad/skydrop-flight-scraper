"""Hand-rolled protobuf encoder for the Google Flights tfs query parameter.

Field numbers are from public reverse-engineering of the tfs protobuf schema
and must be verified empirically against a known-good browser URL before
trusting. fast-flights 3.1.0 source is the cross-check reference.

Schema sketch:
  FlightData { date=2(str), from=13(Airport{code=2}), to=14(Airport{code=2}) }
  Info       { data=3(repeated FlightData), pax=1(varint), seat=9(varint),
               trip=19(varint 1=round,2=oneway) }
"""
from __future__ import annotations

import base64
from datetime import date

from flight_alert_scraper.models.query import CabinClass, SearchQuery

_CABIN_MAP = {
    CabinClass.ECONOMY: 1,
    CabinClass.PREMIUM_ECONOMY: 2,
    CabinClass.BUSINESS: 3,
    CabinClass.FIRST: 4,
}


def _varint(value: int) -> bytes:
    buf = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            buf.append(b | 0x80)
        else:
            buf.append(b)
            break
    return bytes(buf)


def _field_varint(field: int, value: int) -> bytes:
    tag = (field << 3) | 0  # wire type 0 = varint
    return _varint(tag) + _varint(value)


def _field_bytes(field: int, data: bytes) -> bytes:
    tag = (field << 3) | 2  # wire type 2 = length-delimited
    return _varint(tag) + _varint(len(data)) + data


def _field_str(field: int, value: str) -> bytes:
    return _field_bytes(field, value.encode())


def _encode_airport(code: str) -> bytes:
    return _field_str(2, code)


def _encode_flight_data(d: date, origin: str, destination: str) -> bytes:
    msg = (
        _field_str(2, d.strftime("%Y-%m-%d"))
        + _field_bytes(13, _encode_airport(origin))
        + _field_bytes(14, _encode_airport(destination))
    )
    return msg


def _encode_info(
    flight_data: bytes,
    adults: int,
    cabin: CabinClass,
    round_trip: bool,
) -> bytes:
    trip_type = 1 if round_trip else 2
    return (
        _field_varint(1, adults)
        + _field_bytes(3, flight_data)
        + _field_varint(9, _CABIN_MAP[cabin])
        + _field_varint(19, trip_type)
    )


def encode(query: SearchQuery) -> str:
    """Return base64url-encoded tfs parameter (no padding) for the given query."""
    fd = _encode_flight_data(query.depart_date, query.origin, query.destination)
    if query.return_date is not None:
        fd += _encode_flight_data(query.return_date, query.destination, query.origin)
    info = _encode_info(fd, query.adults, query.cabin, query.return_date is not None)
    return base64.urlsafe_b64encode(info).rstrip(b"=").decode()


def build_url(query: SearchQuery) -> str:
    tfs = encode(query)
    return f"https://www.google.com/travel/flights/search?tfs={tfs}&curr=USD&gl=us"

"""Hand-rolled protobuf encoder for the Google Flights tfs query parameter.

Verified against a real browser-decoded tfs for IAD→KHI 2026-12-16 /
KHI→IAD 2027-01-21, 1 adult, economy, round trip.

Confirmed schema (verified against 1-adult and 2-adult round trips):
  Airport    { 1: varint(1),  2: string(code) }
  FlightData { 2: string("YYYY-MM-DD"),
               13: Airport(origin), 14: Airport(destination) }
  Info       { 1: varint(28),          # constant; unchanged across pax counts
               2: varint(2),           # constant
               3: FlightData,          # REPEATED — one field-3 per leg
               8: varint(1),           # REPEATED — one occurrence per adult
               9: varint(cabin),       # 1=economy 2=premium_economy 3=business 4=first
               14: varint(1),          # constant
               16: { 1: varint(0xFFFFFFFFFFFFFFFF) }, # sentinel
               19: varint(trip_type) } # 1=round_trip 2=one_way
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
    # Field 1 = varint(1) confirmed present in real tfs; field 2 = IATA code.
    return _field_varint(1, 1) + _field_str(2, code)


def _encode_flight_data(d: date, origin: str, destination: str) -> bytes:
    return (
        _field_str(2, d.strftime("%Y-%m-%d"))
        + _field_bytes(13, _encode_airport(origin))
        + _field_bytes(14, _encode_airport(destination))
    )


def _encode_info(
    flight_data_list: list[bytes],
    adults: int,
    cabin: CabinClass,
    round_trip: bool,
) -> bytes:
    trip_type = 1 if round_trip else 2
    # Each FlightData is a separate field-3 (repeated field), not one combined blob.
    fd_encoded = b"".join(_field_bytes(3, fd) for fd in flight_data_list)
    # Field 8 is repeated once per adult (each occurrence = varint 1).
    pax_encoded = b"".join(_field_varint(8, 1) for _ in range(adults))
    field16 = _field_bytes(16, _field_varint(1, 0xFFFFFFFFFFFFFFFF))
    return (
        _field_varint(1, 28)       # constant
        + _field_varint(2, 2)      # constant
        + fd_encoded               # repeated field 3: one per FlightData
        + pax_encoded              # repeated field 8: one per adult
        + _field_varint(9, _CABIN_MAP[cabin])
        + _field_varint(14, 1)     # constant
        + field16                  # sentinel sub-message
        + _field_varint(19, trip_type)
    )


def encode(query: SearchQuery) -> str:
    """Return base64url-encoded tfs parameter (no padding) for the given query."""
    flights = [_encode_flight_data(query.depart_date, query.origin, query.destination)]
    if query.return_date is not None:
        flights.append(
            _encode_flight_data(query.return_date, query.destination, query.origin)
        )
    info = _encode_info(flights, query.adults, query.cabin, query.return_date is not None)
    return base64.urlsafe_b64encode(info).rstrip(b"=").decode()


def build_url(query: SearchQuery) -> str:
    tfs = encode(query)
    return f"https://www.google.com/travel/flights/search?tfs={tfs}&curr=USD&gl=us"

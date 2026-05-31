"""
Station name → (globalId, latitude, longitude) resolver.
Uses the MVG locations API. Blocking — called once at startup.
"""


def resolve_station(station_name, pool, ssl_context):
    """Resolve a station name to (globalId, latitude, longitude).
    Filters results to S-BAHN stations only, picks the first match.
    Returns (None, None, None) on failure."""
    # Lazy import — gracefully fails if adafruit_requests is missing
    import adafruit_requests

    # URL-encode: replace spaces with %20 (sufficient for station names)
    encoded = station_name.strip().replace(" ", "%20")
    url = f"https://www.mvg.de/api/bgw-pt/v3/locations?query={encoded}"

    print(f"Resolving station: '{station_name}'...")
    r = None
    try:
        session = adafruit_requests.Session(pool, ssl_context)
        r = session.get(url, timeout=10)

        if r.status_code != 200:
            print(f"Location API HTTP {r.status_code}")
            return None, None, None

        data = r.json()
        r.close()
        r = None

        if not isinstance(data, list):
            print("Location API: unexpected response format")
            return None, None, None

        # Filter to S-BAHN stations, pick the first match
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if "SBAHN" not in entry.get("transportTypes", []):
                continue
            gid = entry.get("globalId", "")
            lat = entry.get("latitude")
            lon = entry.get("longitude")
            name = entry.get("name", "")
            if gid and lat is not None and lon is not None:
                print(f"Resolved: {name} → {gid} ({lat}, {lon})")
                return gid, float(lat), float(lon)

        print(f"No S-Bahn station found for '{station_name}'")
        return None, None, None

    except Exception as e:
        print(f"Station resolution error: {e}")
        return None, None, None
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass

import os

DB_CONFIG = {
    "dbname": os.environ.get("WI_DB_NAME", "weather_intel"),
    "user": os.environ.get("WI_DB_USER", "weather"),
    "password": os.environ.get("WI_DB_PASSWORD", "weather_local"),
    "host": os.environ.get("WI_DB_HOST", "localhost"),
    "port": int(os.environ.get("WI_DB_PORT", "5432")),
}

DATABASE_URL = "postgresql://{user}:{password}@{host}:{port}/{dbname}".format(**DB_CONFIG)

STATIONS = {
    "hyannis": {"station_id": "USW00094720", "name": "Hyannis/Barnstable", "covers": "Cape Cod", "lat": 41.6719, "lon": -70.2697},
    "plymouth": {"station_id": "USW00054769", "name": "Plymouth", "covers": "South Shore", "lat": 41.9086, "lon": -70.7278},
    "taunton": {"station_id": "USW00054777", "name": "Taunton", "covers": "SE MA / Brockton", "lat": 41.8756, "lon": -71.0208},
    "new-bedford": {"station_id": "USW00094726", "name": "New Bedford", "covers": "South Coast", "lat": 41.6792, "lon": -70.9592},
    "norwood": {"station_id": "USW00054704", "name": "Norwood", "covers": "Metro South / Norfolk", "lat": 42.1911, "lon": -71.1733},
    "worcester": {"station_id": "USW00094746", "name": "Worcester", "covers": "Central MA", "lat": 42.2706, "lon": -71.8731},
    "fitchburg": {"station_id": "USW00004780", "name": "Fitchburg", "covers": "North Central MA", "lat": 42.5550, "lon": -71.7569},
    "lowell": {"station_id": "USW00094723", "name": "Lawrence/Lowell", "covers": "Merrimack Valley", "lat": 42.7125, "lon": -71.1256},
    "springfield": {"station_id": "USW00014703", "name": "Springfield/Chicopee", "covers": "Springfield area", "lat": 42.2000, "lon": -72.5333},
    "westfield": {"station_id": "USW00014775", "name": "Westfield", "covers": "Western MA", "lat": 42.1600, "lon": -72.7125},
}

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_HISTORY_URL = "https://archive-api.open-meteo.com/v1/archive"

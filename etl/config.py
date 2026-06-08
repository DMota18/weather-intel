"""Station configuration and project constants."""

STATIONS = {
    "USW00094720": {"name": "Hyannis/Barnstable Municipal", "covers": "Cape Cod", "lat": 41.6719, "lon": -70.2697},
    "USW00054769": {"name": "Plymouth Municipal", "covers": "South Shore", "lat": 41.9086, "lon": -70.7278},
    "USW00054777": {"name": "Taunton Municipal", "covers": "SE MA / Brockton corridor", "lat": 41.8756, "lon": -71.0208},
    "USW00094726": {"name": "New Bedford Municipal", "covers": "South Coast", "lat": 41.6792, "lon": -70.9592},
    "USW00054704": {"name": "Norwood Memorial", "covers": "Metro South / Norfolk County", "lat": 42.1911, "lon": -71.1733},
    "USW00094746": {"name": "Worcester Regional", "covers": "Central MA", "lat": 42.2706, "lon": -71.8731},
    "USW00004780": {"name": "Fitchburg Municipal", "covers": "North Central MA", "lat": 42.5550, "lon": -71.7569},
    "USW00094723": {"name": "Lawrence Municipal", "covers": "Merrimack Valley / Lowell", "lat": 42.7125, "lon": -71.1256},
    "USW00014703": {"name": "Chicopee/Westover", "covers": "Springfield area", "lat": 42.2000, "lon": -72.5333},
    "USW00014775": {"name": "Westfield Barnes", "covers": "Western MA", "lat": 42.1600, "lon": -72.7125},
}

GHCN_BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/"

ELEMENTS_NEEDED = ["TMAX", "TMIN", "PRCP", "SNOW", "SNWD", "AWND", "WSF2", "WSF5"]

BACKFILL_START_YEAR = 2021

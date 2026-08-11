# Openreach Route Planner

Local Django app for planning a day's Openreach jobs with AM / PM / all-day appointment windows.

## Features

- Add jobs by **address or postcode** (street names resolved automatically)
- Appointment types:
  - **AM** (8am–1pm) — routed first
  - **PM** (1pm–6pm) — routed after AM
  - **All day** — inserted where they best fit the overall route
- Edit AM/PM after adding, then re-plan
- Add job notes anytime without changing the route
- Sets a **start point** (home/depot)
- Road path-finding via OSRM (OpenStreetMap)
- Accurate driving miles + minutes between stops
- Map view + **Open in Google Maps** link
- **Clear route** wipes everything ready for the next day
- Local **SQLite** database

## Daily workflow

1. Morning (~09:30): add today's jobs, click **Plan best route**
2. Evening: click **Clear route**

## Docker (port 8889)

```bash
docker compose up -d --build
```

App: http://localhost:8889/

Optional env vars (compose / `.env`):

- `SECRET_KEY` — Django secret
- `CSRF_TRUSTED_ORIGINS` — comma-separated origins, e.g. `http://192.168.0.93:8889`
- `ALLOWED_HOSTS` — default `*`

Data persists in the `routeplanner_data` Docker volume.

Stop:

```bash
docker compose down
```

## Local setup (without Docker)

```bash
cd routeplanner
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

1. Go to **Start point** and save your home/depot postcode
2. Add today's jobs (postcode is enough)
3. Click **Plan best route**

## Notes

- UK postcodes via [postcodes.io](https://postcodes.io/) (free)
- Street names via OpenStreetMap Nominatim reverse geocode
- Driving routes via public OSRM
- Assumed ~45 minutes on site between jobs for ETA — adjust `STOP_MINUTES` in `planner/routing.py`

## Admin

```bash
python manage.py createsuperuser
```

Then visit `/admin/`

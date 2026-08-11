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

Public URL: **https://plan.sitematrix.co.uk**

```bash
docker compose up -d --build
```

Container listens on **8889** — point your reverse proxy / Traefik at that port.

Optional env vars (compose / `.env`):

- `SECRET_KEY` — Django secret (set a strong one in production)
- `CSRF_TRUSTED_ORIGINS` — defaults include `https://plan.sitematrix.co.uk`
- `ALLOWED_HOSTS` — defaults include `plan.sitematrix.co.uk`

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

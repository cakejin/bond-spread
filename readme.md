# bond-spread

Local data pipeline playground using PostgreSQL and MongoDB.

## Prerequisites

- Docker Desktop
- Python 3.10+

## Environment

Create `.env` in project root:

```env
POSTGRES_USER=bond_user
POSTGRES_PASSWORD=bond_pass
POSTGRES_DB=bond_db
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

MONGO_URI=mongodb://localhost:27017/
MONGO_DB=bond_raw
```

## Start Databases

```bash
docker compose up -d postgres mongo
```

## Install Python Dependencies

```bash
python -m pip install -r requirements.txt
```

## Connection Checks

PostgreSQL:

```bash
python src/connect_postgres.py
```

MongoDB:

```bash
python src/connect_mongo.py
```

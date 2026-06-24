"""
Sync Postgres data to BigQuery.

Exports stations, daily_weather, and jobs from the operational Postgres
database to BigQuery for analytical queries, dbt, and Tableau.
"""

import os
import sys
import psycopg2
import psycopg2.extras
from google.cloud import bigquery

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(
    os.path.dirname(__file__), "..", "gcp-key.json"
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from config import DB_CONFIG

PROJECT_ID = "nesc-weather-intel"
DATASET_ID = "weather_intel"
FULL_DATASET = f"{PROJECT_ID}.{DATASET_ID}"


def get_bq_client():
    return bigquery.Client(project=PROJECT_ID)


def ensure_dataset(client):
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    try:
        client.get_dataset(dataset_ref)
        print(f"  Dataset {DATASET_ID} exists")
    except Exception:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        client.create_dataset(dataset)
        print(f"  Created dataset {DATASET_ID}")


def sync_table(client, pg_conn, table_name, query, schema):
    print(f"\n  Syncing {table_name}...")

    with pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query)
        rows = cur.fetchall()
    print(f"    Fetched {len(rows)} rows from Postgres")

    if not rows:
        print(f"    No data to sync for {table_name}")
        return

    table_ref = f"{FULL_DATASET}.{table_name}"

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    job = client.load_table_from_json(
        [dict(row) for row in rows],
        table_ref,
        job_config=job_config,
    )
    job.result()
    print(f"    Loaded {job.output_rows} rows to {table_ref}")


def main():
    print("BigQuery Sync starting...")

    client = get_bq_client()
    ensure_dataset(client)

    pg_conn = psycopg2.connect(**DB_CONFIG)

    # Stations
    sync_table(client, pg_conn, "stations",
        "SELECT station_id, name, covers, state, latitude::float, longitude::float FROM stations",
        [
            bigquery.SchemaField("station_id", "STRING"),
            bigquery.SchemaField("name", "STRING"),
            bigquery.SchemaField("covers", "STRING"),
            bigquery.SchemaField("state", "STRING"),
            bigquery.SchemaField("latitude", "FLOAT"),
            bigquery.SchemaField("longitude", "FLOAT"),
        ]
    )

    # Daily weather
    sync_table(client, pg_conn, "daily_weather",
        """SELECT station_id, observation_date::text,
           temp_max_f::float, temp_min_f::float, temp_mean_f::float,
           precip_in::float, snow_in::float, snow_depth_in::float,
           wind_avg_mph::float, wind_max_mph::float,
           pour_score, sealer_score
           FROM daily_weather""",
        [
            bigquery.SchemaField("station_id", "STRING"),
            bigquery.SchemaField("observation_date", "DATE"),
            bigquery.SchemaField("temp_max_f", "FLOAT"),
            bigquery.SchemaField("temp_min_f", "FLOAT"),
            bigquery.SchemaField("temp_mean_f", "FLOAT"),
            bigquery.SchemaField("precip_in", "FLOAT"),
            bigquery.SchemaField("snow_in", "FLOAT"),
            bigquery.SchemaField("snow_depth_in", "FLOAT"),
            bigquery.SchemaField("wind_avg_mph", "FLOAT"),
            bigquery.SchemaField("wind_max_mph", "FLOAT"),
            bigquery.SchemaField("pour_score", "STRING"),
            bigquery.SchemaField("sealer_score", "STRING"),
        ]
    )

    # Jobs
    sync_table(client, pg_conn, "jobs",
        """SELECT job_id, start_date::text, completion_date::text,
           final_revenue::float, month, lead_name, address,
           job_type, concrete_type, lead_status,
           square_footage, concrete_company, sealer_coats, station_id
           FROM jobs""",
        [
            bigquery.SchemaField("job_id", "INTEGER"),
            bigquery.SchemaField("start_date", "DATE"),
            bigquery.SchemaField("completion_date", "DATE"),
            bigquery.SchemaField("final_revenue", "FLOAT"),
            bigquery.SchemaField("month", "STRING"),
            bigquery.SchemaField("lead_name", "STRING"),
            bigquery.SchemaField("address", "STRING"),
            bigquery.SchemaField("job_type", "STRING"),
            bigquery.SchemaField("concrete_type", "STRING"),
            bigquery.SchemaField("lead_status", "STRING"),
            bigquery.SchemaField("square_footage", "INTEGER"),
            bigquery.SchemaField("concrete_company", "STRING"),
            bigquery.SchemaField("sealer_coats", "INTEGER"),
            bigquery.SchemaField("station_id", "STRING"),
        ]
    )

    pg_conn.close()
    print("\nSync complete.")


if __name__ == "__main__":
    main()

"""
UC3 — Apache Spark Aggregation Workflow
Acme Ltd Financial Data Warehouse

Reads time-series data from MongoDB, computes aggregations using Spark,
and persists results back to MongoDB in the `spark_aggregations` collection.

Usage:
    python spark/aggregations.py

Requirements:
    pip install pyspark pymongo
    MongoDB must be running (docker-compose up -d)
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from pymongo import MongoClient
from datetime import datetime, timezone
import json

MONGO_URI = "mongodb://acme:acme_secret@localhost:27017/acme_dwh?authSource=admin"
MONGO_DB = "acme_dwh"


def get_mongo_data(collection_name: str) -> list:
    """Fetch all documents from a MongoDB collection."""
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    docs = list(db[collection_name].find({}, {"_id": 0}))
    client.close()
    # Convert datetime objects to strings for Spark compatibility
    for doc in docs:
        for k, v in doc.items():
            if isinstance(v, datetime):
                doc[k] = v.isoformat()
    return docs


def save_to_mongo(collection_name: str, records: list) -> None:
    """Persist Spark results back to MongoDB."""
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    col = db[collection_name]
    col.drop()  # replace with fresh results each run
    if records:
        col.insert_many(records)
    print(f"  Saved {len(records)} records to `{collection_name}`")
    client.close()


def main():
    print("=" * 60)
    print("Acme Financial DWH — Spark Aggregation Job")
    print("=" * 60)

    # ── Start Spark session ───────────────────────────────────────
    spark = SparkSession.builder \
        .appName("AcmeFinancialDWH-Aggregations") \
        .master("local[*]") \
        .config("spark.sql.shuffle.partitions", "4") \
        .getOrCreate()

    spark.sparkContext.setLogLevel("WARN")
    print("\n[1/5] Spark session started")

    # ── Load data from MongoDB ────────────────────────────────────
    print("[2/5] Loading time-series data from MongoDB...")
    ts_docs = get_mongo_data("time_series")
    asset_docs = get_mongo_data("assets")

    if not ts_docs:
        print("  ERROR: No time-series data found. Run docker-compose up -d and wait for seeder.")
        spark.stop()
        return

    print(f"  Loaded {len(ts_docs)} time-series records")
    print(f"  Loaded {len(asset_docs)} asset records")

    # ── Create Spark DataFrames ───────────────────────────────────
    ts_df = spark.createDataFrame(ts_docs)
    ts_df = ts_df.withColumn("close", F.col("close").cast("double")) \
                 .withColumn("open", F.col("open").cast("double")) \
                 .withColumn("high", F.col("high").cast("double")) \
                 .withColumn("low", F.col("low").cast("double")) \
                 .withColumn("volume", F.col("volume").cast("double")) \
                 .withColumn("series_date", F.to_timestamp("series_date"))

    # Latest version of each asset (temporal DWH — pick most recent valid_from)
    asset_df = spark.createDataFrame(asset_docs)
    asset_window = Window.partitionBy("asset_id").orderBy(F.desc("valid_from"))
    latest_assets = asset_df \
        .filter(F.col("record_status") == "active") \
        .withColumn("rn", F.row_number().over(asset_window)) \
        .filter(F.col("rn") == 1) \
        .select("asset_id", "symbol", "asset_class", "region")

    # Join time-series with asset metadata
    joined = ts_df.join(latest_assets, on="asset_id", how="left")

    print("[3/5] Computing aggregations...")

    # ── Aggregation 1: Per-asset summary statistics ───────────────
    print("  → Per-asset summary statistics")
    summary = joined.groupBy("asset_id", "symbol", "asset_class", "source_id") \
        .agg(
            F.count("close").alias("record_count"),
            F.round(F.avg("close"), 4).alias("avg_close"),
            F.round(F.min("close"), 4).alias("min_close"),
            F.round(F.max("close"), 4).alias("max_close"),
            F.round(F.stddev("close"), 4).alias("std_close"),
            F.round(F.sum("volume"), 2).alias("total_volume"),
            F.round(F.avg("volume"), 2).alias("avg_daily_volume"),
            F.min("series_date").alias("first_date"),
            F.max("series_date").alias("last_date"),
        )

    # ── Aggregation 2: Daily returns per asset ────────────────────
    print("  → Daily returns (price change %)")
    window_asset = Window.partitionBy("asset_id", "source_id").orderBy("series_date")
    returns_df = ts_df \
        .withColumn("prev_close", F.lag("close", 1).over(window_asset)) \
        .withColumn("daily_return_pct",
                    F.round((F.col("close") - F.col("prev_close")) / F.col("prev_close") * 100, 4)) \
        .filter(F.col("prev_close").isNotNull())

    volatility = returns_df.groupBy("asset_id", "source_id") \
        .agg(
            F.round(F.avg("daily_return_pct"), 4).alias("avg_daily_return_pct"),
            F.round(F.stddev("daily_return_pct"), 4).alias("volatility_pct"),
            F.round(F.min("daily_return_pct"), 4).alias("worst_day_pct"),
            F.round(F.max("daily_return_pct"), 4).alias("best_day_pct"),
        )

    # ── Aggregation 3: Rolling 30-day average close ───────────────
    print("  → Rolling 30-day average close")
    rolling_window = Window.partitionBy("asset_id", "source_id") \
        .orderBy(F.col("series_date").cast("long")) \
        .rowsBetween(-29, 0)

    rolling_df = ts_df \
        .withColumn("rolling_30d_avg_close", F.round(F.avg("close").over(rolling_window), 4)) \
        .select("asset_id", "source_id", "series_date", "close", "rolling_30d_avg_close") \
        .orderBy("asset_id", "series_date")

    # ── Aggregation 4: Asset class breakdown ─────────────────────
    print("  → Asset class breakdown")
    class_breakdown = joined.groupBy("asset_class") \
        .agg(
            F.countDistinct("asset_id").alias("num_assets"),
            F.count("close").alias("total_records"),
            F.round(F.avg("close"), 4).alias("avg_close_across_class"),
        )

    # ── Collect results and save to MongoDB ──────────────────────
    print("[4/5] Persisting results to MongoDB...")

    def df_to_dicts(df):
        rows = []
        for row in df.collect():
            d = row.asDict()
            # Convert Timestamp to string
            for k, v in d.items():
                if hasattr(v, 'isoformat'):
                    d[k] = v.isoformat()
                elif v != v:  # NaN check
                    d[k] = None
            d["computed_at"] = datetime.now(timezone.utc).isoformat()
            rows.append(d)
        return rows

    save_to_mongo("spark_asset_summary", df_to_dicts(summary))
    save_to_mongo("spark_volatility", df_to_dicts(volatility))
    save_to_mongo("spark_rolling_avg", df_to_dicts(rolling_df))
    save_to_mongo("spark_class_breakdown", df_to_dicts(class_breakdown))

    # ── Print preview ─────────────────────────────────────────────
    print("\n[5/5] Results preview:")
    print("\n--- Per-Asset Summary ---")
    summary.select("symbol", "avg_close", "min_close", "max_close", "std_close", "record_count") \
           .show(truncate=False)

    print("--- Volatility (Daily Returns) ---")
    volatility_with_symbol = volatility.join(
        latest_assets.select("asset_id", "symbol"), on="asset_id", how="left"
    )
    volatility_with_symbol.select("symbol", "avg_daily_return_pct", "volatility_pct", "best_day_pct", "worst_day_pct") \
                          .show(truncate=False)

    print("--- Asset Class Breakdown ---")
    class_breakdown.show(truncate=False)

    spark.stop()
    print("\nSpark aggregation job completed successfully.")
    print("Results saved to MongoDB collections: spark_asset_summary, spark_volatility, spark_rolling_avg, spark_class_breakdown")


if __name__ == "__main__":
    main()

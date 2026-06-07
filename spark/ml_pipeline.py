"""
UC3 — Apache Spark ML Pipeline
Acme Ltd Financial Data Warehouse

Reads historical time-series data from MongoDB, trains a Linear Regression
model per asset using Spark MLlib, evaluates it, and persists predictions
back to MongoDB in the `spark_ml_predictions` collection.

Usage:
    python spark/ml_pipeline.py

Requirements:
    pip install pyspark pymongo
    MongoDB must be running (docker-compose up -d)
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from pyspark.ml.feature import VectorAssembler
from pyspark.ml.regression import LinearRegression
from pyspark.ml.evaluation import RegressionEvaluator
from pyspark.ml import Pipeline
from pymongo import MongoClient
from datetime import datetime, timezone


MONGO_URI = "mongodb://acme:acme_secret@localhost:27017/acme_dwh?authSource=admin"
MONGO_DB = "acme_dwh"
HORIZON_DAYS = 5
TRAIN_RATIO = 0.8


def get_mongo_data(collection_name: str) -> list:
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    docs = list(db[collection_name].find({}, {"_id": 0}))
    client.close()
    for doc in docs:
        for k, v in doc.items():
            if isinstance(v, datetime):
                doc[k] = v.isoformat()
    return docs


def save_to_mongo(collection_name: str, records: list) -> None:
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    col = db[collection_name]
    col.drop()
    if records:
        col.insert_many(records)
    print(f"  Saved {len(records)} records to `{collection_name}`")
    client.close()


def main():
    print("=" * 60)
    print("Acme Financial DWH — Spark ML Pipeline")
    print("=" * 60)

    # ── Start Spark session ───────────────────────────────────────
    spark = SparkSession.builder \
        .appName("AcmeFinancialDWH-MLPipeline") \
        .master("local[*]") \
        .config("spark.sql.shuffle.partitions", "4") \
        .getOrCreate()

    spark.sparkContext.setLogLevel("WARN")
    print("\n[1/5] Spark session started")

    # ── Load data ─────────────────────────────────────────────────
    print("[2/5] Loading data from MongoDB...")
    ts_docs = get_mongo_data("time_series")
    asset_docs = get_mongo_data("assets")

    if not ts_docs:
        print("  ERROR: No time-series data found.")
        spark.stop()
        return

    print(f"  Loaded {len(ts_docs)} time-series records")

    ts_df = spark.createDataFrame(ts_docs)
    ts_df = ts_df \
        .withColumn("close", F.col("close").cast("double")) \
        .withColumn("open", F.col("open").cast("double")) \
        .withColumn("high", F.col("high").cast("double")) \
        .withColumn("low", F.col("low").cast("double")) \
        .withColumn("volume", F.col("volume").cast("double")) \
        .withColumn("series_date", F.to_timestamp("series_date")) \
        .filter(F.col("close").isNotNull())

    # Latest asset metadata
    asset_df = spark.createDataFrame(asset_docs)
    asset_window = Window.partitionBy("asset_id").orderBy(F.desc("valid_from"))
    latest_assets = asset_df \
        .filter(F.col("record_status") == "active") \
        .withColumn("rn", F.row_number().over(asset_window)) \
        .filter(F.col("rn") == 1) \
        .select("asset_id", "symbol")

    # ── Feature engineering ───────────────────────────────────────
    print("[3/5] Engineering features...")

    w = Window.partitionBy("asset_id", "source_id").orderBy("series_date")

    featured = ts_df \
        .withColumn("day_index", F.row_number().over(w).cast("double")) \
        .withColumn("lag1_close", F.lag("close", 1).over(w)) \
        .withColumn("lag2_close", F.lag("close", 2).over(w)) \
        .withColumn("lag3_close", F.lag("close", 3).over(w)) \
        .withColumn("rolling_5d_avg",
                    F.avg("close").over(w.rowsBetween(-4, 0))) \
        .withColumn("rolling_10d_avg",
                    F.avg("close").over(w.rowsBetween(-9, 0))) \
        .filter(
            F.col("lag1_close").isNotNull() &
            F.col("lag2_close").isNotNull() &
            F.col("lag3_close").isNotNull()
        )

    feature_cols = ["day_index", "lag1_close", "lag2_close", "lag3_close",
                    "rolling_5d_avg", "rolling_10d_avg"]

    assembler = VectorAssembler(inputCols=feature_cols, outputCol="features")
    featured = assembler.transform(featured)

    # ── Train per asset + source ──────────────────────────────────
    print("[4/5] Training models and generating predictions...")

    combos = featured.select("asset_id", "source_id").distinct().collect()
    print(f"  Training {len(combos)} models (one per asset × source)...")

    all_results = []
    model_metrics = []

    for row in combos:
        asset_id = row["asset_id"]
        source_id = row["source_id"]

        subset = featured.filter(
            (F.col("asset_id") == asset_id) &
            (F.col("source_id") == source_id)
        ).orderBy("series_date")

        total = subset.count()
        if total < 20:
            print(f"  Skipping {asset_id}/{source_id} — not enough data ({total} records)")
            continue

        split_idx = int(total * TRAIN_RATIO)

        # Split train/test by row index
        indexed = subset.withColumn("row_num", F.row_number().over(
            Window.partitionBy("asset_id", "source_id").orderBy("series_date")
        ))
        train_df = indexed.filter(F.col("row_num") <= split_idx)
        test_df = indexed.filter(F.col("row_num") > split_idx)

        # Train Linear Regression
        lr = LinearRegression(
            featuresCol="features",
            labelCol="close",
            maxIter=50,
            regParam=0.1,
            elasticNetParam=0.0,
        )

        try:
            model = lr.fit(train_df)
            predictions = model.transform(test_df)

            evaluator = RegressionEvaluator(labelCol="close", predictionCol="prediction")
            rmse = evaluator.setMetricName("rmse").evaluate(predictions)
            r2 = evaluator.setMetricName("r2").evaluate(predictions)

            # Get symbol for display
            symbol_row = latest_assets.filter(F.col("asset_id") == asset_id).collect()
            symbol = symbol_row[0]["symbol"] if symbol_row else asset_id

            print(f"  ✓ {symbol:6s} | RMSE: {rmse:.4f} | R²: {r2:.4f} | "
                  f"Train: {split_idx} | Test: {total - split_idx}")

            model_metrics.append({
                "asset_id": asset_id,
                "source_id": source_id,
                "symbol": symbol,
                "rmse": round(rmse, 4),
                "r2": round(r2, 4),
                "train_records": split_idx,
                "test_records": total - split_idx,
                "feature_cols": feature_cols,
                "model": "LinearRegression",
                "computed_at": datetime.now(timezone.utc).isoformat(),
            })

            # Collect test predictions
            for pred_row in predictions.select(
                "asset_id", "source_id", "series_date", "close", "prediction"
            ).collect():
                d = pred_row.asDict()
                for k, v in d.items():
                    if hasattr(v, 'isoformat'):
                        d[k] = v.isoformat()
                    elif v != v:
                        d[k] = None
                d["prediction"] = round(float(d["prediction"]), 4) if d["prediction"] else None
                d["split"] = "test"
                d["computed_at"] = datetime.now(timezone.utc).isoformat()
                all_results.append(d)

            # ── Simple forecast for next HORIZON_DAYS ─────────────
            last_rows = subset.orderBy(F.desc("series_date")).limit(10).collect()
            if last_rows:
                last = last_rows[0]
                last_day_idx = float(last["day_index"])
                last_close = float(last["close"])
                last_date = last["series_date"]

                for h in range(1, HORIZON_DAYS + 1):
                    future_features = [(
                        last_day_idx + h,
                        last_close,
                        float(last_rows[min(1, len(last_rows)-1)]["close"]),
                        float(last_rows[min(2, len(last_rows)-1)]["close"]),
                        last_close,
                        last_close,
                    )]
                    future_df = spark.createDataFrame(
                        future_features,
                        ["day_index", "lag1_close", "lag2_close", "lag3_close",
                         "rolling_5d_avg", "rolling_10d_avg"]
                    )
                    future_df = assembler.transform(future_df)
                    forecast_pred = model.transform(future_df).collect()[0]["prediction"]

                    from datetime import timedelta
                    if hasattr(last_date, 'isoformat'):
                        future_date = (datetime.fromisoformat(last_date.isoformat()) +
                                      timedelta(days=h)).isoformat()
                    else:
                        future_date = str(last_date)

                    all_results.append({
                        "asset_id": asset_id,
                        "source_id": source_id,
                        "series_date": future_date,
                        "close": None,
                        "prediction": round(float(forecast_pred), 4),
                        "split": "forecast",
                        "horizon_day": h,
                        "computed_at": datetime.now(timezone.utc).isoformat(),
                    })

        except Exception as e:
            print(f"  ✗ {asset_id} failed: {e}")
            continue

    # ── Persist to MongoDB ────────────────────────────────────────
    print("\n[5/5] Saving results to MongoDB...")
    save_to_mongo("spark_ml_predictions", all_results)
    save_to_mongo("spark_ml_metrics", model_metrics)

    # ── Print model metrics summary ───────────────────────────────
    if model_metrics:
        print("\n--- Model Performance Summary ---")
        print(f"{'Symbol':<8} {'RMSE':>10} {'R²':>8} {'Train':>8} {'Test':>8}")
        print("-" * 46)
        for m in model_metrics:
            print(f"{m['symbol']:<8} {m['rmse']:>10.4f} {m['r2']:>8.4f} "
                  f"{m['train_records']:>8} {m['test_records']:>8}")

    spark.stop()
    print("\nSpark ML pipeline completed successfully.")
    print("Results saved to: spark_ml_predictions, spark_ml_metrics")


if __name__ == "__main__":
    main()

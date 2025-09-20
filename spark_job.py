import sys
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import(
    col, when, lit, to_timestamp, concat, round as spark_round
)


# Core Processing function

def process_transactions(
    trans_df: DataFrame,
    cardholders_df: DataFrame,
    time_format: str = "HH:mm:ss"
) -> DataFrame:
    
    df = trans_df.filter(
        (col("transaction_amount") > 0) &
        (col("transaction_status").isin("SUCCESS","FAILED","PENDING")) &
        col("cardholder_id").isNotNull() &
        col("merchant_id").isNotNull()
    )
    
    df =(
        df.withColumn(
            "transaction_category",
            when(col("transaction_amount") <= 100, lit("Low"))
            .when((col("transaction_amount") > 100) & (col("transaction_amount") <= 500), lit("Medium"))
            .otherwise(lit("High"))
        )
        .withColumn("transaction_timestamp", to_timestamp(col("transaction_timestamp")))
        .withColumn("high_risk",
                    (col("fraud_flag") == True) |
                    (col("transaction_amount") > 10000) |
                    (col("transaction_category") == "High")
        )
        .withColumn("merchant_info",
                    concat(col("merchant_name"),lit("-"),col("merchant_location"))
                    )
    )
    
    df = df.join(cardholders_df, on="cardholder_id", how="left")
    
    df = df.withColumn("updated_reward_points",
                       col("reward_points") + spark_round(col("transaction_amount")/10)
                       )
    
    df = df.withColumn(
        "fraud_risk_level",
        when(col("high_risk"), lit("Critical"))
        .when((col("risk_score") > 0.3) | (col("fraud_flag")), lit("High"))
        .otherwise(lit("Low"))
    )
    
    return df


# Job entrypoint
if __name__ == "__main__":
    spark = SparkSession.builder \
        .appName("Advanced Credit Card Transaction Processor") \
        .getOrCreate()
    
    # Paths and BQ Tables
    json_file_path = "gs://credit-card-data-analysis-prj/transactions/transactions_*.json"
    BQ_PROJECT_ID = "astute-impulse-448710-h3"
    BQ_DATASET = "credit_card"
    BQ_CARDHOLDERS_TABLE = f"{BQ_PROJECT_ID}.{BQ_DATASET}.cardholders_tb"
    BQ_TRANSACTIONS_TABLE = f"{BQ_PROJECT_ID}.{BQ_DATASET}.transactions"
    
    # Load Data
    cardholders_df = spark.read \
    .format("bigquery") \
    .option("table", BQ_CARDHOLDERS_TABLE) \
    .load()
    
    transactions_df = spark.read.option("multiline","true").json(json_file_path) 
    
    # Process data
    enriched_df = process_transactions(transactions_df, cardholders_df)
    
    # Write to Bigquery
    enriched_df.write.format("bigquery") \
        .option("table", BQ_TRANSACTIONS_TABLE) \
        .option("temporaryGcsBucket","bq-temp-prj-bucket") \
        .option("createDisposition", "CREATE_IF_NEEDED") \
        .option("writeDisposition", "WRITE_APPEND") \
        .save()
    
    print("Advanced Transactions Processing Completed!")
    spark.stop()
    
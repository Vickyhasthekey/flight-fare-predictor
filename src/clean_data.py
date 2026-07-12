import duckdb
import time

IN_PATH = "data/flight_prices_slim.csv"
OUT_PATH = "data/flight_prices_clean.parquet"

con = duckdb.connect()

# 先看一下清洗前的行数、以及要清洗掉的问题各自有多少行，方便你理解每一步在删什么
print("=== 清洗前统计 ===")
stats = con.execute(f"""
    SELECT
        COUNT(*) AS total_rows,
        COUNT(*) FILTER (WHERE totalFare IS NULL OR totalFare <= 20 OR totalFare >= 5000) AS bad_fare_rows,
        COUNT(*) FILTER (WHERE flightDate < searchDate) AS bad_date_rows,
        COUNT(*) FILTER (WHERE seatsRemaining < 0) AS bad_seats_rows,
        COUNT(*) FILTER (WHERE totalTravelDistance IS NULL) AS missing_distance_rows
    FROM read_csv_auto('{IN_PATH}')
""").fetchone()

total, bad_fare, bad_date, bad_seats, missing_distance = stats
print(f"总行数: {total:,}")
print(f"票价异常(<=$20 或 >=$5000 或空值): {bad_fare:,} 行")
print(f"日期逻辑错误(flightDate < searchDate): {bad_date:,} 行")
print(f"座位数为负数: {bad_seats:,} 行")
print(f"totalTravelDistance 缺失: {missing_distance:,} 行 (不删除,后面填补)")

print("\n=== 开始清洗 + 特征工程 ===")
start = time.time()

con.execute(f"""
    COPY (
        SELECT
            searchDate,
            flightDate,
            startingAirport,
            destinationAirport,
            totalFare,
            isNonStop,
            seatsRemaining,
            COALESCE(
                totalTravelDistance,
                MEDIAN(totalTravelDistance) OVER (PARTITION BY startingAirport, destinationAirport)
            ) AS totalTravelDistance,
            isBasicEconomy,
            date_diff('day', searchDate, flightDate) AS days_before_departure,
            dayofweek(flightDate) AS departure_day_of_week,
            month(flightDate) AS departure_month,
            dayofweek(searchDate) AS search_day_of_week
        FROM read_csv_auto('{IN_PATH}')
        WHERE totalFare > 20 AND totalFare < 5000
          AND flightDate >= searchDate
          AND (seatsRemaining IS NULL OR seatsRemaining >= 0)
    ) TO '{OUT_PATH}' (FORMAT PARQUET)
""")

elapsed = time.time() - start
print(f"清洗完成，耗时 {elapsed:.1f} 秒")

# 清洗后统计
after = con.execute(f"SELECT COUNT(*) FROM '{OUT_PATH}'").fetchone()[0]
print(f"\n清洗后行数: {after:,} (原始 {total:,}，删除了 {total - after:,} 行，占比 {(total-after)/total*100:.2f}%)")

import os
size_mb = os.path.getsize(OUT_PATH) / (1024 * 1024)
print(f"输出文件大小: {size_mb:.1f} MB (原始 csv 是 {os.path.getsize(IN_PATH) / (1024**3):.1f} GB)")

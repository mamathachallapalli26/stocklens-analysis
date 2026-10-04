-- StockLens SQL (SQLite; for MySQL use YEAR(date) instead of strftime)
-- Tables bajaj_auto, eicher_motors, hero_motocorp, infosys, tcs, tvs_motors are created by clean_load.py
-- (dates converted to YYYY-MM-DD, duplicates removed, rows without date/price removed).

-- ===== 1. DATA QUALITY CHECKS =====
-- Missing values (deliverable_qty is the only gap: 1 row per stock)
SELECT 'bajaj_auto' AS stock, date FROM bajaj_auto WHERE deliverable_qty IS NULL
UNION ALL SELECT 'eicher_motors', date FROM eicher_motors WHERE deliverable_qty IS NULL
UNION ALL SELECT 'hero_motocorp', date FROM hero_motocorp WHERE deliverable_qty IS NULL
UNION ALL SELECT 'infosys', date FROM infosys WHERE deliverable_qty IS NULL
UNION ALL SELECT 'tcs', date FROM tcs WHERE deliverable_qty IS NULL
UNION ALL SELECT 'tvs_motors', date FROM tvs_motors WHERE deliverable_qty IS NULL;

-- Duplicate dates (expect 0 rows)
SELECT 'bajaj_auto' AS stock, date, COUNT(*) n FROM bajaj_auto GROUP BY date HAVING n > 1;

-- ===== 2. EXPLORE =====
SELECT COUNT(*) trading_days, MIN(date) first_day, MAX(date) last_day FROM bajaj_auto;
SELECT date, close_price FROM eicher_motors ORDER BY close_price DESC LIMIT 5;
SELECT strftime('%Y', date) AS year, ROUND(AVG(close_price), 2) avg_close FROM tcs GROUP BY year ORDER BY year;

-- ===== 3. MOVING AVERAGES (bajaj1) =====
DROP TABLE IF EXISTS bajaj1;
CREATE TABLE bajaj1 AS
SELECT date, close_price,
  CASE WHEN ROW_NUMBER() OVER (ORDER BY date) >= 20
       THEN ROUND(AVG(close_price) OVER (ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW), 2) END AS ma20,
  CASE WHEN ROW_NUMBER() OVER (ORDER BY date) >= 50
       THEN ROUND(AVG(close_price) OVER (ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW), 2) END AS ma50
FROM bajaj_auto;

-- ===== 4. MASTER TABLE =====
DROP TABLE IF EXISTS master_table;
CREATE TABLE master_table AS
SELECT b.date, b.close_price AS bajaj, t.close_price AS tcs, v.close_price AS tvs,
       i.close_price AS infosys, e.close_price AS eicher, h.close_price AS hero
FROM bajaj_auto b
JOIN tcs t ON t.date = b.date
JOIN tvs_motors v ON v.date = b.date
JOIN infosys i ON i.date = b.date
JOIN eicher_motors e ON e.date = b.date
JOIN hero_motocorp h ON h.date = b.date;

-- ===== 5. GOLDEN CROSS SIGNALS (bajaj2) =====
DROP TABLE IF EXISTS bajaj2;
CREATE TABLE bajaj2 AS
WITH t AS (
  SELECT date, close_price, ma20, ma50,
         LAG(ma20) OVER (ORDER BY date) AS prev_ma20,
         LAG(ma50) OVER (ORDER BY date) AS prev_ma50
  FROM bajaj1)
SELECT date, close_price,
  CASE WHEN ma20 IS NULL OR ma50 IS NULL OR prev_ma20 IS NULL OR prev_ma50 IS NULL THEN 'Hold'
       WHEN ma20 > ma50 AND prev_ma20 <= prev_ma50 THEN 'Buy'
       WHEN ma20 < ma50 AND prev_ma20 >= prev_ma50 THEN 'Sell'
       ELSE 'Hold' END AS signal
FROM t;

SELECT signal, COUNT(*) days FROM bajaj2 GROUP BY signal ORDER BY signal;
SELECT signal FROM bajaj2 WHERE date = '2018-06-21';

-- ===== 6. ALL SIX STOCKS IN ONE QUERY =====
DROP VIEW IF EXISTS prices;
CREATE VIEW prices AS
SELECT 'Bajaj Auto' stock, date, close_price FROM bajaj_auto UNION ALL
SELECT 'Eicher Motors', date, close_price FROM eicher_motors UNION ALL
SELECT 'Hero Motocorp', date, close_price FROM hero_motocorp UNION ALL
SELECT 'Infosys', date, close_price FROM infosys UNION ALL
SELECT 'TCS', date, close_price FROM tcs UNION ALL
SELECT 'TVS Motors', date, close_price FROM tvs_motors;

WITH ma AS (
  SELECT stock, date, close_price,
    CASE WHEN ROW_NUMBER() OVER w >= 20 THEN AVG(close_price) OVER (PARTITION BY stock ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) END ma20,
    CASE WHEN ROW_NUMBER() OVER w >= 50 THEN AVG(close_price) OVER (PARTITION BY stock ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) END ma50
  FROM prices WINDOW w AS (PARTITION BY stock ORDER BY date)),
lagged AS (
  SELECT *, LAG(ma20) OVER (PARTITION BY stock ORDER BY date) p20,
            LAG(ma50) OVER (PARTITION BY stock ORDER BY date) p50 FROM ma),
sig AS (
  SELECT stock, date,
    CASE WHEN ma20 IS NULL OR ma50 IS NULL OR p20 IS NULL OR p50 IS NULL THEN 'Hold'
         WHEN ma20 > ma50 AND p20 <= p50 THEN 'Buy'
         WHEN ma20 < ma50 AND p20 >= p50 THEN 'Sell' ELSE 'Hold' END signal FROM lagged),
latest AS (
  SELECT stock, date, signal, ROW_NUMBER() OVER (PARTITION BY stock ORDER BY date DESC) rn
  FROM sig WHERE signal <> 'Hold')
SELECT s.stock, SUM(s.signal = 'Buy') buys, SUM(s.signal = 'Sell') sells,
       l.date last_signal_date, l.signal last_signal
FROM sig s JOIN latest l ON l.stock = s.stock AND l.rn = 1
GROUP BY s.stock ORDER BY s.stock;

-- ===== 7. WHO WENT UP? =====
WITH ends AS (SELECT stock, MIN(date) d0, MAX(date) d1 FROM prices GROUP BY stock)
SELECT e.stock, a.close_price first_close, b.close_price last_close,
       ROUND(100.0 * (b.close_price - a.close_price) / a.close_price, 1) pct_change
FROM ends e JOIN prices a ON a.stock = e.stock AND a.date = e.d0
            JOIN prices b ON b.stock = e.stock AND b.date = e.d1
ORDER BY pct_change DESC;

-- ===== 8. DATA TRAP: worst day per stock (bonus issues / splits show up here) =====
WITH mv AS (
  SELECT stock, date, close_price,
         100.0 * (close_price / LAG(close_price) OVER (PARTITION BY stock ORDER BY date) - 1) pct_move
  FROM prices),
r AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY stock ORDER BY pct_move) rn FROM mv WHERE pct_move IS NOT NULL)
SELECT stock, date, close_price, ROUND(pct_move, 1) pct_move FROM r WHERE rn = 1 ORDER BY pct_move;

-- ===== 9. FIX IT: adjust for 1:1 bonus issues (TCS 2018-05-31, Infosys 2015-06-15) =====
DROP VIEW IF EXISTS adjusted;
CREATE VIEW adjusted AS
SELECT 'TCS' stock, date, CASE WHEN date < '2018-05-31' THEN close_price / 2 ELSE close_price END adj_close FROM tcs
UNION ALL
SELECT 'Infosys', date, CASE WHEN date < '2015-06-15' THEN close_price / 2 ELSE close_price END FROM infosys;

SELECT stock,
  ROUND(100.0 * (MAX(CASE WHEN date = '2018-07-31' THEN adj_close END) /
                 MAX(CASE WHEN date = '2015-01-01' THEN adj_close END) - 1), 1) AS adjusted_pct_change
FROM adjusted GROUP BY stock ORDER BY stock;
"""
run_pipeline.py — Sequential download + sector-metrics pipeline
================================================================

Usage
-----
    python scripts/run_pipeline.py                          # default settings
    python scripts/run_pipeline.py --tickers path/to/file  # custom ticker file
    python scripts/run_pipeline.py --sleep 4 --resume      # 4-second sleep, skip done sectors
    python scripts/run_pipeline.py --sectors Technology Finance  # subset of sectors
    python scripts/run_pipeline.py --no-benchmarks          # skip benchmark file generation

Ticker file format (tab-separated, same as sector_ticker.txt):
    ticker  sector  name  marginabile
    AAPL    Technology  Apple Inc  1
    ENI.MI  Energy  Eni SpA  1

Output
------
    financial_data/
        metrics.xlsx                  — all tickers, all years (input to chains.py)
        eval_metrics.xlsx
        composite_scores.xlsx
        red_flags.xlsx
        raw_red_flags.xlsx
        metrics_by_sectors.xlsx       — per-sector peer averages (read by get_market_metrics)
        eval_metrics_by_sectors.xlsx  — per-sector valuation averages
        failed_tickers.log            — tickers skipped due to empty download

Pipeline stages
---------------
  1. Download  — one ticker at a time, sequential, with configurable sleep
  2. Evaluate  — FundamentalTraderAssistant per ticker, sector-specific weights
  3. Export    — five canonical Excel files via export_financial_results()
  4. Benchmark — sector averages written to metrics_by_sectors.xlsx and
                 eval_metrics_by_sectors.xlsx so chains.py can compare any
                 ticker against its peer group via get_market_metrics()

Design invariants
-----------------
- One ticker downloaded at a time (sequential) to respect yfinance rate limits.
- Each ticker is evaluated using the weights for its own sector from config.sec_sector_metric_weights.
- Unknown sectors fall back to "Default" with a warning.
- On --resume, sectors whose checkpoint file already exists are skipped entirely.
- Benchmark files are always recomputed from the full metrics.xlsx after export,
  so they reflect all tickers — including those from a previous run.
"""

import argparse
import logging
import os
import re
import time
from typing import Optional

import pandas as pd

# --- package imports --------------------------------------------------------
from financialtools.analysis import build_weights
from financialtools.config import sec_sector_metric_weights
from financialtools.processor import Downloader
from financialtools.evaluator import empty_result
from financialtools.wrappers import export_financial_results, merge_results

# ---------------------------------------------------------------------------
# Logging: script-level logger; wrappers.py configures the file handlers when
# it is imported above.  We add a StreamHandler here for console progress.
# ---------------------------------------------------------------------------
logger = logging.getLogger("run_pipeline")
logger.setLevel(logging.DEBUG)

_console = logging.StreamHandler()
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_console)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_TICKERS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "financialtools", "data", "sector_ticker.txt"
)
DEFAULT_OUTPUT_DIR = "financial_data"
DEFAULT_SLEEP_SECONDS = 3
FAILED_LOG_NAME = "failed_tickers.log"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sector_done(sector: str, output_dir: str) -> bool:
    """Return True if a per-sector composite_scores checkpoint already exists."""
    checkpoint = os.path.join(output_dir, f"_checkpoint_{sector}.done")
    return os.path.isfile(checkpoint)


def _mark_sector_done(sector: str, output_dir: str) -> None:
    """Write a zero-byte sentinel so --resume can skip this sector next run."""
    checkpoint = os.path.join(output_dir, f"_checkpoint_{sector}.done")
    open(checkpoint, "w").close()


def _load_ticker_list(filepath: str) -> pd.DataFrame:
    """
    Load the ticker list from a tab-separated file.

    Expected columns: ticker, sector.  Extra columns are allowed and ignored.
    Returns a DataFrame with columns [ticker, sector].
    """
    df = pd.read_csv(filepath, sep="\t")
    return df[["ticker", "sector"]]


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def download_sector(
    tickers: list[str],
    sleep_seconds: float,
) -> dict[str, pd.DataFrame]:
    """
    Download merged financial data for each ticker in the list, sequentially.

    Returns
    -------
    dict[str, pd.DataFrame]
        {ticker: merged_df} — tickers with empty DataFrames are still included
        so the caller can log them as failures.
    """
    results: dict[str, pd.DataFrame] = {}
    total = len(tickers)

    for i, ticker in enumerate(tickers, start=1):
        logger.info(f"  [{i}/{total}] Downloading {ticker} …")
        try:
            time.sleep(sleep_seconds)
            d = Downloader.from_ticker(ticker)
            df = d.get_merged_data()

            # ── Enrich: company name (mirrors wrappers.py / data_tools.py) ───
            # Sector is already known from the ticker file; only company_name
            # requires the extra get_info_data() call.
            info_df = d.get_info_data()
            if not info_df.empty and "longName" in info_df.columns:
                company_name = info_df["longName"].str.lower().to_string(index=False).strip()
            else:
                company_name = ticker.lower()
                logger.warning(
                    f"  [{i}/{total}] {ticker}: longName not found in info; using ticker as name"
                )

            if not df.empty:
                df["company_name"] = company_name

            results[ticker] = df
            if df.empty:
                logger.warning(f"  [{i}/{total}] {ticker}: download succeeded but merged data is empty")
            else:
                logger.info(f"  [{i}/{total}] {ticker}: {len(df)} rows")
        except Exception as exc:
            logger.error(f"  [{i}/{total}] {ticker}: unexpected error — {exc}", exc_info=True)
            results[ticker] = pd.DataFrame()

    return results


def evaluate_sector(
    ticker_data: dict[str, pd.DataFrame],
    sector: str,
) -> dict[str, dict]:
    """
    Run FundamentalTraderAssistant.evaluate() for each ticker whose data is non-empty.

    Parameters
    ----------
    ticker_data : {ticker: merged_df}
    sector      : sector name (used to pick weights)

    Returns
    -------
    {ticker: evaluate_result_dict}
        Tickers with empty DataFrames get empty_result() directly.
    """
    from financialtools.processor import FundamentalMetricsEvaluator
    from financialtools.exceptions import EvaluationError

    weights = build_weights(sector)
    results: dict[str, dict] = {}

    for ticker, df in ticker_data.items():
        if df.empty:
            results[ticker] = empty_result()
            continue
        try:
            assistant = FundamentalMetricsEvaluator(data=df, weights=weights)
            results[ticker] = assistant.evaluate()
        except EvaluationError as exc:
            logger.error(f"  {ticker}: EvaluationError — {exc}")
            results[ticker] = empty_result()
        except Exception as exc:
            logger.error(f"  {ticker}: unexpected evaluation error — {exc}", exc_info=True)
            results[ticker] = empty_result()

    return results


def collect_failed(ticker_data: dict[str, pd.DataFrame]) -> list[str]:
    """Return tickers whose merged DataFrame is empty (download produced no data)."""
    return [t for t, df in ticker_data.items() if df.empty]


# ---------------------------------------------------------------------------
# Sector benchmarks
# ---------------------------------------------------------------------------

def compute_sector_benchmarks(output_dir: str) -> None:
    """
    Compute per-sector peer-average metrics and write the two benchmark files
    that chains.py reads via get_market_metrics().

    Reads
    -----
    - {output_dir}/metrics.xlsx      — wide: ticker, time, sector, <metric cols>
    - {output_dir}/eval_metrics.xlsx — wide: ticker, time, sector, <valuation cols>

    Writes
    ------
    - {output_dir}/metrics_by_sectors.xlsx      — columns: sector, metrics, market_value, time
    - {output_dir}/eval_metrics_by_sectors.xlsx — same schema

    Formula: market_value = mean(metric) across all tickers in the sector, per year.
    NaN values are excluded from the mean (skipna=True, pandas default).

    Invariant: these files must exist before calling get_stock_evaluation_report()
    or chains.py will raise SectorNotFoundError on every ticker.
    """
    _ID_VARS = {"ticker", "time", "sector"}

    for source_file, dest_file in (
        ("metrics.xlsx",      "metrics_by_sectors.xlsx"),
        ("eval_metrics.xlsx", "eval_metrics_by_sectors.xlsx"),
    ):
        source_path = os.path.join(output_dir, source_file)
        dest_path   = os.path.join(output_dir, dest_file)

        if not os.path.isfile(source_path):
            logger.warning(f"Benchmark: {source_path} not found — skipping {dest_file}")
            continue

        try:
            wide = pd.read_excel(source_path, sheet_name="sheet1")

            # Derive metric columns dynamically — same logic as processor.evaluate()
            metric_cols = [c for c in wide.columns if c not in _ID_VARS]

            if not metric_cols:
                logger.warning(f"Benchmark: no metric columns found in {source_file} — skipping")
                continue

            long = wide.melt(
                id_vars=["sector", "time"],
                value_vars=metric_cols,
                var_name="metrics",
                value_name="market_value",
            )

            benchmarks = (
                long
                .groupby(["sector", "metrics", "time"], dropna=False, sort=False)
                .agg(market_value=("market_value", "mean"))
                .reset_index()
            )

            with pd.ExcelWriter(dest_path, engine="openpyxl") as writer:
                benchmarks.to_excel(writer, sheet_name="sheet1", index=False)

            n_sectors = benchmarks["sector"].nunique()
            n_metrics = benchmarks["metrics"].nunique()
            logger.info(
                f"Benchmark: wrote {dest_file} "
                f"({n_sectors} sectors × {n_metrics} metrics)"
            )

        except Exception as exc:
            logger.error(f"Benchmark: failed to build {dest_file} — {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(
    tickers_file: str,
    output_dir: str,
    sleep_seconds: float,
    resume: bool,
    sectors_filter: Optional[list[str]],
    benchmarks: bool = True,
) -> None:
    """
    Main pipeline:
      1. Load ticker list grouped by sector.
      2. For each sector (optionally filtered, optionally skipped if --resume):
         a. Download merged data for all tickers sequentially.
         b. Evaluate metrics using sector-specific weights.
         c. Accumulate results.
      3. Export all results to financial_data/*.xlsx.
      4. Compute sector benchmark files (metrics_by_sectors.xlsx,
         eval_metrics_by_sectors.xlsx) — required by chains.py.
      5. Write failed_tickers.log.
    """
    os.makedirs(output_dir, exist_ok=True)

    # --- load tickers -------------------------------------------------------
    ticker_df = _load_ticker_list(tickers_file)
    logger.info(f"Loaded {len(ticker_df)} tickers from {tickers_file}")

    all_sectors = sorted(ticker_df["sector"].unique().tolist())
    if sectors_filter:
        all_sectors = [s for s in all_sectors if s in sectors_filter]
        logger.info(f"Filtered to {len(all_sectors)} sector(s): {all_sectors}")

    # --- pipeline loop per sector -------------------------------------------
    all_results: dict[str, dict] = {}   # ticker → evaluate() result dict
    all_failed: list[str] = []

    for sector in all_sectors:
        sector_tickers = ticker_df.loc[
            ticker_df["sector"] == sector, "ticker"
        ].tolist()

        if resume and _sector_done(sector, output_dir):
            logger.info(f"[SKIP] {sector} ({len(sector_tickers)} tickers) — checkpoint found")
            continue

        logger.info(
            f"\n{'='*60}\n"
            f"SECTOR: {sector}  ({len(sector_tickers)} tickers)\n"
            f"{'='*60}"
        )

        # Stage 1: download
        ticker_data = download_sector(sector_tickers, sleep_seconds)

        # Track failures before evaluation
        failed = collect_failed(ticker_data)
        if failed:
            logger.warning(f"  Empty data for {len(failed)} ticker(s): {failed}")
        all_failed.extend(failed)

        # Stage 2: evaluate
        sector_results = evaluate_sector(ticker_data, sector)
        all_results.update(sector_results)

        # Mark sector complete for --resume
        _mark_sector_done(sector, output_dir)
        logger.info(f"  Sector {sector} complete.")

    # --- export all results -------------------------------------------------
    if not all_results:
        logger.warning("No results to export — all sectors were skipped or all downloads failed.")
        return

    logger.info(f"\nExporting {len(all_results)} ticker results to {output_dir}/ …")
    export_financial_results(
        results=list(all_results.values()),
        output_dir=output_dir,
        sheet_name="sheet1",
    )

    # --- compute sector benchmarks ------------------------------------------
    # Must run after export so metrics.xlsx / eval_metrics.xlsx exist.
    # These files are what chains.py reads via get_market_metrics().
    if benchmarks:
        logger.info("\nComputing sector benchmarks …")
        compute_sector_benchmarks(output_dir)
    else:
        logger.info("Skipping benchmark computation (--no-benchmarks).")

    # --- write failed log ---------------------------------------------------
    if all_failed:
        failed_path = os.path.join(output_dir, FAILED_LOG_NAME)
        with open(failed_path, "w") as f:
            f.write("\n".join(all_failed) + "\n")
        logger.warning(
            f"{len(all_failed)} ticker(s) produced no data — see {failed_path}"
        )

    logger.info("Pipeline complete.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download yfinance fundamentals and compute sector metrics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--tickers",
        default=DEFAULT_TICKERS_FILE,
        metavar="PATH",
        help="Path to tab-separated ticker file (default: financialtools/data/sector_ticker.txt)",
    )
    p.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=f"Output directory for Excel files (default: {DEFAULT_OUTPUT_DIR})",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        metavar="SECONDS",
        help=f"Sleep between ticker downloads in seconds (default: {DEFAULT_SLEEP_SECONDS})",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip sectors whose checkpoint file already exists in output-dir",
    )
    p.add_argument(
        "--sectors",
        nargs="+",
        metavar="SECTOR",
        default=None,
        help="Run only these sectors (space-separated). Default: all sectors in ticker file.",
    )
    p.add_argument(
        "--no-benchmarks",
        action="store_true",
        dest="no_benchmarks",
        help="Skip writing metrics_by_sectors.xlsx and eval_metrics_by_sectors.xlsx.",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(
        tickers_file=args.tickers,
        output_dir=args.output_dir,
        sleep_seconds=args.sleep,
        resume=args.resume,
        sectors_filter=args.sectors,
        benchmarks=not args.no_benchmarks,
    )

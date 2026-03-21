import json
import time

import pandas as pd


def export_to_csv(df, path):
    """Export a DataFrame to a CSV file."""
    try:
        df.to_csv(path, index=False)
        print(f"Data exported to {path}")
    except Exception as e:
        print(f"Error exporting to CSV: {e}")


def export_to_xlsx(df, path, sheet_name):
    """Export a DataFrame to an Excel (.xlsx) file."""
    try:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
        print(f"Data exported to {path}")
    except Exception as e:
        print(f"Error exporting to Excel: {e}")


def dataframe_to_json(df):
    """
    Converts a pandas DataFrame to a JSON-formatted string.

    Parameters:
        df (pd.DataFrame): The DataFrame to convert.

    Returns:
        str: JSON-formatted string.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Input must be a pandas DataFrame.")

    df_dict = df.to_dict(orient='records')
    json_str = json.dumps(df_dict)

    return json_str


def flatten_weights(weights: dict) -> dict:
    """
    Flattens sector weights.
    Supports both grouped (by category) and flat dictionaries.

    Example:
        Input (grouped):
        {
            "Profitability & Margins": {"GrossMargin": 10, "OperatingMargin": 12},
            "Return": {"ROA": 10, "ROE": 12}
        }

        Output:
        {
            "GrossMargin": 10, "OperatingMargin": 12,
            "ROA": 10, "ROE": 12
        }
    """
    try:
        flat = {}
        for key, value in weights.items():
            if isinstance(value, dict):  # category grouping
                flat.update(value)
            else:  # already flat
                flat[key] = value
        return flat
    except Exception as e:
        print(f"Error flattening weights: {e}")
        return {}


def get_ticker_profile(ticker: str) -> pd.DataFrame:
    """
    Fetches key profile information for a given stock ticker from Yahoo Finance.

    Parameters:
    - ticker (str): The stock ticker symbol (e.g., 'FCT.MI').

    Returns:
    - pd.DataFrame: A single-row DataFrame with selected profile fields.
    """
    import yfinance as yf  # deferred: yfinance is only required for this function
    stock = yf.Ticker(ticker)
    info = stock.info

    data = {
        "shortName": info.get("shortName"),
        "industry": info.get("industry"),
        "sectorKey": info.get("sectorKey"),
        "beta": info.get("beta"),
        "longBusinessSummary": info.get("longBusinessSummary")
    }

    return pd.DataFrame([data])


def enrich_tickers(df: pd.DataFrame, ticker_column: str = "ticker") -> pd.DataFrame:
    """
    Applies get_ticker_profile to each ticker in the DataFrame and combines results.

    Parameters:
    - df (pd.DataFrame): Input DataFrame with a column of ticker symbols.
    - ticker_column (str): Name of the column containing ticker symbols.

    Returns:
    - pd.DataFrame: Combined DataFrame with profile info for each ticker.
    """
    profiles = []
    for ticker in df[ticker_column]:
        try:
            profile_df = get_ticker_profile(ticker)
            profile_df["ticker"] = ticker  # Add ticker for traceability
            profiles.append(profile_df)
        except Exception as e:
            print(f"Error fetching data for {ticker}: {e}")
        time.sleep(0.5)  # Pause to avoid overwhelming the API

    return pd.concat(profiles, ignore_index=True)

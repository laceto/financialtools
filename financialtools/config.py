# config.py placeholder

import pandas as pd

grouped_weights = {
    "Profitability & Margins": {
        "GrossMargin": 8,
        "OperatingMargin": 12,
        "NetProfitMargin": 8,
        "EBITDAMargin": 10
    },
    "Returns": {
        "ROA": 10,
        "ROE": 12
    },
    "Leverage & Solvency": {
        "DebtToEquity": 12,
        "DebtToAssets": 10
    },
    "Liquidity": {
        "CurrentRatio": 8
    },
    "Cash Flow Strength": {
        "FCFToRevenue": 10,
        "FCFYield": 10
    }
}


sector_metric_weights = {
    "Commercial Services": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8
    },
    "Communications": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 10, "DebtToAssets": 8,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "Consumer Durables": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8
    },
    "Consumer Non-Durables": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 10, "DebtToAssets": 8,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "Consumer Services": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 10, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 9, "FCFYield": 9
    },
    "Distribution Services": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 10, "ROA": 12, "ROE": 12,
        "DebtToEquity": 12, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 9, "FCFYield": 9
    },
    "Electronic Technology": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 12,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 8, "DebtToAssets": 8,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8
    },
    "Energy Minerals": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "DebtToAssets": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "Finance": {
        "GrossMargin": 0, "OperatingMargin": 8, "NetProfitMargin": 12,
        "EBITDAMargin": 0, "ROA": 12, "ROE": 16,
        "DebtToEquity": 20, "DebtToAssets": 16,
        "CurrentRatio": 0, "FCFToRevenue": 8, "FCFYield": 8
    },
    "Health Services": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 10, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 9, "FCFYield": 9
    },
    "Health Technology": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 12,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 8, "DebtToAssets": 8,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 10
    },
    "Industrial Services": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 10, "ROA": 12, "ROE": 12,
        "DebtToEquity": 12, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "Non-Energy Minerals": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "DebtToAssets": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "Process Industries": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8
    },
    "Producer Manufacturing": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8
    },
    "Retail Trade": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 12, "ROE": 12,
        "DebtToEquity": 10, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8
    },
    "Technology Services": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 12,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 8, "DebtToAssets": 8,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 10
    },
    "Transportation": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "DebtToAssets": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "Utilities": {
        "GrossMargin": 8, "OperatingMargin": 10, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 14, "DebtToAssets": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "Default": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    }
}

sec_sector_metric_weights = {
    "basic-materials": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "DebtToAssets": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "communication-services": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 10, "DebtToAssets": 8,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "consumer-cyclical": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8
    },
    "consumer-defensive": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 10, "DebtToAssets": 8,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "energy": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "DebtToAssets": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "financial-services": {
        "GrossMargin": 0, "OperatingMargin": 8, "NetProfitMargin": 12,
        "EBITDAMargin": 0, "ROA": 12, "ROE": 16,
        "DebtToEquity": 20, "DebtToAssets": 16,
        "CurrentRatio": 0, "FCFToRevenue": 8, "FCFYield": 8
    },
    "healthcare": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 12,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 8, "DebtToAssets": 8,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 10
    },
    "industrials": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8
    },
    "real-estate": {
        "GrossMargin": 0, "OperatingMargin": 8, "NetProfitMargin": 10,
        "EBITDAMargin": 0, "ROA": 12, "ROE": 12,
        "DebtToEquity": 16, "DebtToAssets": 14,
        "CurrentRatio": 0, "FCFToRevenue": 8, "FCFYield": 8
    },
    "technology": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 12,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 8, "DebtToAssets": 8,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 10
    },
    "utilities": {
        "GrossMargin": 8, "OperatingMargin": 10, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 14, "DebtToAssets": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    },
    "default": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "DebtToAssets": 10,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10
    }
}


weights = (
        pd.read_excel('financialtools/data/weights.xlsx')
        .melt(id_vars=["sector"], var_name="metrics", value_name="Weight")
    )


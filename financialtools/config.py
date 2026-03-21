# Standard extension block added to most sectors (sum ≈ 52).
# Finance / financial-services and real-estate use custom blocks
# (zero-weight metrics that have no meaning for those business models).
_STD_EXT = {
    "QuickRatio": 4, "CashRatio": 2, "WorkingCapitalRatio": 2,
    "DebtRatio": 4, "EquityRatio": 2, "NetDebtToEBITDA": 6, "InterestCoverage": 6,
    "ROIC": 8, "AssetTurnover": 4,
    "OCFRatio": 4, "FCFMargin": 4, "CashConversion": 4, "CapexRatio": 2,
}

# Finance / financial-services: liquidity ratios and NetDebtToEBITDA have no
# meaning for banks/insurers, so they are zero-weighted (not excluded) to keep
# the dict schema uniform across all sectors.
_FIN_EXT = {
    "QuickRatio": 0, "CashRatio": 0, "WorkingCapitalRatio": 0,
    "DebtRatio": 0, "EquityRatio": 6, "NetDebtToEBITDA": 0, "InterestCoverage": 0,
    "ROIC": 12, "AssetTurnover": 6,
    "OCFRatio": 0, "FCFMargin": 8, "CashConversion": 6, "CapexRatio": 0,
}

# Real-estate: current-ratio-style liquidity metrics are not meaningful;
# debt structure and NOI-based cash metrics take precedence.
_RE_EXT = {
    "QuickRatio": 0, "CashRatio": 0, "WorkingCapitalRatio": 0,
    "DebtRatio": 6, "EquityRatio": 4, "NetDebtToEBITDA": 10, "InterestCoverage": 8,
    "ROIC": 8, "AssetTurnover": 2,
    "OCFRatio": 4, "FCFMargin": 6, "CashConversion": 4, "CapexRatio": 4,
}

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
        "FCFtoDebt": 10
    },
    "Liquidity": {
        "CurrentRatio": 8
    },
    "Cash Flow Strength": {
        "FCFToRevenue": 10,
        "FCFYield": 10
    },
    "Extended Metrics": {
        "QuickRatio": 4, "CashRatio": 2, "WorkingCapitalRatio": 2,
        "DebtRatio": 4, "EquityRatio": 2, "NetDebtToEBITDA": 6, "InterestCoverage": 6,
        "ROIC": 8, "AssetTurnover": 4,
        "OCFRatio": 4, "FCFMargin": 4, "CashConversion": 4, "CapexRatio": 2,
    },
}


sector_metric_weights = {
    "Commercial Services": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8,
        **_STD_EXT,
    },
    "Communications": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 10, "FCFtoDebt": 8,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "Consumer Durables": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8,
        **_STD_EXT,
    },
    "Consumer Non-Durables": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 10, "FCFtoDebt": 8,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "Consumer Services": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 10, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 9, "FCFYield": 9,
        **_STD_EXT,
    },
    "Distribution Services": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 10, "ROA": 12, "ROE": 12,
        "DebtToEquity": 12, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 9, "FCFYield": 9,
        **_STD_EXT,
    },
    "Electronic Technology": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 12,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 8, "FCFtoDebt": 8,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8,
        **_STD_EXT,
    },
    "Energy Minerals": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "FCFtoDebt": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "Finance": {
        "GrossMargin": 0, "OperatingMargin": 8, "NetProfitMargin": 12,
        "EBITDAMargin": 0, "ROA": 12, "ROE": 16,
        "DebtToEquity": 20, "FCFtoDebt": 16,
        "CurrentRatio": 0, "FCFToRevenue": 8, "FCFYield": 8,
        **_FIN_EXT,
    },
    "Health Services": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 10, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 9, "FCFYield": 9,
        **_STD_EXT,
    },
    "Health Technology": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 12,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 8, "FCFtoDebt": 8,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 10,
        **_STD_EXT,
    },
    "Industrial Services": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 10, "ROA": 12, "ROE": 12,
        "DebtToEquity": 12, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "Non-Energy Minerals": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "FCFtoDebt": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "Process Industries": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8,
        **_STD_EXT,
    },
    "Producer Manufacturing": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8,
        **_STD_EXT,
    },
    "Retail Trade": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 12, "ROE": 12,
        "DebtToEquity": 10, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8,
        **_STD_EXT,
    },
    "Technology Services": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 12,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 8, "FCFtoDebt": 8,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 10,
        **_STD_EXT,
    },
    "Transportation": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "FCFtoDebt": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "Utilities": {
        "GrossMargin": 8, "OperatingMargin": 10, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 14, "FCFtoDebt": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "Default": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
}

sec_sector_metric_weights = {
    "basic-materials": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "FCFtoDebt": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "communication-services": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 10, "FCFtoDebt": 8,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "consumer-cyclical": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8,
        **_STD_EXT,
    },
    "consumer-defensive": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 10, "FCFtoDebt": 8,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "energy": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 12, "FCFtoDebt": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "financial-services": {
        "GrossMargin": 0, "OperatingMargin": 8, "NetProfitMargin": 12,
        "EBITDAMargin": 0, "ROA": 12, "ROE": 16,
        "DebtToEquity": 20, "FCFtoDebt": 16,
        "CurrentRatio": 0, "FCFToRevenue": 8, "FCFYield": 8,
        **_FIN_EXT,
    },
    "healthcare": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 12,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 8, "FCFtoDebt": 8,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 10,
        **_STD_EXT,
    },
    "industrials": {
        "GrossMargin": 10, "OperatingMargin": 12, "NetProfitMargin": 10,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 8,
        **_STD_EXT,
    },
    "real-estate": {
        "GrossMargin": 0, "OperatingMargin": 8, "NetProfitMargin": 10,
        "EBITDAMargin": 0, "ROA": 12, "ROE": 12,
        "DebtToEquity": 16, "FCFtoDebt": 14,
        "CurrentRatio": 0, "FCFToRevenue": 8, "FCFYield": 8,
        **_RE_EXT,
    },
    "technology": {
        "GrossMargin": 12, "OperatingMargin": 12, "NetProfitMargin": 12,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 10,
        "DebtToEquity": 8, "FCFtoDebt": 8,
        "CurrentRatio": 8, "FCFToRevenue": 8, "FCFYield": 10,
        **_STD_EXT,
    },
    "utilities": {
        "GrossMargin": 8, "OperatingMargin": 10, "NetProfitMargin": 8,
        "EBITDAMargin": 12, "ROA": 10, "ROE": 10,
        "DebtToEquity": 14, "FCFtoDebt": 12,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
    "default": {
        "GrossMargin": 8, "OperatingMargin": 12, "NetProfitMargin": 8,
        "EBITDAMargin": 10, "ROA": 10, "ROE": 12,
        "DebtToEquity": 12, "FCFtoDebt": 10,
        "CurrentRatio": 8, "FCFToRevenue": 10, "FCFYield": 10,
        **_STD_EXT,
    },
}

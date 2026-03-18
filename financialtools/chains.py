import os

from dotenv import load_dotenv
load_dotenv()

from langchain_core.output_parsers import PydanticOutputParser
from langchain.output_parsers import OutputFixingParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from financialtools.wrappers import read_financial_results
from financialtools.pydantic_models import StockRegimeAssessment
from financialtools.prompts import system_prompt_StockRegimeAssessment
from financialtools.utils import get_sector_for_ticker, get_market_metrics, dataframe_to_json

def get_stock_evaluation_report(
    ticker: str,
    year: int | None = None,
    base_dir: str = "financial_data",
    sector_file: str = "financialtools/data/sector_ticker.txt",
) -> "StockRegimeAssessment":
    """
    Run the full LLM fundamental regime assessment for a ticker.

    Args:
        ticker:      Ticker symbol (e.g. "AAPL", "ENI.MI").
        year:        Optional year to focus the assessment on. If None, uses all years.
        base_dir:    Directory containing the evaluation output files
                     (metrics.xlsx, composite_scores.xlsx, red_flags.xlsx,
                     raw_red_flags.xlsx, eval_metrics.xlsx,
                     metrics_by_sectors.xlsx, eval_metrics_by_sectors.xlsx).
                     Defaults to "financial_data" (relative to CWD).
        sector_file: Path to the tab-separated sector mapping file
                     (columns: ticker, sector, name, marginabile).
                     External consumers should pass the path to their own copy.
                     Defaults to the bundled "financialtools/data/sector_ticker.txt".

    Returns:
        StockRegimeAssessment Pydantic model.

    Raises:
        FileNotFoundError:   if base_dir or sector_file does not exist.
        SectorNotFoundError: if ticker is absent from sector_file, or sector
                             is absent from the benchmark Excel files.
    """
    kwargs = {
        "ticker": ticker,
        "input_dir": base_dir,
        "sheet_name": "sheet1",
    }

    if year is not None:
        kwargs["time"] = year

    metrics, eval_metrics, composite_scores, red_flags = read_financial_results(**kwargs)

    sector = get_sector_for_ticker(ticker, sector_file=sector_file)

    market_metrics = get_market_metrics(
        file_path=os.path.join(base_dir, "metrics_by_sectors.xlsx"),
        sector=sector,
    )

    eval_market_metrics = get_market_metrics(
        file_path=os.path.join(base_dir, "eval_metrics_by_sectors.xlsx"),
        sector=sector,
    )
    
    metrics, eval_metrics, composite_scores, red_flags, market_metrics, eval_market_metrics = [
        dataframe_to_json(df)
        for df in [metrics, eval_metrics, composite_scores, red_flags, market_metrics, eval_market_metrics]
    ]

    
    # Instantiate the LLM (OpenAI GPT-4 or your preferred model)
    llm = ChatOpenAI(model="gpt-4.1-nano", temperature=0)

    # Instantiate the parser with the Pydantic model
    parser = PydanticOutputParser(pydantic_object=StockRegimeAssessment)
    # Wrap your parser with OutputFixingParser
    parser = OutputFixingParser.from_llm(parser=parser, llm=llm)

    # Get the format instructions string from the parser
    format_instructions = parser.get_format_instructions()

    # Create a ChatPromptTemplate with system message and user input

    # TODO: system_prompt_StockRegimeAssessment has no {format_instructions} placeholder,
    # so this .format() is a no-op and format_instructions is silently discarded.
    # The OutputFixingParser provides a recovery path, but structured-output instructions
    # never reach the LLM. Fix: add {format_instructions} to build_prompt() in prompts.py,
    # but validate LLM output behavior before changing to avoid regressions.
    system_prompt_filled = system_prompt_StockRegimeAssessment.format(format_instructions=format_instructions)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt_filled),
        ("human", "Metrics:\n{metrics}\nScores:\n{composite_scores}\nEvaluation Metrics:\n{eval_metrics}\nRedFlags:\n{red_flags}\nMarket metrics:{market_metrics}\nMarket evaluation metrics:{eval_market_metrics}"),
    ])

    # Create a runnable chain: prompt followed by LLM invocation
    chain = prompt | llm | parser


    # Then invoke with a dict containing 'financial_data'
    response = chain.invoke({
        "metrics": metrics,  
        "eval_metrics": eval_metrics,
        "composite_scores": composite_scores,
        "red_flags": red_flags,   
        "market_metrics": market_metrics, 
        "eval_market_metrics": eval_market_metrics
    })

    

    return response
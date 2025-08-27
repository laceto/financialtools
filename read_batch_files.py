import json
import pandas as pd
from io import StringIO
from pprint import pprint
import rich


result_file_name = "batch_job_results_tickers_nopostpone_1year.jsonl"


# Loading data from saved file
results = []
with open(result_file_name, 'r') as file:
    for line in file:
        # Parsing the JSON string into a dict and appending to the list of results
        json_object = json.loads(line.strip())
        results.append(json_object)

# Assuming 'results' is a list of response dictionaries
data_list = []

for item in results:
    try:
        json_output = item['response']['body']['choices'][0]['message']['content']
        parsed = json.loads(json_output)

        data_list.append({
            'ticker': parsed.get('ticker'),
            'regime': parsed.get('regime'),
            'rationale': parsed.get('rationale'),
            'metrics_movement': parsed.get('metrics_movement'),
            'non_aligned_findings': parsed.get('non_aligned_findings')
        })
    except (KeyError, json.JSONDecodeError) as e:
        print(f"Skipping item due to error: {e}")

# Create DataFrame
df = pd.DataFrame(data_list)
rich.print(df)
df.to_excel("batch_job_results_tickers_nopostpone_1year.xlsx", index=False)


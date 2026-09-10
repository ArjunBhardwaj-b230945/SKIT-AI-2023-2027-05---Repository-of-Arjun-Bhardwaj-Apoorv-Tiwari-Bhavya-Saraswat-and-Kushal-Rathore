import os
from dotenv import load_dotenv
from llama_parse import LlamaParse
from langchain_classic.output_parsers import PydanticOutputParser
load_dotenv()
from structure import TaxDocumentExtraction
from langchain_core.prompts import PromptTemplate
instruction = """
You are an expert legal document parser. Your critical task is to parse this Income-tax Act and format it into strict hierarchical markdown:
1. Format every "CHAPTER" heading with a single '#' (e.g., '# CHAPTER I PRELIMINARY').
2. Format every main Section title/number with '##' (e.g., '## 1. Short title, extent and commencement').
3. Format Subsections or numbered clauses within sections with '###' (e.g., '### (1)' or '### (a)').
4. You must preserve all tabular data perfectly in markdown table format. Do not flatten tables into plain text.
"""
llama_parser = LlamaParse(
    api_key=os.getenv('llama-parse'),
    result_type='markdown',
    verbose=True,
    parsing_instruction=instruction
    
)

file_name = "./IT-Act.pdf"
act_document = llama_parser.load_data(file_name)

print('Creating Mardown file...')

with open('act.md', 'w', encoding="utf-8") as f:
    for doc in act_document:
        f.write(doc.text)

print("Markdown extraction complete.")
#using payed method

import os
import json
import time
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_classic.output_parsers import PydanticOutputParser
from langchain_text_splitters import MarkdownHeaderTextSplitter # Or langchain_classic
from structure import TaxDocumentExtraction

load_dotenv()

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash",temperature=0, max_retries=3,api_key=os.getenv("GEMINI_API_KEY")) 

# Set up Parser & Prompt
output_parser = PydanticOutputParser(pydantic_object=TaxDocumentExtraction)
format_instructions = output_parser.get_format_instructions()

prompt = PromptTemplate(
    template="""You are a strict data extraction AI. Your ONLY job is to extract tax rules into a specific JSON structure.

CRITICAL INSTRUCTIONS:
1. You MUST use exactly these three root keys in your JSON output: "regimes", "allowances", and "deductions". Do NOT use class names like "TaxRegime" or "DeductionSection" as keys.
2. If the text does not contain any relevant tax slabs, allowances, or deductions (e.g., if it's just introductory text, titles, or unrelated rules), you MUST return exactly this empty JSON: 
{{"regimes": [], "allowances": [], "deductions": []}}
3. Do not invent or infer data. Extract only what is explicitly written.

FORMAT INSTRUCTIONS:
{format_instructions}

TEXT:
{text}
""",
    input_variables=['text'],
    partial_variables={'format_instructions': format_instructions}
)

chain = prompt | llm | output_parser

# Load and split markdown
with open('act.md', 'r', encoding="utf-8") as f:
    full_markdown_text = f.read()

headers_to_split_on = [
    ("#", "Chapter"),
    ("##", "Section"),
]
text_splitter = MarkdownHeaderTextSplitter(headers_to_split_on)
new_doc = text_splitter.split_text(full_markdown_text)

master_data = TaxDocumentExtraction(
    regimes=[],
    allowances=[],
    deductions=[]
)

STATE_FILE = 'final_tax_act.json'
PROGRESS_FILE = 'progress.txt'

if os.path.exists(STATE_FILE) and os.path.exists(PROGRESS_FILE):
    print("Resuming from previous run...")
    with open(STATE_FILE, 'r') as f:
        master_data = TaxDocumentExtraction(**json.load(f))
    with open(PROGRESS_FILE, 'r') as f:
        START_CHUNK = int(f.read().strip())
    print(f"Resuming from chunk {START_CHUNK}")
else:
    master_data = TaxDocumentExtraction(regimes=[], allowances=[], deductions=[])
    START_CHUNK = 1

for i, chunk in enumerate(new_doc):
    chunk_num = i + 1

    if chunk_num < START_CHUNK:  
        continue
    
    chunk_text = chunk.page_content.lower()
    keywords = [
    "deduction", "allowance", "exemption", "rebate",
    "rate of tax", "400000", "per cent",
    "section 123", "section 124", "section 156",
    "total income", "surcharge"
    ]
    if not any(keyword in chunk_text for keyword in keywords):
        print(f"Skipping chunk {chunk_num}: No relevant keywords found.")
        continue

    print(f'Processing chunk {chunk_num}/{len(new_doc)}')
    try:
        extracted_chunk_data = chain.invoke({'text': chunk.page_content})

        # Merge Regime
        for new_regime in extracted_chunk_data.regimes:
            if not any(r.regime_name == new_regime.regime_name and r.tax_year == new_regime.tax_year for r in master_data.regimes):
                master_data.regimes.append(new_regime)
                
        
        # Merge Allowances
        for new_allowances in extracted_chunk_data.allowances:
            if not any(a.allowance_name == new_allowances.allowance_name for a in master_data.allowances):
                master_data.allowances.append(new_allowances)
                

        # Merge Deduction
        for new_deduction in extracted_chunk_data.deductions:
            if not any(d.section == new_deduction.section for d in master_data.deductions):
                master_data.deductions.append(new_deduction)
            

        print(
    f"Regimes: {master_data.regimes[-1] if master_data.regimes else 'None'}, "
    f"Allowances: {master_data.allowances[-1] if master_data.allowances else 'None'}, "
    f"Deductions: {master_data.deductions[-1] if master_data.deductions else 'None'}"
    )
                
        # Save state
        with open('final_tax_act.json', 'w', encoding='utf-8') as f:
            f.write(master_data.model_dump_json(indent=4))
        
        with open(PROGRESS_FILE, 'w') as f:
            f.write(str(chunk_num + 1))

        time.sleep(2)

    except Exception as e:
        print(f'Failed to extract from Chunk {chunk_num}: {e}')
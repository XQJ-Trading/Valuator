from langchain_core.messages import SystemMessage, HumanMessage

from utils.basic_utils import *
from utils.llm_utils import *
from utils.llm_zoo import *
from utils.test_runner import append_to_methods


@append_to_methods
def reports_of_president(text: str) -> str:
    # Parse the list of presidents from list_of_president function
    presidents = list_of_president(text)
    
    # Parse presidents text into a list using parse_text
    president_list = parse_text(presidents, {"presidents": "List of Korean conservative presidents"})
    
    # Initialize empty list for all descriptions
    all_descriptions = []
    
    # Get description for each president
    for president in president_list["presidents"]:
        # Get description for each president using president_desc function
        description = president_desc(president)
        all_descriptions.append(description)
    
    # Join all descriptions with newlines
    all_descriptions = "\n".join(all_descriptions)
    
    # Create system and human messages for final summary
    s_msg = SystemMessage(content='''
    You are a political analyst summarizing reports about Korean conservative presidents.
    Provide a comprehensive summary that highlights key patterns and significant contributions.
    Focus on their political ideology and major policies.
    Keep it objective and analytical.
    ''')
    
    h_msg = HumanMessage(content=f'''
    Individual president reports:
    {all_descriptions}
    ''')
    
    # Get final summary from GPT-4.1 mini
    final_summary = gpt_41_mini.invoke([s_msg, h_msg]).content
    return final_summary
    pass

@append_to_methods
def list_of_president(text: str) -> str:
    s_msg = SystemMessage(content='''
    You are a political analyst focusing on Korean conservative presidents.
    List all Korean conservative presidents in chronological order.
    Include only their names, one per line.
    ''')
    
    h_msg = HumanMessage(content=f'''
    Please list Korean conservative presidents.
    ''')
    
    result = gpt_41_nano.invoke([s_msg, h_msg]).content
    return result

@append_to_methods
def president_desc(text: str) -> str:
    s_msg = SystemMessage(content='''
    You are a political analyst focusing on Korean presidents.
    Given a president's name, provide a brief 2-3 sentence description of their presidency.
    Focus on their key policies, achievements, and historical significance.
    Keep it factual and concise.
    ''')
    
    h_msg = HumanMessage(content=f'''
    President name: {text}
    ''')
    
    result = gpt_41_nano.invoke([s_msg, h_msg]).content
    return result
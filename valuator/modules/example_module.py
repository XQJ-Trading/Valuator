from utils.llm_zoo import *
from utils.llm_utils import *


def submodule_example(corp_name):
    result = gpt_41_nano.invoke(f'make a report about ceo of {corp_name}')
    return result.content, parse_text(
        result.content,
        {
            'name': 'the name of ceo',
            'is_founder': 'boolean value'
        }
    )

def submodule_example_stakeholder(corp_name):
    result = gpt_41_nano.invoke(f'make a report about one major stakeholder of {corp_name}')
    return result.content, parse_text(
        result.content,
        {
            'name': 'the name of stakeholder',
            'stake': 'float value, 0 to 100. no percent symbol'
        }
    )


def submodule_example_summary(text_a, text_b):
    result = gpt_41_mini.invoke(f'make a summary of this: \nf{text_a}\n\nf{text_b}')
    return result.content


def run(corp_name: str) -> str:
    result_one, _ = submodule_example(corp_name)
    result_two, _ = submodule_example_stakeholder(corp_name)
    result_main = submodule_example_summary(result_one, result_two)
    return result_main


from utils import test_runner
if __name__ == '__main__':
    test_runner.run(run)

import click
import os

from report import generate_report

# 논문 목록 정의
PAPERS = [
    (
        'VGGT: Visual Geometry Grounded Transformer',
        'META',
        'https://arxiv.org/pdf/2503.11651',
    ),
    (
        'MLGym: A New Framework and Benchmark for Advancing AI Research Agents',
        'META',
        'https://arxiv.org/pdf/2502.14499',
    ),
    (
        'Semantic Ads Retrieval at Walmart eCommerce with Language Models Progressively Trained on Multiple Knowledge Domains',
        'WMT',
        'https://arxiv.org/pdf/2502.09089',
    ),
    (
        'Capturing Individual Human Preferences with Reward Features',
        'GOOGL',
        'https://arxiv.org/abs/2503.17338v1',
    ),
    (
        'Efficient Intent-Based Filtering for Multi-Party Conversations Using Knowledge Distillation from LLMs',
        'MSFT',
        'https://arxiv.org/abs/2503.17336v1',
    ),
    (
        'CAM-Seg: A Continuous-valued Embedding Approach for Semantic Image Generation',
        'AMZN',
        'https://arxiv.org/pdf/2503.15617v1',
    ),
    (
        'Preference-Guided Diffusion for Multi-Objective Offline Optimization',
        'GLAD',
        'https://arxiv.org/pdf/2503.17299v1',
    ),
]


def check_api_key():
    api_key = os.getenv("API_KEY")
    if not api_key:
        api_key = click.prompt("API_KEY가 설정되어 있지 않습니다. 입력해주세요", hide_input=True)
        os.environ["API_KEY"] = api_key
    return api_key


@click.command()
def select_paper():
    """논문 목록에서 선택하여 리포트를 생성"""

    # api key 확인
    check_api_key()


    click.echo('=== 논문 목록 ===')
    for i, (title, author, _) in enumerate(PAPERS, 1):
        click.echo(f'{i}. {title} ({author})')

    choice = click.prompt('리포트를 생성할 논문의 번호를 입력하세요', type=int)

    if 1 <= choice <= len(PAPERS):
        selected_paper = PAPERS[choice - 1]
        click.echo(f'선택된 논문: {selected_paper[0]} ({selected_paper[1]})')
        click.echo(f'논문 링크: {selected_paper[2]}')
        
        # 이후 report.py의 리포트 생성 함수를 호출할 예정
        title, ticker, link = selected_paper[0], selected_paper[1], selected_paper[2]
        report = generate_report(title, ticker, link)
        click.echo('\n=== 리포트가 생성되었습니다. ===')
    else:
        click.echo('잘못된 선택입니다. 다시 실행해주세요.')


if __name__ == '__main__':
    select_paper()

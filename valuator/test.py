from utils.basic_utils import *
from utils.llm_utils import *


def main():
    d = parse_text(
        """
​2025년 4월 16일(현지 시각 기준) 미국 증시는 주요 지수들이 하락 마감했습니다.​

S&P 500 지수: 5,396.63포인트로 전일 대비 9.34포인트(약 -0.2%) 하락 마감했습니다 .​
FRED
+2
Zacks
+2
Finviz
+2

Russell 2000 지수: 현재 실시간 지수 수치는 확인되지 않지만, 관련 ETF인 iShares Russell 2000 ETF(IWM)는 185.72달러로 전일 대비 1.04달러(약 -0.56%) 하락했습니다.​

이러한 하락은 미국 정부의 중국 반도체 수출 규제 강화로 인한 무역 긴장 고조와 이에 따른 투자 심리 위축이 주요 원인으로 분석됩니다 .​
가디언

추가로 궁금하신 사항이 있으시면 언제든지 문의해 주세요.
""",
        {
            "S&P index": "index value. float 형태로 parse가 가능한 clean한 형태로",
            "Russell 2000 index": "no dollar sign, pure float format",
        },
    )
    print(d)


if __name__ == "__main__":
    main()

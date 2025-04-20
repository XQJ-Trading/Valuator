# Valuator
LLM Valuation Model Agent
![image](https://github.com/user-attachments/assets/4202d0ed-fd3c-491a-8fb5-9378d45f8d46)


# Guide for Builder

간단하게 요약하자면:
1. 모든 시스템과 모듈은 `run(arg1, arg2, ...)`와 그 하위 함수로 조직할 것.
2. system은 최상위 실행 단위, module은 필요에 따라 중간 실행 단위로 생각하고 설계할것.


## 시스템과 모듈
<img src="https://github.com/user-attachments/assets/c8fa9cb6-e7d1-42d0-836b-ab130e59e24c" style="width:500px;" /> <p/>
이게 시스템임.

<img src="https://github.com/user-attachments/assets/743ecaa1-26fa-4f39-9e64-9ef290f70adb" style="width:500px;" /> <p/>
이게 모듈임.

## 시스템과 모듈 - 어떤게 시스템이고 어떤게 모듈인가

가급적이면, 예시 데이터를 넣고 실행하고 싶은 작업단위로 module과 system을 설계하는게 좋음.
그 이유는 run을 호출하는 방식으로 테스트와 분석이 진행되는것이 자연스럽기 때문.

예를 들어,
<p/><img src="https://github.com/user-attachments/assets/684d2d73-eda5-4dad-aaea-bf1b5843529a" style="width:500px;" /> <p/>
Analyst group을 통째로 실행해야 한다면, group 전체를 system이나 module로 정의하고, run() 함수를 설계하는 것이 맞음.

하지만, group 자체가 의미있는 실행의 단위가 아니라면,
 <p/> <img src="https://github.com/user-attachments/assets/973b579b-aa14-4987-84d2-ea68181498ab" style="width:500px;" /> <p/>
각각의 analyst를 module로 정의하고, 더 큰 단위를 system으로 설계하는 것이 나을 것.

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

## 실행
* python 파일을 경로에서 정상적으로 실행하려면, 프로젝트가 있는 Valuator 폴더로 터미널에서 진입해야 함. 이거 보고 따라하셈
---
* 윈도우에서 Python 파일을 실행하려면, 파일이 위치한 폴더로 이동한 뒤에 실행하는 것이 가장 간단한 방법입니다. 아래는 경로를 찾고 실행하는 일반적인 절차입니다:
	1.	Python 파일이 있는 위치 확인하기:
Python 파일이 저장된 폴더를 먼저 확인하세요. 만약 파일이 바탕화면에 있다면 바탕화면이, 특정 프로젝트 폴더에 있다면 그 폴더가 작업 경로가 됩니다.
	2.	폴더 경로 확인하는 방법:
	•	파일 탐색기에서 Python 파일이 있는 폴더를 엽니다.
	•	폴더 창 위쪽 주소 표시줄을 클릭하면 폴더 경로가 전체 경로 형태로 나타납니다.
	•	예: C:\Users\내이름\Desktop\MyProject
	3.	커맨드 프롬프트(명령 프롬프트) 열기:
	•	시작 메뉴에서 cmd를 입력하고 엔터를 누르면 커맨드 프롬프트가 열립니다.
	•	만약 PowerShell을 선호한다면 powershell을 입력해 열 수도 있습니다.
	4.	cd 명령어로 폴더 이동:
커맨드 프롬프트에서 cd 명령어를 사용하여 Python 파일이 있는 폴더로 이동합니다.
	•	예: cd C:\Users\내이름\Desktop\MyProject
	•	이 명령을 실행하면 현재 작업 폴더가 그 경로로 바뀌게 됩니다.
추가 팁:
	•	Windows 파일 탐색기에서 폴더 경로를 복사한 후 커맨드 프롬프트에 붙여넣으면 쉽게 경로를 입력할 수 있습니다.
	•	Python이 기본적으로 PATH에 추가되어 있어야 python 명령어를 바로 사용할 수 있습니다. PATH에 Python이 등록되지 않았다면, Python 설치 경로를 찾아 실행 경로를 직접 지정해야 할 수도 있습니다.
---
### 전체 테스트 하는 법

```bash
python -m main
```

### 모듈 단위로 테스트 하는 법

* `당장은 string -> string의 형식이 아니라면, test_runner가 작동하기 힘들것임.`

1. 모듈 / 시스템 코드 파일 밑에 이 코드 추가:
```python
from utils import test_runner
if __name__ == '__main__':
    test_runner.run(run)
```

2. `python -m` 을 이용해서 모듈 단위 실행을 할거임.
```bash
python -m {modules / systems}.{name}
ex) python -m modules.example_module
```

3. 보면 안다.

 <p/> <img src="https://github.com/user-attachments/assets/aea4dff8-3c75-4148-95dd-48d4b54eab87" style="width:500px;" /> <p/>




# datalake
* 지식관리를 위한 패키지
* 현재는 cache만 제공함


## cache
* 기본적으로 cache는 string-to-string map이다.
* key는 반드시 1개 이상의 단어(알파벳, 숫자, 언더스코어)가 .(dot)으로 구분된 형식이어야 한다. 예: `a`, `a.b`, `foo.bar_baz.hello`
* 전체적인 model 수행에 있어서, 필요한 값들을 global-scope에 저장해 두는 역할이다.
* get과 set을 가지며, [] operator로 접근 가능하다.
* 없는 key로 접근하면 빈 문자열("")을 반환한다.
* 현재는 없지만, 나중에 search 기능을 가지게 될 가능성이 높으니 확장성을 고려해 설계된다.
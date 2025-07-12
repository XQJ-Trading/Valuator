from PyQt5.QtCore import QObject, pyqtSignal

class FontManager(QObject):
    """
    애플리케이션 전체의 폰트 크기를 관리하는 싱글턴 클래스.
    폰트 크기 변경 시 시그널을 통해 모든 위젯에 알립니다.
    """
    _instance = None
    
    # 폰트 크기 변경 시그널
    font_scale_changed = pyqtSignal(float)
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        super().__init__()
        if FontManager._instance is not None:
            raise Exception("This class is a singleton!")
        
        # 기본 폰트 크기 설정
        self._current_scale = 1.0
        self._base_sizes = {
            "label": 14,
            "text": 13, 
            "button": 12,
            "title": 14
        }
        self._min_scale = 0.5
        self._max_scale = 2.0
        self._scale_step = 0.1
        
        FontManager._instance = self
    
    @property
    def current_scale(self):
        return self._current_scale
    
    def get_font_size(self, element_type: str) -> int:
        """특정 요소의 현재 폰트 크기를 반환합니다."""
        base_size = self._base_sizes.get(element_type, 13)
        return int(base_size * self._current_scale)
    
    def increase_font_size(self):
        """폰트 크기를 한 단계 증가시킵니다."""
        new_scale = min(self._current_scale + self._scale_step, self._max_scale)
        if new_scale != self._current_scale:
            self._current_scale = new_scale
            self.font_scale_changed.emit(self._current_scale)
    
    def decrease_font_size(self):
        """폰트 크기를 한 단계 감소시킵니다."""
        new_scale = max(self._current_scale - self._scale_step, self._min_scale)
        if new_scale != self._current_scale:
            self._current_scale = new_scale
            self.font_scale_changed.emit(self._current_scale)
    
    def reset_font_size(self):
        """폰트 크기를 기본값으로 초기화합니다."""
        if self._current_scale != 1.0:
            self._current_scale = 1.0
            self.font_scale_changed.emit(self._current_scale)
    
    def set_font_scale(self, scale: float):
        """폰트 크기 배율을 직접 설정합니다."""
        new_scale = max(self._min_scale, min(scale, self._max_scale))
        if new_scale != self._current_scale:
            self._current_scale = new_scale
            self.font_scale_changed.emit(self._current_scale) 
from base_analyzer import BaseAnalyzer


class CEOAnalyzer(BaseAnalyzer):
    def __init__(self, data: str):
        super().__init__(data)
        self.ceo_data = None

    def analyze(self):
        pass

    def report(self):

        pass


class LeadershipAnalyzer(BaseAnalyzer):
    def __init__(self, data: str):
        super().__init__(data)
        self.leadership_data = None

    def analyze(self):
        pass

    def report(self):
        pass

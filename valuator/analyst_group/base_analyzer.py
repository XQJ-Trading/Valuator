from abc import ABC, abstractmethod


class BaseAnalyst(ABC):
    """
    Base class for analysts.
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def analyze(self, data):
        """
        Analyze the given data.
        """
        pass

    @abstractmethod
    def report(self):
        """
        Generate a report of the analysis.
        """
        pass

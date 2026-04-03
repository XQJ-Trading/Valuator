from __future__ import annotations

import json
import math
import statistics
import sys

import numpy
import pandas
import scipy

from .executor import fork_and_execute
from .protocol import ReadySignal, SandboxResponse, dumps_message, loads_request

PRELOADED = {
    "np": numpy,
    "pd": pandas,
    "numpy": numpy,
    "pandas": pandas,
    "scipy": scipy,
    "math": math,
    "statistics": statistics,
    "json": json,
}


def main() -> None:
    _write_message(ReadySignal(ready=True, preloaded=tuple(PRELOADED)))
    for line in sys.stdin:
        try:
            response = fork_and_execute(loads_request(line), PRELOADED)
        except Exception as exc:
            response = SandboxResponse(
                success=False,
                output="",
                execution_type="failed",
                error=str(exc),
            )
        _write_message(response)


def _write_message(message: ReadySignal | SandboxResponse) -> None:
    sys.stdout.write(dumps_message(message))
    sys.stdout.flush()


if __name__ == "__main__":
    main()

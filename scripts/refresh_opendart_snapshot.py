from __future__ import annotations

from valuator.infra.opendart_client import (
    OUTPUT_PATH,
    OPENDART_SNAPSHOT_PATH,
    sync_all_companies,
)
from valuator.utils.config import get_opendart_api_key


def main() -> None:
    seeds = sync_all_companies(
        get_opendart_api_key(required=True),
        snapshot_path=OPENDART_SNAPSHOT_PATH,
        output_path=OUTPUT_PATH,
    )
    print(
        "OpenDART snapshot refresh complete: "
        f"companies={len(seeds)}"
    )


if __name__ == "__main__":
    main()

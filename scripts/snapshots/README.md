OpenDART snapshot artifacts live here.

The canonical snapshot file is `opendart_companies.json.gz`.

It is consumed by `scripts/download_opendart_securities.py` as persistent
OpenDART sync state and rebuilt by `scripts/refresh_opendart_snapshot.py`.

Refresh them from a network that can reach OpenDART:

```bash
OPENDART_API_KEY=... python scripts/refresh_opendart_snapshot.py
```

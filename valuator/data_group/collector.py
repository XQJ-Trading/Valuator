import requests


def fetch_using_readerLLM(url):
    proxy_url = f"https://r.jina.ai/{url}"
    response = requests.get(proxy_url, timeout=10)
    response.raise_for_status()
    return response.text


if __name__ == "__main__":
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    html = fetch_using_readerLLM(url)
    print(html[:1000])

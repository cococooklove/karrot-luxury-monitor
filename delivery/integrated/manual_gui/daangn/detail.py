from daangn.model import Product
from bs4 import BeautifulSoup


def render_to_html(prd: Product):
    HTML = """
<div>
  <a id="url" href="">페이지 열기</a>
  <p id="name" style="font-weight:bold; font-size:18px; margin:0; margin-top: 4px;"></p>
  <p id="price" style="margin:4px 0 0 0; font-size:14px;"></p>
  <p id="desc" style="font-size:14px; margin:6px 0 0 0;"></p>
</div>
"""

    soup = BeautifulSoup(HTML, "html.parser")
    soup.select_one("#name").string = prd.name or ""            # type: ignore
    soup.select_one("#price").string = prd.get_price_str()      # type: ignore
    soup.select_one("#desc").string = prd.description or ""     # type: ignore
    # 상대경로(/kr/buy-sell/..)면 절대 URL 로 — 안 그러면 클릭 시 상세 빈칸
    url = prd.url or ""
    if url and not url.startswith("http"):
        url = "https://www.daangn.com" + url
    soup.select_one("#url").attrs["href"] = url                 # type: ignore

    return str(soup)

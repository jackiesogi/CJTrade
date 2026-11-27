import os
from textwrap import dedent

import toml
from cjtrade.pkgs.analytics.informational.news_client import NewsClient
from cjtrade.pkgs.analytics.informational.news_client import NewsProviderType
from cjtrade.pkgs.logger import get_logger
from cjtrade.pkgs.logger import setup_logging
from cjtrade.pkgs.ui import FormEngine

log = get_logger("CJNews")

def generate_news_search_form(news_list):
    return toml.dumps({
        "title": "CJNews search result",
        "field": [
            {
                "type": "display",
                "config": {
                    "heading": news.title,
                    "body": news.content,
                },
            }
            for news in news_list
        ],
    })

if __name__ == "__main__":
    setup_logging()
    spec = dedent("""\
        title = "CJNews search engine (lite)"

        [[field]]
        name = "keyword"
        label = "搜尋關鍵字"
        default = "台積電"
        type = "text"

        [[field]]
        name = "source"
        label = "新聞來源"
        default = "CNYES 鉅亨網"
        type = "select"
        [field.config]
        options = ["CNYES 鉅亨網", "NewsAPI"]

        [[field]]
        name = "num"
        label = "結果筆數"
        default = 5
        type = "number"
        [field.config]
        min = 1
        step = 1
        max = 20
    """)

    form = FormEngine(toml_str=spec, renderer="web").run()
    log.info("user input: %s", form)

    provider = {
        "CNYES 鉅亨網": NewsProviderType.CNYES,
        "NewsAPI": NewsProviderType.NEWS_API,
    }.get(form["source"])

    config = {}
    if provider == NewsProviderType.NEWS_API:
        # NewsAPI needs a key; the same NEWSAPI_API_KEY the shell reads.
        config["api_key"] = os.environ.get("NEWSAPI_API_KEY", "")
        if not config["api_key"]:
            raise SystemExit("NewsAPI needs NEWSAPI_API_KEY in a .cjconf file or the environment")

    client = NewsClient(provider, **config)
    n = int(form["num"])
    keyword = form["keyword"]

    result = (
        client.search_by_keyword(keyword, n)
        or client.fetch_headline_news(n)
    )

    FormEngine(
        toml_str=generate_news_search_form(result),
        renderer="web",
    ).run()

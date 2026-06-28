from textwrap import dedent

import toml
from cjtrade.pkgs.analytics.informational.news_client import NewsClient
from cjtrade.pkgs.analytics.informational.news_client import NewsProviderType
from cjtrade.pkgs.ui import FormEngine

def generate_news_search_form(news_list):
    return toml.dumps({
        "title": "CJNews search result",
        "field": [
            {
                "name": f"result_{i}",
                "label": news.title,
                "type": "sublabel",
                "optional": True,
                "sublabel": news.content,
            }
            for i, news in enumerate(news_list)
        ],
    })

if __name__ == "__main__":
    spec = dedent("""\
        title = "CJNews search engine (lite)"

        [[field]]
        name = "keyword"
        label = "搜尋關鍵字"
        type = "text"
        default = "台積電"

        [[field]]
        name = "source"
        label = "新聞來源"
        type = "select"
        options = ["CNYES 鉅亨網", "NewsAPI", "財報狗"]
        default = "CNYES 鉅亨網"

        [[field]]
        name = "num"
        label = "結果筆數"
        type = "number"
        min = 1
        step = 1
        default = 5
    """)

    form = FormEngine(toml_str=spec, renderer="web").run()
    print(f"User input: {form}")

    provider = {
        "CNYES 鉅亨網": NewsProviderType.CNYES,
        "NewsAPI": NewsProviderType.NEWS_API,
    }.get(form["source"])

    if provider is None:
        raise NotImplementedError(f'{form["source"]} provider is not implemented yet.')

    client = NewsClient(provider)
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

from elasticsearch_dsl import Search, Q

from ...search.multicorpus.multi_corpus import MultiCorpus
from ...core.language_manager import LanguageManager
from ...core.settings_utils import get_language_manager
from ...core.esutils import get_es_conn
from ...search.document import map_search_hit
from ...security.base_authorization import BaseAuthorization


class DocumentsByText:
    def __init__(self, env_id: str, authorization: BaseAuthorization):
        self.env_id = env_id
        self.authorization = authorization
        self.multi_corpus = MultiCorpus(env_id, authorization)

    def query_index(self, query: dict) -> str:
        """
        Get query index wildcard for the corpus id and all languages.

        :param query:
        :return:
        """
        corpus = self.multi_corpus.corpus_from_id(query["corpus_id"])
        return corpus.dd.get_indices(docTypes=[])

    def queries_indices(self, queries: list) -> list:
        return [self.query_index(query) for query in queries]

    @staticmethod
    def transform(language_manager: LanguageManager, query: dict) -> Q:
        text_field_name = "text"
        if query["search_mode"] == "language":
            text_field_name = text_field_name + "." + language_manager.get_es_analyser(query["language"])

        return Q({"match": {text_field_name: query["text"]}})

    def group_and_transform_queries_by_operator(self, queries: list) -> dict:
        language_manager = get_language_manager()
        operators = ["must", "must_not", "should"]
        grouped_queries = {}
        for operator in operators:
            grouped_queries[operator] = []

        for query in queries:
            for operator in operators:
                if operator == query["operator"]:
                    grouped_queries[operator].append(self.transform(language_manager, query))
                    continue

        return grouped_queries

    def documents_by_text(self, queries: list, from_index: int, size: int) -> tuple:
        """
        Paginated documents found by text.

        :param queries:
        :param from_index:
        :param size:
        :return:
        """
        # For pagination/score sorting to work, we need to query all the different corpus indices in the same
        # Elasticsearch query.
        indices = self.queries_indices(queries)
        indices_argument = ','.join(indices)

        # Sticks the `must`, `should` and `must not` in 3 different bags
        grouped_queries = self.group_and_transform_queries_by_operator(queries)

        # A query language restriction, if present, will work automatically via the query text.<language> mapping.
        es = get_es_conn()
        search = Search(using=es, index=indices_argument)
        search = search.source(["title", "language", "source"])

        search.query = Q('bool',
                         must=grouped_queries["must"],
                         must_not=grouped_queries["must_not"],
                         should=grouped_queries["should"])

        search = search[from_index:from_index + size]
        count = search.count()
        documents = [map_search_hit(hit) for hit in search]

        return count, documents
from elasticsearch_dsl import Search, Q
from typing import List

from jassrealtime.core.esutils import get_es_conn
from jassrealtime.core.settings_utils import get_settings, get_env_id
from jassrealtime.document.document_corpus import make_sort_field, make_es_filters, get_master_document_corpus_list
from jassrealtime.search.document import map_search_hit
from jassrealtime.security.security_selector import get_autorisation


def get_metadata_for_documents(corpusIds, schemaType, fromIndex, size, sortBy, sortOrder, filters,
                               filterJoin):
    # Specify all annotations indices for specified corpora
    indices = partial_corpora_indices(corpusIds)

    es = get_es_conn()
    search = Search(using=es, index=indices)
    search = search[fromIndex:fromIndex + size]  # We are forced to use the scrolling API to sort (scan won't work)

    # Sort by score if no sort field specified
    if sortBy:
        actual_sort = make_sort_field(sortBy, sortOrder)
    else:
        actual_sort = "_score"

    search = search.sort(actual_sort)

    # Need to restrict the search annotations to the given schema type.
    # The alternative is doing a first search to retrieve only the indices of the given schema type.
    # We are not sure which approach is faster overall.
    schema_type_query = Q('term', schemaType=schemaType)

    if filters:
        es_filters = make_es_filters(filters, filterJoin)
        # Although we are calling them filters,
        # we cannot actually use an ElasticSearch filter because we would lose score.
        # Scoring is important for sorting searches with analyzers like Ngram, EdgeNgram, etc.
        search = search.query(schema_type_query & es_filters)
    else:
        # Here, we use filter because it's faster and scoring is not relevant
        search = search.filter(schema_type_query)

    count = search.count()

    annotations = [map_search_hit(hit) for hit in search]

    return count, annotations


def partial_corpora_indices(corpus_ids: List[str]) -> str:
    # The idiomatic way would be to instantiate a corpus for each corpus Id and then do a search in each corpus
    # for the bucket with the right schema type.
    # As it represent a 2n operation before doing the main search, and fearing latency,
    # I, Jean-François Héon, decided to perform this (possibly premature) optimization.
    settings = get_settings()
    annotation_directory = settings['CLASSES']['DOCUMENT_DIRECTORY']['CLASS_PREFIX']
    data_suffix = settings['CLASSES']['DOCUMENT_DIRECTORY']['INDEX_DATA_SUFFIX']
    index_suffix = '*' + data_suffix + '_*'
    index_prefix = get_env_id() + annotation_directory
    indices = []
    for corpus_id in corpus_ids:
        indices.append(index_prefix + corpus_id + index_suffix)
    joined_indices = ','.join(indices)
    return joined_indices


def corpus_languages(corpus):
    return corpus.languages


def query_structure(grouped_targets: dict) -> list:
    structure = []

    for corpusId, buckets in grouped_targets.items():
        corpus = corpus_from_id(corpusId)
        group_structure = {"id": corpusId, "languages": corpus_languages(corpus)}
                           # "properties": bucket_properties(corpus, buckets)}
        structure.append(group_structure)

    return structure


def corpus_from_id(corpus_id):
    env_id = get_env_id()
    authorization = get_autorisation(env_id, None, None)
    corpora = get_master_document_corpus_list(env_id, authorization)
    return corpora.get_corpus(corpus_id)

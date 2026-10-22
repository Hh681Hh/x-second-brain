from copy import deepcopy

from xsecondbrain.knowledge import search_documents


def test_foreign_source_indexes_complete_localized_method_at_its_evidence():
    chunks = [
        {'id': 'cited', 'text': 'Use audience questions to build a digital product.', 'start_offset': 0},
        {'id': 'other', 'text': 'This unrelated paragraph covers time management.', 'start_offset': 100},
    ]
    card = {
        'problem': '不知道怎样选择第一款产品。',
        'method': '把自己解决过的问题做成一页免费指南，再根据受众反馈扩展。',
        'why': '专业经验提供素材，重复提问反映需求。',
        'scenarios': ['数字产品', '30天挑战'], 'prerequisites': ['观察真实受众问题'],
        'steps': ['先验证需求，再完善交付'], 'limitations': ['没有成交数据'],
        'evidence': [{'chunk_id': 'cited'}],
    }
    original = deepcopy(chunks)
    lexical, vectors = search_documents('An English article', chunks, {'knowledge': [card]})
    assert '30天挑战' in lexical['cited'] and '专业经验' in lexical['cited']
    assert card['method'] in vectors[0] and card['why'] in vectors[0]
    assert '数字产品' not in lexical['other'] and '数字产品' not in vectors[1]
    assert chunks == original  # citations continue to refer to actual source text/offsets


def test_no_analysis_retains_original_keyword_and_embedding_source():
    lexical, vectors = search_documents('Title', [{'id': 'c', 'text': 'Original content'}], None)
    assert lexical == {'c': 'Title\nOriginal content'}
    assert vectors == ['Title\nOriginal content']

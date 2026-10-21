import pytest
from xsecondbrain.knowledge import split_chunks, validate_evidence, remove_repeated_sentences
from xsecondbrain.security import UserError


def test_all_source_characters_are_preserved_with_offsets():
    text = '🧠 原始文章第一段。\n\n' + '这里包含实际操作方法和前提条件。'*170
    chunks = split_chunks('test-article',text)
    covered = set()
    for c in chunks:
        assert c['text'] == text[c['start_offset']:c['end_offset']]
        assert len(c['text']) <= 400
        covered.update(range(c['start_offset'],c['end_offset']))
    assert all(i in covered for i,char in enumerate(text) if not char.isspace())
    quote = chunks[-1]['text'][10:45]
    result = validate_evidence([{'chunk_id':chunks[-1]['id'],'quote':quote}],chunks)[0]
    assert text[result['start_offset']:result['end_offset']] == quote


@pytest.mark.parametrize('evidence',[{'chunk_id':'fake','quote':'完全虚构的原文引用'}, {'chunk_id':'correct','quote':'不存在的内容，不能成为原文依据'}])
def test_false_citations_are_rejected(evidence):
    chunks = [{'id':'correct','article_id':'article','text':'真实原文提出了方法，但没有量化收益数据。','start_offset':0}]
    with pytest.raises(UserError,match='不存在'):
        validate_evidence([evidence],chunks)


def test_reading_cleanup_preserves_numbers_and_abbreviations():
    text = '模型v1.0的阈值为0.5，另一个阈值为0.7。Use U.S. examples and v1.2. 保持证据。保持证据。'
    assert remove_repeated_sentences(text) == '模型v1.0的阈值为0.5，另一个阈值为0.7。Use U.S. examples and v1.2. 保持证据。保持证据。'
    assert remove_repeated_sentences('限制需要核对。限制需要核对。条件不能省略。') == '限制需要核对。条件不能省略。'

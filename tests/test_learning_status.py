"""Learning progress is independent of whether the human has read an article.

These isolated metadata fixtures exercise aggregation and filtering only; no
model analysis or external collection is simulated as a successful AI run.
"""
import json


def _article(client, app, sample, index, *, status, category='AI Agent',
             is_read=False, cards=None):
    response = client.post('/api/articles', json={
        **sample,
        'url': f'https://example.org/fixtures/learning-status/{index}',
        'content': sample['content'] + f'\n\n明确标记的状态统计样例 {index}。',
        'category': category,
    })
    assert response.status_code == 201
    article_id = response.json()['id']
    analysis = None if cards is None else json.dumps({
        'knowledge': [{} for _ in range(cards)], 'quick': [], 'ratings': {},
    })
    timestamp = f'2026-10-22T08:{index:02d}:00+00:00'
    with app.state.service.db.connect() as conn:
        conn.execute(
            'UPDATE articles SET status=?,is_read=?,analysis_json=?,updated_at=? WHERE id=?',
            (status, is_read, analysis, timestamp, article_id),
        )
    return article_id, timestamp


def test_empty_learning_status_and_workbench_cache(client):
    status = client.get('/api/status').json()
    for name in ('total', 'learned', 'unread', 'knowledge_cards',
                 'needs_attention', 'needs_content', 'failed', 'saved'):
        assert status[name] == 0, name
    assert status['latest_updated_at'] == ''
    assert client.get('/workbench').headers['cache-control'] == 'no-cache'


def test_learning_counts_keep_human_reading_separate(client, app, sample):
    fixtures = [
        ('ready', True, 2),
        ('ready', False, 1),
        # Existing analysis remains counted during a re-index or retry.
        ('processing', False, 1),
        ('queued', False, None),
        ('needs_content', False, None),
        ('needs_content', True, None),
        ('error', False, None),
        ('saved', False, None),
    ]
    timestamps = []
    for index, (state, read, cards) in enumerate(fixtures):
        _, timestamp = _article(client, app, sample, index,
                                status=state, is_read=read, cards=cards)
        timestamps.append(timestamp)
    status = client.get('/api/status').json()
    assert status['total'] == 8
    assert status['learned'] == 3
    assert status['unread'] == 6
    assert status['knowledge_cards'] == 4
    assert status['needs_attention'] == 4
    assert status['needs_content'] == 2
    assert status['failed'] == 1
    assert status['saved'] == 1
    assert status['latest_updated_at'] == max(timestamps)


def test_attention_filter_composes_without_changing_default_list(client, app, sample):
    needs, _ = _article(client, app, sample, 0, status='needs_content')
    failed, _ = _article(client, app, sample, 1, status='error', is_read=True)
    saved, _ = _article(client, app, sample, 2, status='saved', category='获客与营销')
    for index, status in enumerate(('ready', 'processing', 'queued'), start=3):
        _article(client, app, sample, index, status=status)

    default = client.get('/api/articles').json()
    disabled = client.get('/api/articles', params={'attention': False}).json()
    assert default['total'] == disabled['total'] == 6
    assert {a['id'] for a in default['articles']} == {a['id'] for a in disabled['articles']}

    attention = client.get('/api/articles', params={'attention': True}).json()
    assert attention['total'] == 3
    assert {a['id'] for a in attention['articles']} == {needs, failed, saved}
    category = client.get('/api/articles', params={
        'attention': True, 'category': 'AI Agent',
    }).json()
    assert category['total'] == 2
    assert {a['id'] for a in category['articles']} == {needs, failed}
    unread = client.get('/api/articles', params={
        'attention': True, 'category': 'AI Agent', 'unread': True,
    }).json()
    assert unread['total'] == 1
    assert [a['id'] for a in unread['articles']] == [needs]

    page = client.get('/api/articles', params={
        'attention': True, 'limit': 1, 'offset': 1,
    }).json()
    assert page['total'] == 3 and len(page['articles']) == 1
    assert page['articles'][0]['id'] in {needs, failed, saved}

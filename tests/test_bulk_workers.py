"""Exercise SQLite job ownership, not simulated successful AI responses."""
import threading
import time

from xsecondbrain.config import Settings
from xsecondbrain.main import create_app
from xsecondbrain.models import ArticleInput


def test_concurrent_workers_claim_each_job_once(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, knowledge_workers=2,
                              embedding_provider='none'), start_worker=False)
    service = app.state.service
    ids = []
    for i in range(8):
        result = service.add(ArticleInput(title=f'Queue fixture {i}',
            content=f'Queue ownership test {i}. This is not a real AI article or analysis.'))
        ids.append(result['id'])
    seen, lock = [], threading.Lock()
    rendezvous = threading.Barrier(2)

    def observe_claim(article_id):
        with lock:
            seen.append(article_id)
        rendezvous.wait(timeout=5)
        with service.db.connect() as conn:
            conn.execute("UPDATE jobs SET state='done' WHERE article_id=?", (article_id,))

    service.process = observe_claim
    service.start()
    try:
        deadline = time.monotonic() + 8
        while len(seen) < len(ids) and time.monotonic() < deadline:
            time.sleep(.02)
        assert sorted(seen) == sorted(ids)
        assert len(set(seen)) == len(ids)
    finally:
        service.stop()


def test_retrieval_keeps_details_from_best_long_source_and_other_sources(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, embedding_provider='none'), start_worker=False)
    service = app.state.service
    best = service.add(ArticleInput(title='审批自动化方法', content=(
        '审批自动化需要逐项核对权限与审计记录，记录审批自动化的适用条件和失败处理。' * 40)))['id']
    for i in range(5):
        service.add(ArticleInput(title=f'补充资料{i}', content=(
            f'这是第{i}份明确标记的检索测试资料。审批自动化需要核对。其他段落讨论团队日常工作与沟通安排。')))
    hits = service.search.query('审批自动化', limit=6)['hits']
    assert len(hits) == 6
    assert sum(h['article_id'] == best for h in hits) >= 2
    assert len({h['article_id'] for h in hits}) >= 2

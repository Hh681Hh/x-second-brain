from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from xsecondbrain.config import Settings
from xsecondbrain.main import create_app

SAMPLE = {
    'title': '【原创测试样例】服务知识检索流程',
    'author': 'X Second Brain 测试作者（虚构样例角色）',
    'url': 'https://example.org/fixtures/support',
    'content': '这是原创测试样例，不是真实 X 文章。\n\n先把内部帮助资料整理成短段，保留每段来源。收到客户咨询时，先在资料中检索相关段落，再由模型依据检索结果作答。回答附上原段落；没有足够证据就转交人工。\n\n先收集常见疑问与历史工单，编写标准答案，再评估召回率和转人工比例。涉及退款和修改账户的操作应由人工确认。这个方法依赖资料及时更新；文档过时会让答案失效，作者没有提供业务收益的量化数据。',
    'category': 'AI Agent'
}
SECOND = {
    'title': '【原创测试样例】知识服务的上线评估',
    'author': 'X Second Brain 测试作者（虚构样例角色）',
    'url': 'https://example.org/fixtures/evaluation',
    'content': '这是原创测试样例。上线答疑系统前，准备一组匿名历史咨询作为回归集，人工标记每道问题应引用的证据和允许的答案。分别统计资料检索命中率、回答正确率以及无答案时的拒答率。先以影子模式运行，与人工回复对比，再逐步开放。不能把模型自身的自信程度当成正确率。这篇只提出评估流程，没有声称能替代人工审核。',
    'category': 'AI Agent'
}


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=tmp_path, embedding_provider='none'), start_worker=False)


@pytest.fixture
def client(app):
    with TestClient(app) as instance:
        yield instance


@pytest.fixture
def sample():
    return dict(SAMPLE)

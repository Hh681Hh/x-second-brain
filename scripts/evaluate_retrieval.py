"""Small disclosed paraphrase fixture evaluation using actual model vectors."""
import json
import numpy as np
from xsecondbrain.config import ROOT, Settings
from xsecondbrain.providers import Embeddings
from tests.conftest import SAMPLE, SECOND

if __name__ == '__main__':
    model = Embeddings(Settings(data_dir=ROOT/'data'))
    documents = [SAMPLE['title']+'\n'+SAMPLE['content'],SECOND['title']+'\n'+SECOND['content'],'番茄种植需要充足光照，浇水时保持土壤湿润。叶霉病的防治需要通风和控制湿度。']
    queries = ['售后机器人怎样减轻接线员的负担？','我想给自己的业务制作一个 AI 自动客服，有什么好的实现方案？','如何验证自动答疑的效果，避免上线后胡说？','如何种植意大利番茄并防治叶霉病？','比特币价格明天会涨多少？']
    vectors = model.encode(documents)
    encoded = model.encode(queries,query=True)
    scores = encoded @ vectors.T
    report = [{'query':q,'scores':[round(float(v),4) for v in s]} for q,s in zip(queries,scores)]
    print(json.dumps(report,ensure_ascii=False,indent=2))

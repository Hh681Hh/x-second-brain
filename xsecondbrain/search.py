from collections import Counter
import numpy as np

from .knowledge import tokenize
from .security import UserError


class Search:
    def __init__(self, db, embeddings, settings):
        self.db, self.embeddings, self.settings = db, embeddings, settings

    def query(self, question, limit=8, category=None, exclude_article=None, unread=False):
        tokens = list(dict.fromkeys(tokenize(question)))[:90]
        warnings = []
        with self.db.connect() as conn:
            params = []
            # A saved card/preview is not enough to support an article-level answer.
            constraints = ["length(a.content)>0", "a.status!='needs_content'"]
            if category:
                constraints.append("a.category=?")
                params.append(category)
            if unread:
                constraints.append('a.is_read=0')
            if exclude_article:
                constraints.append("a.id!=?")
                params.append(exclude_article)
            where = ' AND '.join(constraints)
            columns = "c.id,c.article_id,c.ordinal,c.start_offset,c.end_offset,c.text,a.title,a.author,a.url,a.category,a.saved_at"
            lexical = []
            if tokens:
                expression = ' OR '.join('"' + t.replace('"','') + '"' for t in tokens)
                lexical = [dict(r) for r in conn.execute(f"SELECT {columns},bm25(chunks_fts) AS lexical_rank,c.search_text FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.chunk_id JOIN articles a ON a.id=c.article_id WHERE chunks_fts MATCH ? AND {where} ORDER BY lexical_rank LIMIT 80", [expression, *params])]
                # One accidental common bigram is not enough for a long query.
                needed = 1 if len(tokens) <= 3 else 2
                lexical = [r for r in lexical if len(set(tokens) & set(tokenize(r['search_text']))) >= needed]
            vector_rows = [dict(r) for r in conn.execute(f"SELECT {columns},c.embedding FROM chunks c JOIN articles a ON a.id=c.article_id WHERE {where} AND c.embedding IS NOT NULL AND c.embedding_model=?", [*params, self.embeddings.signature])]
        semantic = []
        if self.settings.embedding_provider != 'none' and vector_rows:
            try:
                query = self.embeddings.encode([question], query=True)[0]
                for row in vector_rows:
                    vector = np.frombuffer(row.pop('embedding'), dtype=np.float32)
                    if vector.shape != query.shape:
                        continue
                    score = float(vector @ query)
                    if score >= self.settings.semantic_threshold:
                        row['semantic_score'] = round(score, 4)
                        semantic.append(row)
                semantic.sort(key=lambda x: x['semantic_score'], reverse=True)
                semantic = semantic[:80]
            except UserError as exc:
                warnings.append(str(exc))
        elif self.settings.embedding_provider != 'none':
            warnings.append("尚无当前模型的可用向量；正在等待索引或需要重建。此次仅做全文检索。")
        else:
            warnings.append("语义检索已关闭；此次仅做全文检索。")
        merged = {}
        for channel, items in (('keyword', lexical), ('semantic', semantic)):
            for rank, item in enumerate(items):
                row = merged.setdefault(item['id'], {k: v for k, v in item.items() if k not in ('search_text', 'lexical_rank', 'embedding')})
                row['score'] = row.get('score', 0) + 1 / (40 + rank + 1)
                row.setdefault('matched_by', []).append(channel)
                if 'semantic_score' in item:
                    row['semantic_score'] = item['semantic_score']
        ranked = sorted(merged.values(), key=lambda x: x['score'], reverse=True)
        # Reserve half the budget for source diversity, then spend the rest on
        # relevant details. Filling the entire budget with one chunk per article
        # loses the method/conditions from the best matching long article.
        selected, counts = [], Counter()
        for cap in (1, 3):
            for row in ranked:
                budget = max(1, (limit + 1) // 2) if cap == 1 else limit
                if len(selected) >= budget:
                    break
                if row not in selected and counts[row['article_id']] < cap:
                    row['score'] = round(row['score'], 6)
                    selected.append(row)
                    counts[row['article_id']] += 1
        return {"hits": selected, "warnings": warnings, "mode": "hybrid" if semantic and lexical else "semantic" if semantic else "keyword", "embedding_model": self.embeddings.signature}

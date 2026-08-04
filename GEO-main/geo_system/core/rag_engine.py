"""
RAG检索引擎
用于构建和管理GEO知识库
"""

import os
import hashlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class KnowledgeChunk:
    """知识片段"""
    id: str
    content: str
    source: str
    chunk_type: str  # entity, relation, evidence, general
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None
    created_at: str = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


@dataclass
class SearchResult:
    """搜索结果"""
    chunk: KnowledgeChunk
    score: float
    context: str


class RAGEngine:
    """
    RAG检索引擎
    
    支持知识库的构建、索引和检索
    基于向量相似度实现语义搜索
    """
    
    def __init__(self, embedding_model=None, vector_store=None):
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.knowledge_base: Dict[str, KnowledgeChunk] = {}
        
    def add_document(self, content: str, source: str, 
                     doc_type: str = "general", metadata: Dict = None) -> List[str]:
        """
        添加文档到知识库
        
        Args:
            content: 文档内容
            source: 文档来源
            doc_type: 文档类型
            metadata: 元数据
            
        Returns:
            生成的chunk ID列表
        """
        # 分块处理
        chunks = self._chunk_document(content)
        chunk_ids = []
        
        for i, chunk_content in enumerate(chunks):
            chunk_id = self._generate_chunk_id(source, i, chunk_content)
            
            # 识别chunk类型
            chunk_type = self._identify_chunk_type(chunk_content)
            
            # 创建知识片段
            chunk = KnowledgeChunk(
                id=chunk_id,
                content=chunk_content,
                source=source,
                chunk_type=chunk_type,
                metadata={
                    **(metadata or {}),
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "doc_type": doc_type
                }
            )
            
            # 生成embedding
            if self.embedding_model:
                chunk.embedding = self._generate_embedding(chunk_content)
            
            self.knowledge_base[chunk_id] = chunk
            chunk_ids.append(chunk_id)
        
        return chunk_ids
    
    def _chunk_document(self, content: str, chunk_size: int = 500, 
                        overlap: int = 50) -> List[str]:
        """
        将文档分块
        
        Args:
            content: 文档内容
            chunk_size: 每块大小（字符数）
            overlap: 重叠大小
            
        Returns:
            分块列表
        """
        chunks = []
        start = 0
        
        while start < len(content):
            end = start + chunk_size
            
            # 尝试在句子边界处截断
            if end < len(content):
                # 向后查找句子结束符
                for i in range(min(end + 50, len(content)) - 1, end - 1, -1):
                    if content[i] in '。！？.!?':
                        end = i + 1
                        break
            
            chunk = content[start:end].strip()
            if chunk:
                chunks.append(chunk)
            
            start = end - overlap
        
        return chunks
    
    def _identify_chunk_type(self, content: str) -> str:
        """识别片段类型"""
        # 实体识别
        entity_indicators = ['是', '称为', '指的是', '即']
        if any(indicator in content for indicator in entity_indicators):
            if len(content) < 200:
                return "entity"
        
        # 关系识别
        relation_indicators = ['导致', '影响', '相关', '关联', '因为', '所以']
        if any(indicator in content for indicator in relation_indicators):
            return "relation"
        
        # 证据识别
        evidence_indicators = ['数据显示', '研究表明', '根据', '统计', '案例']
        if any(indicator in content for indicator in evidence_indicators):
            return "evidence"
        
        return "general"
    
    def _generate_chunk_id(self, source: str, index: int, content: str) -> str:
        """生成chunk ID"""
        hash_input = f"{source}:{index}:{content[:50]}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:16]
    
    def _generate_embedding(self, content: str) -> List[float]:
        """生成embedding向量"""
        if self.embedding_model:
            # 实际调用embedding模型
            # 这里返回模拟数据
            return [0.0] * 1536
        return [0.0] * 1536
    
    def search(self, query: str, top_k: int = 5, 
               filters: Dict = None) -> List[SearchResult]:
        """
        搜索知识库
        
        Args:
            query: 查询语句
            top_k: 返回结果数量
            filters: 过滤条件
            
        Returns:
            搜索结果列表
        """
        # 生成查询向量
        query_embedding = self._generate_embedding(query)
        
        # 计算相似度
        results = []
        for chunk in self.knowledge_base.values():
            # 应用过滤器
            if filters and not self._apply_filters(chunk, filters):
                continue
            
            # 计算相似度得分
            if chunk.embedding:
                score = self._calculate_similarity(query_embedding, chunk.embedding)
            else:
                # 使用关键词匹配作为备选
                score = self._keyword_match_score(query, chunk.content)
            
            # 构建上下文
            context = self._build_context(chunk)
            
            results.append(SearchResult(
                chunk=chunk,
                score=score,
                context=context
            ))
        
        # 排序并返回top_k
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]
    
    def _calculate_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算向量相似度（余弦相似度）"""
        import math
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def _keyword_match_score(self, query: str, content: str) -> float:
        """关键词匹配得分"""
        query_words = set(query.lower().split())
        content_words = set(content.lower().split())
        
        if not query_words:
            return 0.0
        
        matches = len(query_words & content_words)
        return matches / len(query_words)
    
    def _apply_filters(self, chunk: KnowledgeChunk, filters: Dict) -> bool:
        """应用过滤条件"""
        for key, value in filters.items():
            if key == "chunk_type" and chunk.chunk_type != value:
                return False
            if key == "source" and chunk.source != value:
                return False
            if key in chunk.metadata and chunk.metadata[key] != value:
                return False
        return True
    
    def _build_context(self, chunk: KnowledgeChunk) -> str:
        """构建上下文"""
        context_parts = [
            f"来源: {chunk.source}",
            f"类型: {chunk.chunk_type}",
            f"内容: {chunk.content[:200]}..."
        ]
        return "\n".join(context_parts)
    
    def get_knowledge_graph(self) -> Dict:
        """
        获取知识图谱结构
        
        Returns:
            包含实体和关系的图谱数据
        """
        entities = []
        relations = []
        
        for chunk in self.knowledge_base.values():
            if chunk.chunk_type == "entity":
                entities.append({
                    "id": chunk.id,
                    "name": self._extract_entity_name(chunk.content),
                    "content": chunk.content
                })
            elif chunk.chunk_type == "relation":
                relations.append({
                    "id": chunk.id,
                    "content": chunk.content,
                    "source": chunk.source
                })
        
        return {
            "entities": entities,
            "relations": relations,
            "stats": {
                "total_chunks": len(self.knowledge_base),
                "entity_count": len(entities),
                "relation_count": len(relations)
            }
        }
    
    def _extract_entity_name(self, content: str) -> str:
        """提取实体名称"""
        # 简单的实体名称提取
        # 实际应用中可以使用NLP工具
        lines = content.strip().split('\n')
        if lines:
            first_line = lines[0]
            # 尝试提取"XX是..."或"...称为XX"中的XX
            if '是' in first_line:
                return first_line.split('是')[0].strip()
        return content[:50]
    
    def export_knowledge_base(self, filepath: str):
        """导出知识库"""
        import json
        
        export_data = {
            "chunks": [
                {
                    "id": chunk.id,
                    "content": chunk.content,
                    "source": chunk.source,
                    "chunk_type": chunk.chunk_type,
                    "metadata": chunk.metadata,
                    "created_at": chunk.created_at
                }
                for chunk in self.knowledge_base.values()
            ],
            "exported_at": datetime.now().isoformat()
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
    
    def import_knowledge_base(self, filepath: str):
        """导入知识库"""
        import json
        
        with open(filepath, 'r', encoding='utf-8') as f:
            import_data = json.load(f)
        
        for chunk_data in import_data.get("chunks", []):
            chunk = KnowledgeChunk(
                id=chunk_data["id"],
                content=chunk_data["content"],
                source=chunk_data["source"],
                chunk_type=chunk_data["chunk_type"],
                metadata=chunk_data["metadata"],
                created_at=chunk_data.get("created_at")
            )
            self.knowledge_base[chunk.id] = chunk


class GEOKnowledgeBuilder:
    """
    GEO知识库构建器
    
    帮助构建符合ERE框架的知识库
    """
    
    def __init__(self, rag_engine: RAGEngine):
        self.rag_engine = rag_engine
        
    def add_entity(self, name: str, definition: str, attributes: Dict = None):
        """添加实体"""
        content = f"{name}是{definition}"
        if attributes:
            for key, value in attributes.items():
                content += f"，其{key}为{value}"
        content += "。"
        
        return self.rag_engine.add_document(
            content=content,
            source=f"entity:{name}",
            doc_type="entity",
            metadata={"entity_name": name, "attributes": attributes or {}}
        )
    
    def add_relation(self, entity1: str, relation_type: str, entity2: str, 
                     description: str = None):
        """添加关系"""
        content = f"{entity1}{relation_type}{entity2}"
        if description:
            content += f"，具体表现为{description}"
        content += "。"
        
        return self.rag_engine.add_document(
            content=content,
            source=f"relation:{entity1}-{entity2}",
            doc_type="relation",
            metadata={
                "entity1": entity1,
                "relation_type": relation_type,
                "entity2": entity2
            }
        )
    
    def add_evidence(self, claim: str, evidence: str, source: str, 
                     evidence_type: str = "data"):
        """添加证据"""
        content = f"{claim}。根据{source}的{evidence_type}显示，{evidence}"
        
        return self.rag_engine.add_document(
            content=content,
            source=source,
            doc_type="evidence",
            metadata={
                "claim": claim,
                "evidence_type": evidence_type,
                "source": source
            }
        )
    
    def query_for_article(self, topic: str) -> Dict:
        """
        为文章生成查询相关知识
        
        Args:
            topic: 文章主题
            
        Returns:
            包含实体、关系、证据的字典
        """
        # 查询实体
        entity_results = self.rag_engine.search(
            topic, 
            top_k=5, 
            filters={"chunk_type": "entity"}
        )
        
        # 查询关系
        relation_results = self.rag_engine.search(
            topic,
            top_k=5,
            filters={"chunk_type": "relation"}
        )
        
        # 查询证据
        evidence_results = self.rag_engine.search(
            topic,
            top_k=5,
            filters={"chunk_type": "evidence"}
        )
        
        return {
            "entities": [r.chunk.content for r in entity_results],
            "relations": [r.chunk.content for r in relation_results],
            "evidence": [r.chunk.content for r in evidence_results],
            "sources": list(set(
                r.chunk.source for r in 
                entity_results + relation_results + evidence_results
            ))
        }


if __name__ == "__main__":
    # 示例用法
    engine = RAGEngine()
    builder = GEOKnowledgeBuilder(engine)
    
    # 添加知识
    builder.add_entity(
        name="GEO",
        definition="生成式引擎优化（Generative Engine Optimization）",
        attributes={
            "全称": "Generative Engine Optimization",
            "提出时间": "2023年",
            "核心目标": "提升AI引用率"
        }
    )
    
    builder.add_relation(
        entity1="GEO",
        relation_type="是",
        entity2="SEO的演进",
        description="从关键词优化转向答案优化"
    )
    
    builder.add_evidence(
        claim="GEO能显著提升品牌可见性",
        evidence="实施GEO策略的企业AI引用率平均提升40%",
        source="Princeton GEO Research 2024",
        evidence_type="研究数据"
    )
    
    # 查询知识
    knowledge = builder.query_for_article("GEO优化")
    print("查询结果：")
    print(f"实体: {len(knowledge['entities'])} 个")
    print(f"关系: {len(knowledge['relations'])} 个")
    print(f"证据: {len(knowledge['evidence'])} 个")

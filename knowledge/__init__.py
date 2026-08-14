"""은행 에이전트 Knowledge Layer.

온톨로지(ontology/*.ttl)와 인스턴스(examples/*.ttl)를 로드하여
에이전트가 질의할 수 있는 지식 계층을 제공한다.
"""
from knowledge.kb import BankKnowledgeBase

__all__ = ["BankKnowledgeBase"]

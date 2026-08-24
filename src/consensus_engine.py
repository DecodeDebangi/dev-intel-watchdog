import logging
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from src.feed_ingestion import FeedItem

logger = logging.getLogger("dev-intel-watchdog.consensus_engine")

class ConsensusFeedItem(BaseModel):
    id: str
    title: str
    topic_signature: str
    canonical_url: str
    text: str
    consensus_weight: int = 1
    all_sources: List[str] = Field(default_factory=list)
    published_at: str

class ConsensusDeduplicator:
    """
    Consensus Deduplication Engine: Groups identical news stories and security advisories
    from parallel feeds, calculates ecosystem consensus weight, and outputs canonical items.
    """

    def deduplicate(self, raw_items: List[FeedItem]) -> List[ConsensusFeedItem]:
        logger.info(f"Consensus Engine processing {len(raw_items)} raw feed items...")
        
        grouped: Dict[str, Dict[str, Any]] = {}

        for item in raw_items:
            key = item.topic_signature or item.title.lower().strip()

            if key not in grouped:
                grouped[key] = {
                    "canonical_item": item,
                    "sources": [item.source],
                    "weight": 1
                }
            else:
                grouped[key]["weight"] += 1
                if item.source not in grouped[key]["sources"]:
                    grouped[key]["sources"].append(item.source)
                
                # Update canonical item if the new one has longer/more detailed content
                if len(item.text) > len(grouped[key]["canonical_item"].text):
                    grouped[key]["canonical_item"] = item

        canonical_items: List[ConsensusFeedItem] = []
        for key, val in grouped.items():
            item = val["canonical_item"]
            consensus_item = ConsensusFeedItem(
                id=item.id,
                title=item.title,
                topic_signature=key,
                canonical_url=item.url,
                text=item.text,
                consensus_weight=val["weight"],
                all_sources=val["sources"],
                published_at=item.published_at
            )
            canonical_items.append(consensus_item)

        logger.info(f"Consensus Engine deduplicated items down to {len(canonical_items)} unique canonical reports.")
        return canonical_items

def consensus_deduplicate(raw_items: List[FeedItem]) -> List[ConsensusFeedItem]:
    engine = ConsensusDeduplicator()
    return engine.deduplicate(raw_items)

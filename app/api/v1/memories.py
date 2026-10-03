"""
Long-Term Memories API Router.
Endpoints for inspecting, semantically searching, and deleting long-term conversational memories.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_database
from app.models.memory import LongTermMemory
from app.schemas.memory import MemoryResponse, MemorySearchRequest, MemoryCreate
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/memories", tags=["Long-Term Memories"])


@router.get("", response_model=List[MemoryResponse])
def list_memories(
    limit: int = Query(default=50, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
    db: Session = Depends(get_database)
):
    """List eligible active long-term memories."""
    return db.query(LongTermMemory).filter(
        LongTermMemory.is_active.is_(True),
        LongTermMemory.is_false_trigger.is_(False)
    ).order_by(LongTermMemory.created_at.desc()).offset(skip).limit(limit).all()


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
def create_memory(
    req: MemoryCreate,
    db: Session = Depends(get_database)
):
    """Stores a new long-term memory with embedding and optional provenance links."""
    return MemoryService.add_memory(
        db=db,
        content=req.content,
        session_id=req.session_id,
        message_id=req.message_id
    )


@router.post("/search", response_model=List[MemoryResponse])
def search_memories(
    req: MemorySearchRequest,
    db: Session = Depends(get_database)
):
    """Semantically search long-term memories using vector similarity."""
    return MemoryService.search_memories(db=db, query=req.query, limit=req.limit)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: int, db: Session = Depends(get_database)):
    """Permanently delete a long-term memory record."""
    success = MemoryService.delete_memory(db=db, memory_id=memory_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return None

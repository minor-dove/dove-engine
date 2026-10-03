"""
Task Service: CRUD operations and state transitions for user tasks.
"""

from typing import List, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.task import TaskItem
from app.schemas.task import TaskCreate, TaskUpdate


class TaskService:
    @staticmethod
    def create_task(db: Session, task_in: TaskCreate) -> TaskItem:
        task = TaskItem(
            title=task_in.title.strip(),
            description=task_in.description.strip() if task_in.description else None,
            due_date=task_in.due_date,
            status="pending",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def get_task(db: Session, task_id: int) -> Optional[TaskItem]:
        return db.query(TaskItem).filter(TaskItem.id == task_id).first()

    @staticmethod
    def list_tasks(
        db: Session,
        status: Optional[str] = None,
        limit: int = 50,
        skip: int = 0
    ) -> List[TaskItem]:
        query = db.query(TaskItem)
        if status:
            query = query.filter(TaskItem.status == status)
        return query.order_by(TaskItem.due_date.asc().nulls_last(), desc(TaskItem.created_at)).offset(skip).limit(limit).all()

    @staticmethod
    def update_task(db: Session, task_id: int, task_in: TaskUpdate) -> Optional[TaskItem]:
        task = TaskService.get_task(db, task_id)
        if not task:
            return None

        if task_in.title is not None:
            task.title = task_in.title.strip()
        if task_in.description is not None:
            task.description = task_in.description.strip() if task_in.description else None
        if task_in.status is not None:
            task.status = task_in.status.lower()
        if task_in.due_date is not None:
            task.due_date = task_in.due_date

        task.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def delete_task(db: Session, task_id: int) -> bool:
        task = TaskService.get_task(db, task_id)
        if not task:
            return False
        db.delete(task)
        db.commit()
        return True

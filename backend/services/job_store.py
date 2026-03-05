import asyncio
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Job:
    job_id: str
    status: str = "pending"  # pending | generating_code | validating_code | rendering | complete | error
    code: Optional[str] = None
    video_path: Optional[str] = None
    error: Optional[str] = None
    attempt: int = 0
    sse_queue: asyncio.Queue = field(default_factory=asyncio.Queue)


_jobs: dict[str, Job] = {}


def create_job(job_id: str) -> Job:
    job = Job(job_id=job_id)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[Job]:
    return _jobs.get(job_id)


def delete_job(job_id: str) -> None:
    _jobs.pop(job_id, None)

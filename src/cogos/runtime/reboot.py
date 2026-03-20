"""Reboot: re-apply image, increment epoch, log operation, re-create init."""

from __future__ import annotations

import logging
from pathlib import Path

from cogos.db.models import ALL_EPOCHS, Process, ProcessMode, ProcessStatus
from cogos.db.models.operation import CogosOperation

logger = logging.getLogger(__name__)

INIT_PROCESS_CONTENT = "@{mnt/boot/cogos/init.py}"

# Standard image locations (cogtainer: /app/images/cogos, local dev: ./images/cogos)
_IMAGE_SEARCH_PATHS = [
    Path("/app/images/cogos"),
    Path("images/cogos"),
]


def _find_image_dir() -> Path | None:
    for p in _IMAGE_SEARCH_PATHS:
        if p.is_dir():
            return p
    return None


def reboot(repo) -> dict:
    """Re-apply image, increment epoch, create fresh init process.

    Re-applies the image from the bundled images/ directory so FileStore
    picks up the latest code. Old processes stay in previous epochs.
    """

    # 1. Re-apply image to update FileStore with current code
    image_counts = {}
    image_dir = _find_image_dir()
    if image_dir:
        from cogos.image.apply import apply_image
        from cogos.image.spec import load_image

        spec = load_image(image_dir)
        image_counts = apply_image(spec, repo)
        logger.info("Image re-applied: %s", image_counts)

    # 2. Find and disable init (cascade disables children)
    init = repo.get_process_by_name("init")
    if init:
        repo.update_process_status(init.id, ProcessStatus.DISABLED)

    # 3. Count current-epoch processes for reporting
    all_procs = repo.list_processes(epoch=ALL_EPOCHS)
    prev_count = len(all_procs)

    # 4. Increment epoch
    new_epoch = repo.increment_epoch()

    # 5. Log operation
    repo.add_operation(CogosOperation(
        epoch=new_epoch,
        type="reboot",
        metadata={"prev_process_count": prev_count, "image": image_counts},
    ))

    # 6. Create fresh init process in the new epoch
    init_proc = Process(
        name="init",
        mode=ProcessMode.DAEMON,
        content=INIT_PROCESS_CONTENT,
        executor="python",
        priority=200.0,
        runner="lambda",
        status=ProcessStatus.RUNNABLE,
        epoch=new_epoch,
    )
    repo.upsert_process(init_proc)

    logger.info("Reboot complete: epoch=%d, prev_processes=%d", new_epoch, prev_count)
    return {"cleared_processes": prev_count, "epoch": new_epoch}

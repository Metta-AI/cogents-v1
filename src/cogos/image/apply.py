"""Apply an ImageSpec to a CogOS repository."""

from __future__ import annotations

import json
import logging

from cogos.db.models import (
    Capability,
    Channel,
    ChannelType,
    Cron,
    Handler,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
    Resource,
    ResourceType,
    Schema,
)
from cogos.files.store import FileStore
from cogos.image.spec import ImageSpec

logger = logging.getLogger(__name__)


def apply_image(spec: ImageSpec, repo, *, clean: bool = False) -> dict[str, int]:
    """Apply an image spec to the database. Returns counts of entities created/updated."""
    counts = {
        "capabilities": 0, "resources": 0, "files": 0, "processes": 0,
        "cron": 0, "schemas": 0, "channels": 0,
    }

    # 1. Capabilities
    for cap_dict in spec.capabilities:
        cap = Capability(
            name=cap_dict["name"],
            handler=cap_dict["handler"],
            description=cap_dict.get("description", ""),
            instructions=cap_dict.get("instructions", ""),
            schema=cap_dict.get("schema") or {},
            iam_role_arn=cap_dict.get("iam_role_arn"),
            metadata=cap_dict.get("metadata") or {},
        )
        repo.upsert_capability(cap)
        counts["capabilities"] += 1

    # 2. Resources (skip if no table/method yet)
    if hasattr(repo, "upsert_resource"):
        for res_dict in spec.resources:
            r = Resource(
                name=res_dict["name"],
                resource_type=ResourceType(res_dict.get("resource_type", res_dict.get("type", "pool"))),
                capacity=float(res_dict.get("capacity", 1.0)),
                metadata=res_dict.get("metadata") or {},
            )
            repo.upsert_resource(r)
            counts["resources"] += 1
    elif spec.resources:
        logger.warning("Skipping %d resources — upsert_resource not implemented", len(spec.resources))

    # 3. Cron rules (skip if no table/method yet)
    if hasattr(repo, "upsert_cron"):
        for cron_dict in spec.cron_rules:
            channel_name = cron_dict.get("channel_name") or cron_dict.get("event_type")
            if not channel_name:
                raise ValueError("cron rule missing channel_name")
            c = Cron(
                expression=cron_dict["expression"],
                channel_name=channel_name,
                payload=cron_dict.get("payload") or {},
                enabled=cron_dict.get("enabled", True),
            )
            repo.upsert_cron(c)
            counts["cron"] += 1
    elif spec.cron_rules:
        logger.warning("Skipping %d cron rules — upsert_cron not implemented", len(spec.cron_rules))

    # 4. Files
    fs = FileStore(repo)
    for key, content in spec.files.items():
        fs.upsert(key, content, source="image")
        counts["files"] += 1

    # 5. Schemas
    for schema_dict in spec.schemas:
        file_id = None
        if schema_dict.get("file_key"):
            f = repo.get_file_by_key(schema_dict["file_key"])
            if f:
                file_id = f.id
        s = Schema(
            name=schema_dict["name"],
            definition=schema_dict.get("definition", {}),
            file_id=file_id,
        )
        repo.upsert_schema(s)
        counts["schemas"] += 1

    # 6. Channels
    for ch_dict in spec.channels:
        schema_id = None
        if ch_dict.get("schema"):
            s = repo.get_schema_by_name(ch_dict["schema"])
            if s:
                schema_id = s.id
        ch = Channel(
            name=ch_dict["name"],
            schema_id=schema_id,
            channel_type=ChannelType(ch_dict.get("channel_type", "named")),
            auto_close=ch_dict.get("auto_close", False),
        )
        repo.upsert_channel(ch)
        counts["channels"] += 1

    # 7. Processes (with capability bindings and handlers)
    for proc_dict in spec.processes:
        mode = ProcessMode(proc_dict.get("mode", "one_shot"))
        p = Process(
            name=proc_dict["name"],
            mode=mode,
            content=proc_dict.get("content", ""),
            runner=proc_dict.get("runner", "lambda"),
            executor=proc_dict.get("executor", "llm"),
            model=proc_dict.get("model"),
            priority=float(proc_dict.get("priority", 0.0)),
            status=ProcessStatus.WAITING if mode == ProcessMode.DAEMON else ProcessStatus.RUNNABLE,
            metadata=proc_dict.get("metadata") or {},
            idle_timeout_ms=proc_dict.get("idle_timeout_ms"),
        )
        pid = repo.upsert_process(p)

        # Bind capabilities
        for cap_entry in proc_dict.get("capabilities", []):
            if isinstance(cap_entry, dict):
                cap_name = cap_entry["name"]
                cap_config = cap_entry.get("config")
                cap_alias = cap_entry.get("alias", cap_name)
            else:
                cap_name = cap_entry
                cap_config = None
                cap_alias = cap_name
            cap = repo.get_capability_by_name(cap_name)
            if cap:
                pc = ProcessCapability(
                    process=pid, capability=cap.id,
                    name=cap_alias, config=cap_config,
                )
                repo.create_process_capability(pc)

        # Create handlers — channel-based
        for ch_name in proc_dict.get("handlers", []):
            ch = repo.get_channel_by_name(ch_name)
            if ch is None:
                ch = Channel(
                    name=ch_name,
                    channel_type=ChannelType.NAMED,
                )
                repo.upsert_channel(ch)
                ch = repo.get_channel_by_name(ch_name)
            h = Handler(process=pid, channel=ch.id, enabled=True)
            repo.create_handler(h)

        counts["processes"] += 1

    # 8. Coglets
    from cogos.coglet import CogletMeta, write_file_tree
    from cogos.capabilities.coglet_factory import _load_meta, _save_meta
    counts["coglets"] = 0
    for coglet_dict in spec.coglets:
        name = coglet_dict["name"]
        test_command = coglet_dict["test_command"]
        files = coglet_dict["files"]
        executor = coglet_dict.get("executor", "subprocess")
        timeout_seconds = coglet_dict.get("timeout_seconds", 60)

        # Check if coglet with this name already exists by scanning meta files
        existing_metas = fs.list_files(prefix="coglets/", limit=1000)
        existing_id = None
        for mf in existing_metas:
            if mf.key.endswith("/meta.json"):
                content = fs.get_content(mf.key)
                if content:
                    try:
                        m = CogletMeta(**json.loads(content))
                        if m.name == name:
                            existing_id = m.id
                            break
                    except Exception:
                        pass

        if existing_id:
            meta = _load_meta(fs, existing_id)
            write_file_tree(fs, existing_id, "main", files)
            meta.test_command = test_command
            meta.executor = executor
            meta.timeout_seconds = timeout_seconds
            _save_meta(fs, meta)
        else:
            meta = CogletMeta(name=name, test_command=test_command, executor=executor, timeout_seconds=timeout_seconds)
            write_file_tree(fs, meta.id, "main", files)
            _save_meta(fs, meta)

        counts["coglets"] += 1

    # 9. Disable stale top-level processes not in this image
    image_process_names = {p["name"] for p in spec.processes}
    all_procs = repo.list_processes(limit=500)
    stale_count = 0
    for proc in all_procs:
        if proc.name in image_process_names:
            continue
        if proc.parent_process is not None:
            continue  # spawned child — not managed by image boot
        if proc.status in (ProcessStatus.DISABLED, ProcessStatus.COMPLETED):
            continue
        logger.info("Disabling stale process %s (not in image)", proc.name)
        repo.update_process_status(proc.id, ProcessStatus.DISABLED)
        stale_count += 1
    counts["stale_disabled"] = stale_count

    # Record image boot timestamp
    if hasattr(repo, "set_meta"):
        repo.set_meta("image:booted_at")

    return counts

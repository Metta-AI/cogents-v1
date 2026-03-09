# Capabilities Dashboard Redesign

## Goal

Replace the read-only capabilities table with a rich panel that shows/edits IO schemas and displays which processes are granted each capability.

## Layout

Mirrors ToolsPanel pattern:
- **Left sidebar**: HierarchyPanel folder tree from hierarchical capability names (`files/read` → `files/` folder)
- **Main area**: Table of capabilities in selected group (Name, Description, Enabled badge). Double-click to expand.
- **Detail panel**: Inline below table showing full capability info with edit support.

## Detail Panel Sections

1. **Header**: Full name (mono), enabled badge, Edit / Disable buttons
2. **Description**: Text block (editable)
3. **Instructions**: Text block (editable)
4. **Handler**: Mono, read-only
5. **IAM Role**: Mono, read-only, shown only if present
6. **Input Schema**: Collapsible JSON editor with validation (editable)
7. **Output Schema**: Collapsible JSON editor with validation (editable)
8. **Granted Processes**: Read-only list of process name + status badge + delegatable flag

## Edit Mode

Edit button switches description, instructions, input_schema, output_schema to editable. Schemas use textarea with JSON validation — Save disabled on invalid JSON with red error. Handler, IAM role, granted processes stay read-only.

## Backend Changes

### Repository
- Add `list_processes_for_capability(capability_id)` to both `repository.py` and `local_repository.py`
- Returns process + process_capability join data

### Dashboard API (`capabilities.py`)
- Add `GET /capabilities/{cap_name}/processes` returning `[{process_id, process_name, process_status, delegatable, config}]`

## Frontend Changes

### Types (`types.ts`)
- Expand `CogosCapability` with: instructions, input_schema, output_schema, iam_role_arn, metadata, created_at, updated_at

### API (`api.ts`)
- `updateCapability(cogentName, capName, updates)` — PUT
- `getCapabilityProcesses(cogentName, capName)` — GET new endpoint

### Component (`CapabilitiesPanel.tsx`)
- Full rewrite using HierarchyPanel + table + inline detail panel
- Edit mode for description, instructions, schemas
- Granted processes display

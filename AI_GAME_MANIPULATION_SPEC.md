# AI Game Manipulation Specification (Integration Phase)

Date: February 23, 2026

## Purpose
Define what the AI is allowed to manipulate in-game and the expected behaviors. This is a planning/spec document only. No implementation is included here.

## Scope (High-Level)
The AI may **read** state and **request** actions through a controlled command layer. It must not directly mutate scene objects outside the approved actions below.

Approved manipulation categories:
- Camera control
- Component selection + highlighting
- Scene switching (helicopter / cockpit / engine)
- UI mode transitions (model ↔ chat)
- Exploded view controls
- UI panel visibility and focus
- Model rotation control
- Theme and visual presets (optional)
- Manual/knowledge window switching (optional)

## Core In-Game Actions (Planned)
Each action represents an atomic operation. The AI will call these via a command router (to be implemented later).

### 1) Camera Manipulation
**Actions**
- `camera.orbit({ yaw, pitch })`
- `camera.pan({ x, y })`
- `camera.zoom({ delta })`
- `camera.focus({ targetName, distance, durationMs })`
- `camera.reset({ durationMs })`
- `camera.autoRotate({ enabled })`

**Behavior Requirements**
- Camera actions must be bounded by min/max limits defined in config.
- `camera.focus` should smoothly interpolate and preserve the current orbit target if the mesh is found.
- If `targetName` is not found, return a graceful failure and do not move the camera.

### 2) Highlighting & Selection
**Actions**
- `model.select({ targetName })`
- `model.highlight({ targetName, color, intensity, durationMs })`
- `model.clearHighlight({ targetName })`
- `model.clearAllHighlights()`

**Behavior Requirements**
- Selection should trigger the standard selection pipeline (info panel, highlight color, optional camera focus).
- Highlights should be layered so that temporary highlights do not overwrite a selected highlight permanently.

### 3) Scene Switching
**Actions**
- `scene.switch({ sceneId })` where `sceneId` ∈ `helicopter | cockpit | engine`

**Behavior Requirements**
- Preserve global UI state across scenes unless explicitly changed.
- If the target scene is already active, return a no-op success.

### 4) Exploded View
**Actions**
- `model.explode({ enabled, distance, speed })`

**Behavior Requirements**
- Must respect configured limits for distance and speed.
- If scene does not support explosion, return a failure with reason.

### 5) UI Mode Transitions
**Actions**
- `ui.mode({ mode })` where `mode` ∈ `model | chat`

**Behavior Requirements**
- Use the existing transition phases (shrinking → moving → chat, or expanding → model).
- Queue the command if a transition is already in progress.

### 6) UI Panel Control
**Actions**
- `ui.panel({ panelId, visible })` where `panelId` ∈ `subModelList | configMenu | healthReport | componentInfo | manualViewer | chatWindow`
- `ui.focus({ panelId })`

**Behavior Requirements**
- `ui.focus` brings panel to front and optionally highlights its border for 1–2 seconds.
- Respect global UI hub visibility; if the hub is hidden, do not show panels unless explicitly allowed.

### 7) Manual Viewer / Window Switching (Optional)
**Actions**
- `manual.open({ docId, page })`
- `manual.search({ query })`
- `manual.close()`

**Behavior Requirements**
- The AI should open manuals only on explicit user intent.
- Page navigation must clamp to valid ranges.

### 8) Visual Presets (Optional)
**Actions**
- `theme.set({ themeId })`
- `ui.visualPreset({ presetId })`

**Behavior Requirements**
- Theme changes should be reversible and logged.

## State Read Access (Planned)
The AI may read (not mutate) these states:
- Current scene id
- Current selected component
- Active highlights (list)
- Camera position/target
- UI mode (model/chat)
- Exploded view status
- Visible panels
- Theme id

## Command Routing (Planned)
A centralized command router should validate commands, enforce limits, and emit structured results.

**Result Shape**
- `status`: `success | failure | noop`
- `message`: user-friendly summary
- `data`: optional structured payload

## Safety & Constraints
- All actions must be bounded and validated.
- Commands must be idempotent where possible.
- The AI should never bypass safety checks or manipulate raw scene objects directly.

## Existing Reference Points (Implementation Targets Later)
- Scene switching: ChangeViews
- Camera + selection: HelicopterScene
- Chat commands: ChatWindow / mockAiService
- UI state: App
- Config limits: config

## Non-Goals (Out of Scope)
- Direct physics manipulation
- File system modifications from AI
- Persistent state changes without explicit user approval

---
Prepared for implementation phase. No code changes required yet.

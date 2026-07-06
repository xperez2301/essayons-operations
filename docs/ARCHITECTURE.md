# EOMS Architecture

## Logistics Operating System

## Core Vision

EOMS is a Logistics Operating System that unifies operations, automation, and intelligence into a single governed platform for managing, executing, and continuously improving logistics.

## Major Pillars

- Operations Engine
- Automation Kernel
- Intelligence Engine
- Shared Platform
- Security Layer

## Operations Engine

The Operations Engine contains the business workflows that run the logistics operation. This layer owns operational business logic, business state transitions, and user-facing workflows.

Core Operations Engine domains include:

- RMS Integration
- Dispatch Center
- Route Builder
- Warehouse Command
- Fleet Operations
- GPS7000 Integration
- Driver Portal
- Customer Portal
- Inventory
- Cross Dock
- Proof of Delivery
- Billing
- Reporting

Business record changes belong in Operations modules. Automation may request, validate, or route work, but business workflow ownership remains in the Operations Engine.

## Automation Kernel

The Automation Kernel is the governed automation pipeline for EOMS. It creates, stores, validates, authorizes, and executes automation work without bypassing policy or operator control.

Official automation pipeline:

```text
Scheduler
-> Queue
-> Policy Engine
-> Execution Controller
-> Executor
-> Workers
```

- Scheduler creates work.
- Queue stores work.
- Policy Engine defines what is allowed.
- Execution Controller decides whether a queued job may run now.
- Executor manages lifecycle and invokes workers only after authorization.
- Workers perform approved operations.

The Automation Kernel does not own business workflows. It governs automation execution and delegates approved business actions to the appropriate worker or Operations module.

## Job Lifecycle

Standard job states:

- CREATED
- QUEUED
- VALIDATING
- AUTHORIZED
- RUNNING
- COMPLETED
- BLOCKED
- FAILED
- CANCELLED future/reserved

Normal path:

```text
CREATED -> QUEUED -> VALIDATING -> AUTHORIZED -> RUNNING -> COMPLETED
```

Blocked path:

```text
VALIDATING -> BLOCKED
```

Failure path:

```text
RUNNING -> FAILED
```

The Queue owns job lifecycle state. The Execution Controller decides whether a queued job is allowed to proceed. The Executor performs lifecycle transitions during authorized execution.

## Automation Safety Rules

- Automation never bypasses policy.
- Approval-required jobs do not execute automatically.
- Blocked jobs never execute.
- Unknown job types are not automatic.
- Kill switch stops execution.
- Retry limits prevent endless loops.
- Duplicate running jobs are rejected.
- Business record changes belong in Operations modules, not the Automation Kernel.

## Intelligence Engine

The Intelligence Engine provides AI-assisted recommendations, analysis, detection, and decision support. AI recommends but does not directly execute.

AI recommendations must become governed automation jobs before anything operational happens.

AI-governed path:

```text
AI Recommendation
-> Automation Job
-> Policy Engine
-> Execution Controller
-> Executor
-> Worker
```

This preserves human governance and keeps AI inside the same automation safety model as every other automation source.

## Shared Platform

The Shared Platform provides reusable services used across Operations, Automation, Intelligence, and Security.

Shared services include:

- Authentication
- Users
- Roles
- Permissions
- Notifications
- Audit Logs
- Configuration
- Storage
- Search
- API
- File Management
- GPS Services
- Maps
- Document Services

Shared services should be reused before creating new services or duplicate systems.

## Security Layer

The Security Layer protects EOMS users, operational data, production workflows, and automation boundaries.

Security responsibilities include:

- Authentication
- Authorization
- Policy enforcement
- Audit trail
- Data protection
- Recovery
- Production protection

Security applies across every EOMS layer. Automation, AI, and operations all remain subject to authentication, authorization, auditability, and production safeguards.

## Core Principles

- One System
- Layered Architecture
- Automation Never Bypasses Policy
- Business Logic Lives in Operations
- AI Recommends, Humans Govern
- Observable by Design
- Reusable Before New
- Protect Production
- Modular Growth
- Operator Comes First

## Roadmap Alignment

- EOMS 2.0 Automation Kernel
- EOMS 3.0 Logistics Execution
- EOMS 4.0 Enterprise Platform
- EOMS 5.0 Intelligence Engine

## Current Architecture Status

- FT1 RMS Integration complete
- FT2 Command Center complete
- FT3 Automation Platform in progress
- FT3.5.4.1 Policy Engine complete
- FT3.5.4.2 Execution Controller complete
- FT3.5.4.3 Executor Integration pending

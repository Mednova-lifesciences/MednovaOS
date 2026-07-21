# MedNovaOS CRM Implementation Brief

## Project Overview

Build a native CRM module inside MedNovaOS, designed as the internal business development workspace for MedNova Lifesciences. This CRM must feel like a first-class part of MedNovaOS rather than a standalone product. Companies discovered through Regulatory Intelligence should flow directly into CRM records without duplication. The CRM should read directly from existing MedNovaOS data, reuse the current authentication model, and adopt the same design language, navigation, colors, typography, spacing, and component patterns already used in the platform.

## Product Vision

MedNovaOS is evolving from a regulatory intelligence and opportunity discovery platform into a unified operating system for commercial and regulatory growth. The CRM is the central workspace where users manage companies after discovering them through Green Book research, regulatory intelligence reporting, and opportunity analysis. It should support the full business development lifecycle from company discovery to relationship management, outreach, task tracking, proposals, and commercial outcomes.

## Core Workflow

Green Book
↓
Generate Regulatory Intelligence Report
↓
Add to CRM
↓
Company appears inside CRM
↓
Business Development manages the relationship
↓
Emails
↓
Meetings
↓
Tasks
↓
Proposal
↓
Client

## Product Principles

- Integrate directly with existing MedNovaOS data and workflows.
- Avoid duplicate data entry; use existing company and product records as the source of truth.
- Preserve the current MedNovaOS experience and visual language.
- Feel like premium enterprise software, similar to HubSpot, Salesforce, Zoho CRM, or Microsoft Dynamics.
- Prioritize speed, clarity, and professional business workflows.
- Be responsive, modern, and suitable for internal teams.

## Primary Modules

Build the following modules as part of the CRM:

- Dashboard
- Companies
- Company Profile
- Contacts
- Activities
- Tasks
- Notes
- Deals / Pipeline
- Emails
- Reports
- Settings

## Navigation and Integration

- Add a CRM entry point in the main MedNovaOS navigation alongside existing modules.
- Ensure CRM pages support active-state highlighting and responsive behavior.
- Reuse the existing MedNovaOS header, typography, cards, tables, buttons, spacing, and color system.
- Do not redesign the rest of MedNovaOS; make the CRM feel like it has always been part of the application.
- Use shared routing conventions and preserve current navigation behavior.

## Data Model Expectations

The CRM should work from existing MedNovaOS entities and optionally create CRM-specific records that link back to them.

### Company Records

Each company should be represented as a CRM company record linked to the existing company/product intelligence data. The CRM should support:

- Company name
- Industry / therapeutic focus
- Country
- Website
- Status
- Opportunity score
- Portfolio summary
- Source of discovery
- Linked regulatory intelligence report
- Related products
- Related contacts
- Related activities and tasks

### Contacts

Initially support manual creation and later integration. Each contact should include:

- Name
- Position
- Department
- Email
- Phone
- LinkedIn
- Notes

### Activities

Support records such as:

- Calls
- Emails
- Meetings
- Follow-ups
- Notes
- Proposal milestones

### Tasks

Allow users to create:

- Calls
- Meetings
- Follow-ups
- Deadlines
- Proposal reminders

### Pipeline / Deals

Support deal stages:

- Lead
- Qualified
- Contacted
- Meeting Scheduled
- Proposal Sent
- Negotiation
- Won
- Lost

## CRM Dashboard

The CRM dashboard should present a premium enterprise overview with summary cards and a clean layout. Include KPI tiles for:

- Companies added
- Leads
- Active opportunities
- Won clients
- Tasks due
- Meetings scheduled
- Pipeline value

## Companies Module

The Companies module should be the main list view where users can browse discovered companies and manage their lifecycle. Each row should show:

- Company name
- Country
- Opportunity score
- Status
- Portfolio summary
- Last activity
- Next follow-up

## Company Profile

Every company page should include a comprehensive profile with the following sections:

- Company Information
- Generated Regulatory Intelligence Report
- Opportunity Score
- Portfolio Summary
- Contacts
- Activities
- Tasks
- Notes
- Emails
- Meeting History
- Files
- Timeline

The profile should be designed like an executive client workspace and should support both summary and detail views.

## Regulatory Intelligence Integration

The CRM must integrate directly with the Regulatory Intelligence module. When a company is added from Opportunities:

- the CRM should receive the company context
- the company should appear in CRM immediately
- the generated report should remain accessible inside the company profile
- opportunity score and portfolio summary should be visible in the company view

## Email Module

The CRM should support AI-assisted email generation using company data, opportunity score, regulatory report, portfolio detail, and past activity. The system should:

- draft personalized outreach emails
- store generated emails in the CRM
- allow users to review, edit, and send them

## Notes and Timeline

The CRM should include a timeline or activity feed showing:

- reports generated
- emails sent
- calls logged
- tasks created
- meetings scheduled
- notes added

## Reports Module

Build reports and analytics views with metrics such as:

- Companies added
- Leads
- Active opportunities
- Won clients
- Tasks due
- Meetings scheduled
- Pipeline value

## UI Requirements

The CRM should feel like premium enterprise software and should integrate naturally into the existing MedNovaOS experience.

### Visual Direction

- Clean white background
- polished cards
- strong spacing
- professional typography
- tables and drawers
- status badges
- activity feed
- responsive layout
- dark/light compatibility if already supported

### Interaction Design

- Use modals and drawers for detail views
- Use clear hierarchy and consistent spacing
- Keep interactions simple and fast
- Avoid creating a disconnected “standalone app” feel
- Preserve the current MedNovaOS design language and user experience

## Technical Guidance

- Use a modern frontend architecture suitable for rapid development.
- Reuse existing MedNovaOS components whenever possible.
- Keep the implementation maintainable and modular.
- Respect the current authentication model and routing conventions.
- Make the CRM feel like it has always belonged to MedNovaOS.

## Deliverable

Create a fully integrated MedNovaOS CRM module that acts as the central workspace for companies discovered through Regulatory Intelligence, with strong support for business development workflows, reporting, activities, tasks, contacts, and pipeline management.

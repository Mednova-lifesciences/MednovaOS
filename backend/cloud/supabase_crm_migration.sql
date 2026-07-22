-- Supabase CRM migration: create CRM tables if they do not exist
-- Run this in the Supabase SQL editor or via psql connected to your Supabase DB.

create table if not exists public.crm_companies (
  id bigint primary key,
  company_name text not null,
  country text,
  opportunity_score integer default 0,
  portfolio_summary text,
  source text,
  report_context text,
  greenbook_products_json text,
  registration_numbers text,
  dosage_forms text,
  therapeutic_areas text,
  registration_dates text,
  opportunity_status text default 'New',
  pipeline_stage text default 'Lead',
  created_at text,
  updated_at text,
  constraint crm_companies_company_name_unique unique (company_name)
);

create table if not exists public.crm_activities (
  id bigint primary key,
  crm_company_id bigint not null,
  activity_type text not null,
  title text not null,
  body text,
  created_at text,
  constraint fk_activity_company foreign key (crm_company_id) references public.crm_companies(id) on delete cascade
);

create table if not exists public.crm_notes (
  id bigint primary key,
  crm_company_id bigint not null,
  body text not null,
  created_at text,
  constraint fk_note_company foreign key (crm_company_id) references public.crm_companies(id) on delete cascade
);

create table if not exists public.crm_contacts (
  id bigint primary key,
  crm_company_id bigint not null,
  full_name text not null,
  role text,
  department text,
  email text,
  phone text,
  source text,
  created_at text,
  updated_at text,
  source_url text,
  discovered_at text,
  confidence_score real,
  verification_status text,
  website text,
  linkedin_url text,
  notes text,
  constraint fk_contact_company foreign key (crm_company_id) references public.crm_companies(id) on delete cascade
);

create table if not exists public.crm_tasks (
  id bigint primary key,
  crm_company_id bigint not null,
  title text not null,
  description text,
  task_type text default 'follow-up',
  status text default 'pending',
  priority text default 'medium',
  due_date text,
  assigned_to text,
  completed_at text,
  created_at text,
  updated_at text,
  constraint fk_task_company foreign key (crm_company_id) references public.crm_companies(id) on delete cascade
);

create table if not exists public.crm_deals (
  id bigint primary key,
  crm_company_id bigint not null,
  crm_contact_id bigint,
  title text not null,
  stage text default 'lead',
  value numeric default 0,
  currency text default 'USD',
  probability integer default 0,
  expected_close_at text,
  owner text,
  description text,
  created_at text,
  updated_at text,
  constraint fk_deal_company foreign key (crm_company_id) references public.crm_companies(id) on delete cascade
);

create table if not exists public.crm_outreach_emails (
  id bigint primary key,
  crm_company_id bigint not null,
  crm_contact_id bigint,
  template_key text,
  template_name text,
  subject text not null,
  body text not null,
  recipient text,
  recipient_name text,
  sender_name text,
  sender_email text,
  from_email text,
  company_name text,
  contact_name text,
  status text default 'draft',
  direction text default 'outbound',
  message_id text,
  error_message text,
  client_request_id text,
  created_at text,
  updated_at text,
  sent_at text,
  constraint fk_outreach_company foreign key (crm_company_id) references public.crm_companies(id) on delete cascade
);

-- Indexes
create index if not exists idx_crm_contacts_company_id on public.crm_contacts(crm_company_id);
create index if not exists idx_crm_tasks_company_id on public.crm_tasks(crm_company_id);
create index if not exists idx_crm_tasks_status on public.crm_tasks(status);
create index if not exists idx_crm_tasks_due_date on public.crm_tasks(due_date);
create index if not exists idx_crm_activities_company_id on public.crm_activities(crm_company_id);
create index if not exists idx_crm_notes_company_id on public.crm_notes(crm_company_id);
create index if not exists idx_crm_deals_company_id on public.crm_deals(crm_company_id);
create index if not exists idx_crm_deals_stage on public.crm_deals(stage);
create index if not exists idx_crm_deals_owner on public.crm_deals(owner);
create index if not exists idx_crm_outreach_company on public.crm_outreach_emails(crm_company_id);
create index if not exists idx_crm_outreach_status on public.crm_outreach_emails(status);
create index if not exists idx_crm_outreach_created on public.crm_outreach_emails(created_at);

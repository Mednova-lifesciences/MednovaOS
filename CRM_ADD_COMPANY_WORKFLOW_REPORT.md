# CRM add-company workflow report

## Root cause
The opportunity-to-CRM flow was already reaching the backend endpoint, but the experience was incomplete in two places:

1. The UI was only showing a generic success state after the backend returned a result, without using the backend's created/existing response to differentiate new insertions from duplicates.
2. The CRM landing route was redirecting away from the built-in CRM page, which made the newly created company less visible in the expected flow and caused the route-level regression test to fail.

The actual database write path was already working. The company was being inserted into the CRM table and returned by the API.

## Files modified
- [app.py](app.py)
  - Expanded the add-to-CRM API response with richer state (`created`, `exists`, `status`, company payload).
  - Kept the CRM company persistence path intact while making the response immediately useful to the UI.
  - Restored the `/crm` route to render the CRM page directly for the current app experience.
- [templates/opportunities.html](templates/opportunities.html)
  - Replaced the generic success behavior with a richer inline toast experience.
  - Added support for duplicate-company messaging and a direct CRM action.
  - Kept the UI within the existing MedNovaOS design system and page structure.
- [static/styles.css](static/styles.css)
  - Added toast styling for the success/duplicate notification.
- [tests/test_company_workflow.py](tests/test_company_workflow.py)
  - Added regression coverage for duplicate-company handling.

## Workflow before
1. User clicked the opportunity action.
2. The frontend sent a request to the backend endpoint.
3. The backend inserted or reused the CRM company record.
4. The UI only showed a generic success message and did not clearly distinguish between a newly created company and an existing company.
5. The CRM landing experience was not aligned with the local page flow.

## Workflow after
1. User clicks Add Opportunity to CRM.
2. The frontend POSTs to the backend endpoint.
3. The backend writes the company to the CRM table and returns a response that clearly indicates whether the company was created or already existed.
4. The page shows a polished confirmation toast that:
   - animates into view
   - remains visible for about 7 seconds
   - supports manual dismissal
   - offers an Open CRM action
5. If the company already exists, the UI shows a duplicate-aware message instead of creating another record.
6. The CRM route remains available directly so the newly created company is visible in the CRM experience after the workflow completes.

## Verification results
Verified with:
- `./.venv/Scripts/python.exe -m pytest -q tests/test_company_workflow.py tests/test_opportunities.py`
- Result: 3 passed in 6.04s

## Remaining edge cases
- The current CRM experience still uses the existing page structure and does not yet add richer per-company routing from the toast to a specific company profile.
- The toast uses the same CRM landing page for navigation; if a deeper company-profile route is introduced later, the Open CRM action can be pointed there with the returned company ID.

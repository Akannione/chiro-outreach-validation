# AlignDeskApp 48-Hour MVP Demo

This is a static validation demo for a chiropractic documentation workflow. It is not the final product.

## Goal

Show a clinic owner or staff member a concrete workflow:

1. Pick a common chiropractic visit type.
2. Enter exam details.
3. Generate a structured SOAP-style note.
4. Copy a plain-text EHR-ready output.
5. Capture the clinic's reaction and willingness to pay.

## Run

Open this file in a browser:

```text
demo/aligndesk_mvp/index.html
```

No server or package install is required.

## What To Test With Clinics

- Does the generated note match how they document care?
- Would this save real time during or after visits?
- Which note templates matter most?
- Would they pay $50-$100/month if this worked with their current EHR workflow?
- Is copy/paste enough for v1, or is integration required before they care?

## MVP Boundary

Included:

- Chiropractic-specific templates
- SOAP note generation
- EHR copy output
- Follow-up task list
- Local demo feedback capture

Excluded:

- User accounts
- Patient storage
- EHR integrations
- Billing
- Scheduling
- Real clinical decision support


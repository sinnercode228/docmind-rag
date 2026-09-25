# Information Security Policy

> Fictional policy of Lumenfold Labs, written for the DocMind demo.

## Accounts and passwords

All company accounts use single sign-on (SSO) with multi-factor authentication. Hardware security keys are mandatory for administrators and for anyone with production access; everyone else may use an authenticator app.

Passwords for systems outside SSO must be at least 14 characters long and stored in the company password manager. Passwords are never shared in chat, email or tickets. Rotation is only required after a suspected compromise.

## Devices

Company laptops must have full-disk encryption enabled, automatic screen lock after 5 minutes, and the latest operating system updates installed within 14 days of release. Personal devices may access email and chat through the mobile apps only; source code and customer data must never be stored on them.

A lost or stolen device must be reported to the security team within one hour, so it can be locked and wiped remotely.

## Data classification

We use three data classes:

- **Public**: marketing pages, published documentation.
- **Internal**: plans, internal wikis, most documents. Shared only inside the company.
- **Confidential**: customer data, credentials, financial and personnel records. Access is granted per project and reviewed every quarter.

Confidential data may only be processed in approved systems. Exporting it to spreadsheets or personal storage requires a written approval from the data owner.

## Reporting incidents

Report any suspected security incident — phishing, a leaked secret, unusual account activity — in the #security-incidents channel or by email to the security team. Do not investigate on your own and do not delete evidence. Reporting quickly is always the right call, even if it turns out to be a false alarm.

## Access reviews

Team leads review who has access to their systems every quarter. Access is removed on the last working day when someone leaves the company.

# ShuttleScope Content Policy
## Version 1.0 — Effective 2026-05-08

---

## 1. Purpose and Scope

This Content Policy describes how ShuttleScope (the "Software" or "Service")
treats content submitted by Users, how third parties may report content they
believe violates their rights, and the response procedure that ShuttleScope's
developer (the "developer") follows after receiving such a report. It is
intended to make the developer's posture as a generally available analysis
tool transparent and to satisfy the operational expectations of:

- the United States Digital Millennium Copyright Act, 17 U.S.C. § 512
  ("DMCA");
- Article 14 of Directive 2000/31/EC on electronic commerce (the "EU
  e-Commerce Directive") and the corresponding provisions of Regulation
  (EU) 2022/2065 (the "Digital Services Act") as they apply to hosting
  services;
- Articles 30 and 47-bis of the Japanese Copyright Act, including the
  information-analysis exception under Article 30-4 / Article 47-5; and
- comparable national legislation in jurisdictions where the Service is
  used.

This Policy supplements and is incorporated by reference into
`TERMS_OF_SERVICE.md`. In the event of a conflict between this Policy and
the Terms of Service, the Terms of Service prevail with respect to
contractual matters.

---

## 2. Hosting Posture

ShuttleScope operates as a **generally available video analysis tool**. The
developer does not pre-screen, curate, or otherwise editorially select User
Content before it is processed by the Service.

In particular:

- the developer does not assert a position on the lawfulness of any
  particular User Content prior to receiving a notice or a credible report
  to the contrary;
- video lawfully accessible to a User through paid streaming subscriptions,
  broadcast licensing, or other lawful means may be processed through the
  Service in the same manner as video the User has personally recorded;
- the responsibility for ensuring that any submitted content is being
  processed within the User's lawful rights rests with the User as set forth
  in `TERMS_OF_SERVICE.md` Section 4 and Section 16;
- the developer's Service-level role is to operate the analysis pipeline,
  store the resulting artifacts, and respond to verified reports of
  infringement or other content-related complaints.

This posture is consistent with the legal framework recognized for
general-purpose tools in Japanese case law (Supreme Court, 19 December 2011)
and with the safe-harbor regimes for hosting services under the DMCA and
the EU e-Commerce Directive.

---

## 3. User Responsibilities

By submitting content to the Service, a User represents that they have
sufficient legal basis to do so, including without limitation any rights
required to record, copy, transmit, store, or analyze the content. The User
also represents that the manner in which they intend to use the Service's
output is consistent with the rights they hold.

ShuttleScope does not offer guidance on whether a particular content
submission is lawful in the User's specific circumstances, and does not act
as an arbiter of competing rights claims. Where a User is in doubt, the
User should consult their own legal advisor before submission.

---

## 4. Content Categories Always Prohibited

Notwithstanding the passive posture described in Section 2, the following
categories of content are prohibited at all times and may be removed by
the developer on becoming aware of them, without the need for a third-party
notice:

- content that is unlawful per se in the jurisdictions where the Service
  is operated (e.g., child sexual abuse material, content depicting
  imminent threats to identifiable persons);
- content that depicts personal data of identified individuals where the
  manifest absence of any plausible lawful basis is apparent on the face
  of the submission;
- content that the developer has been ordered to remove by a court of
  competent jurisdiction or by a binding regulatory directive.

For all other categories, the procedure in Section 6 applies.

---

## 5. Reporting Channels

A right-holder, regulator, data subject, or other interested party may
submit a content-related report through any of the following channels:

- the public contact form at `https://shuttle-scope.com/contact`;
- electronic mail to `contact@shuttle-scope.com`;
- a private GitHub Security Advisory at the repository linked in
  `SECURITY.md` (preferred for technical-attack reports; usable for
  content reports as well).

A report should include the elements described in Section 6 below to
enable triage. Reports that omit those elements may still be received,
acknowledged, and processed where the missing information can be
reasonably reconstructed.

---

## 6. Notice Format

A complete notice contains, where applicable:

- the identification of the work or material claimed to be infringed or
  otherwise to be the subject of the complaint;
- the location within the Service of the material that is the subject of
  the report (account identifier, match identifier, public link, or
  comparable locator);
- the contact details of the complainant (name or organizational name,
  postal address, telephone number, electronic mail address);
- a statement that the complainant has a good-faith belief that the use
  of the material in the manner complained of is not authorized by the
  rights holder, the rights holder's agent, or the law (where the report
  invokes a copyright basis, this corresponds to 17 U.S.C. § 512(c)(3)
  and equivalent national provisions);
- a statement, made under penalty of perjury where applicable, that the
  information in the notice is accurate and that the complainant is
  authorized to act on behalf of the rights holder;
- the physical or electronic signature of the complainant.

This format mirrors 17 U.S.C. § 512(c)(3). Reports based on data
protection rather than copyright (e.g., GDPR Article 17 erasure requests
or APPI Article 30 deletion requests) are routed through the same channels
and addressed under the procedures described in `PRIVACY.md` Article VIII.

---

## 7. Response Procedure

Upon receipt of a notice, the developer follows the procedure below.

| Step | Activity | Target Timeline |
|---|---|---|
| 7.1 Receipt | Acknowledge receipt to the complainant where contact details are present. | 1 business day |
| 7.2 Initial review | Confirm that the report contains the elements in Section 6 and the indicated material exists within the Service. | 5 business days |
| 7.3 Determination | Determine whether the report is upheld, rejected, or requires further information. | within the same 5 business days where feasible |
| 7.4 Action | Where upheld, remove or restrict access to the material; where rejected, communicate the basis to the complainant. | 14 days from receipt |
| 7.5 User notification | Where action is taken in respect of User Content, notify the affected User to the extent permitted by applicable law and by the proper conduct of any related proceeding. | following Step 7.4 |
| 7.6 Counter-notice | Receive and process a counter-notice from the affected User in accordance with Section 8. | as set forth in Section 8 |
| 7.7 Recordkeeping | Retain the notice, response, and any subsequent counter-notice and resolution for at least three (3) years. | ongoing |

The developer reserves the right to extend any of the timelines above by a
reasonable period where the volume or complexity of a report makes the
default timeline impracticable, and shall communicate any such extension
to the complainant.

---

## 8. Counter-Notice Procedure

A User affected by a removal may submit a counter-notice through any of
the channels in Section 5. A counter-notice should include:

- identification of the material that was removed and the location at
  which it appeared;
- a statement under penalty of perjury where applicable that the User has
  a good-faith belief the material was removed as a result of mistake or
  misidentification;
- the User's contact details;
- the User's signature.

This format mirrors 17 U.S.C. § 512(g)(3). Where a valid counter-notice
is received and the original complainant does not commence a legal action
within fourteen (14) business days of being notified, the developer may
restore the affected material.

---

## 9. Designated Agent (Future)

At the time the Service is offered to Users in or directed to the United
States on a sustained commercial basis, the developer intends to register
a designated agent with the United States Copyright Office under 17
U.S.C. § 512(c)(2). Until such registration is in effect, notices may be
submitted through the channels in Section 5 above and shall be received
and processed under the procedure in Section 7.

---

## 10. Recordkeeping and Reporting

The developer retains records of received reports, response actions, and
related communications for the period set forth in Section 7. Aggregate
statistics on the volume and disposition of reports may be published from
time to time in service of accountability and transparency, but the
contents of individual reports are treated as confidential except to the
extent disclosure is required by law or by the proper conduct of a legal
proceeding.

---

## 11. Changes to this Policy

This Policy may be updated from time to time. Material changes will be
communicated through the Service or through other reasonable means.
Continued use of the Service after the effective date of a revised Policy
constitutes acceptance of the revision in respect of subsequent Service
use.

---

## 12. Order of Precedence

Where this Policy conflicts with `TERMS_OF_SERVICE.md`, the Terms of
Service prevail with respect to contractual matters. Where this Policy
conflicts with applicable law, the law prevails.

---

*This Policy is a baseline document. It does not constitute legal advice
and does not create rights in favor of any party other than as expressly
stated herein. Right-holders contemplating litigation, regulators
contemplating enforcement action, or users contemplating a counter-notice
should consult independent legal counsel.*

# Supplemental Terms for the Optional Consent to AI / Machine-Learning Use of Submitted Materials

## Version 1.0 — Effective 2026-05-18

## 0. Summary of Operative Effect

This instrument is the consent vehicle by which the Participant authorises
Operator, and authorised recipients acting under written agreement with
Operator, to use Participant-Submitted Materials for the development,
evaluation, refinement, productisation, commercial exploitation, scholarly
investigation, and onward provision of ShuttleScope and of artificial-
intelligence or machine-learning models, sub-models, adapters, embeddings,
statistical artefacts, and other computational representations associated
with the Service, whether now existing or hereafter devised.

For clarity, trained model weights, fine-tuned checkpoints, distilled or
quantised derivatives, evaluation harness outputs, and anonymised,
aggregated, perturbed, or otherwise non-identifying statistical derivatives
of the Submitted Materials shall not be subject to any obligation of
deletion, recall, unlearning, or invalidation upon subsequent withdrawal
of consent. This limitation is necessary because the selective extraction
or surgical excision of the contribution of any single Participant from a
trained machine-learning artefact is, at the present state of the art,
technically and economically infeasible at any non-trivial scale. Imposing
a per-withdrawal retraining obligation on Operator would render continued
operation of the Service commercially unsustainable and would materially
impair the athletic-performance, research, and service-improvement
purposes for which the Service exists.

Following withdrawal, Operator will cease using the Participant's
non-anonymised Submitted Materials for new training or evaluation
activities to the extent reasonably practicable, but withdrawal shall not
affect models, artefacts, outputs, analyses, or derivatives already
created, committed to, or made available before the withdrawal becomes
effective, except where mandatory law requires otherwise.

The detailed terms that follow give legal effect to the foregoing summary.
In the event of any apparent inconsistency between this Section 0 and the
detailed terms, the detailed terms control.

## 1. Relationship to Other Instruments

These Supplemental Terms (the **"AI Terms"**) operate in conjunction
with, and not in derogation of, (a) the ShuttleScope Terms of Service
(the **"ToS"**) as amended from time to time, (b) the Privacy Notice
(the **"Privacy Notice"**), (c) the Data Contribution Terms, (d) the
participant consent instrument used at the time of enrolment, and
(e) any Data Processing Agreement entered into between the Developer
and a controller, processor, sub-processor, or onward recipient of the
Submitted Materials defined below (each, an **"Instrument"** and
collectively the **"Governing Instruments"**). In the event of any
inconsistency between these AI Terms and any other Governing
Instrument, the more permissive construction in favour of the
Developer's continuing right to perform the Permitted Activities
(defined in §3) shall prevail to the maximum extent permitted by
applicable mandatory law, including but not limited to GDPR Articles
5(1)(b), 6(1)(a), 9(2)(a) where applicable, 22, and 89; APPI
Articles 17, 18, 27, 28; and any analogous successor provisions or
jurisdictional equivalents (collectively, **"Mandatory Law"**).

The Reader, by giving the optional consent designated "AI training" in
the onboarding flow or in the Settings page, becomes a **"Consenting
Party"** for the purposes of these AI Terms and is deemed to have
acknowledged each numbered section below in its entirety, without any
requirement of separate initialling.

## 2. Defined Terms

Capitalised terms used and not otherwise defined herein bear the
following meanings:

(a) **"Submitted Materials"** means, without limitation, every datum,
record, frame, derived feature, latent representation, embedding,
descriptor, label, annotation, statistic, metadata element, model
hyperparameter, gradient, loss curve, telemetry record, log line,
checkpoint, fine-tuning artefact, evaluation harness output, prompt,
response, retrieval index, vector, token sequence, attention map,
saliency map, or any combination, aggregation, distillation,
quantisation, projection, transformation, summarisation, mixture,
ensemble member, adapter, low-rank decomposition, LoRA weight, prefix,
prompt-template, system message, ranking score, calibration table, or
post-processing artefact that is created, derived, computed, inferred,
indexed, cached, or otherwise materialised in whole or in part from any
input that the Consenting Party (or any other person whose data the
Consenting Party has lawful authority to submit) contributes to the
Service, whether such contribution occurs before or after the
acceptance of these AI Terms.

(b) **"Permitted Activities"** means each and every act listed in §3
below, taken in any combination, sequence, modality, or jurisdiction,
whether performed manually, automatically, on-device, on the
Developer's premises, on third-party infrastructure, in federated
configurations, in homomorphically-encrypted or trusted-execution
environments, or by Sub-Recipients (defined below).

(c) **"Derived Models"** means any artificial intelligence,
machine-learning, statistical, heuristic, symbolic, hybrid, or any
other computational artefact whose internal state has been informed,
directly or indirectly, in whole or in any non-trivial part, by the
Submitted Materials; including without limitation foundation models,
fine-tuned models, distilled student models, LoRA / DoRA / IA3
adapters, embeddings tables, retrieval-augmented generation indices,
mixture-of-experts routing tables, calibration models, anomaly
detectors, ranking models, and any model whose parameters were
initialised from any of the foregoing.

(d) **"Sub-Recipients"** means any natural or legal person, partnership,
research consortium, academic institution, professional sports
organisation, governmental body, cloud-services provider, model-hosting
platform, contracted reviewer, vendor, agent, contractor,
sub-contractor, joint venturer, successor, assignee, or affiliate of
the Developer to which the Developer transmits, transfers, licenses,
sub-licenses, makes available, or grants access to Submitted Materials
or to Derived Models trained thereon, provided that any such transfer
that constitutes a "cross-border transfer of personal data" within the
meaning of GDPR Articles 44-49 or APPI Article 28 shall additionally be
subject to (i) Standard Contractual Clauses or equivalent transfer
safeguards, or (ii) reliance on an adequacy decision (including,
without limitation, the European Commission adequacy decision in
respect of Japan dated 23 January 2019 as the same may be amended,
suspended, or replaced), or (iii) any successor or supplementary
safeguard that is, in the Developer's reasonable judgment, lawful at
the time of transfer.

(e) **"Permitted Purposes"** means each of the purposes enumerated in
§4, recognising that several purposes may apply contemporaneously and
that the enumeration is exemplary and not exhaustive.

(f) **"Anonymised Outputs"** means any product, artefact, score,
indicator, embedding, or other derivative of the Submitted Materials
which the Developer has, in the Developer's reasonable engineering
judgment, processed such that (i) it cannot be reasonably re-attributed
to the Consenting Party using means reasonably likely to be used by the
Developer or any Sub-Recipient, and (ii) the marginal cost of
re-identification exceeds the marginal expected benefit of
re-identification, irrespective of whether re-identification remains
theoretically achievable by an adversary possessing auxiliary data not
in the Developer's possession.

(g) **"Withdrawal"** means a withdrawal of the consent given under
these AI Terms in the manner prescribed by §10, and **"Withdrawal
Effective Date"** means the date determined under §10.4.

## 3. Permitted Activities — Scope of Grant

The Consenting Party grants to the Developer, and to each Sub-Recipient
in respect of which the Developer has effected an onward transfer
consistent with §2(d), a worldwide, non-exclusive, royalty-free,
fully-paid-up, sub-licensable, transferable licence (the **"Licence"**)
to do each and all of the following acts with respect to the Submitted
Materials and Derived Models:

(a) reproduction, in any form and medium, including ephemeral,
transient, in-memory, and durably-stored reproductions;

(b) preparation of derivative works of any nature, including the
training, pre-training, continued pre-training, fine-tuning, supervised
fine-tuning, reinforcement-learning fine-tuning (including with human,
AI, or hybrid feedback), preference optimisation, direct preference
optimisation, identity preference optimisation, contrastive
optimisation, distillation (white-box, grey-box, and black-box),
quantisation (including but not limited to integer-N, mixed-precision,
and weight-only schemes), pruning, sparsification, sharding,
parallelisation, knowledge graph construction, retrieval index
generation, embedding extraction, latent factor decomposition, and any
other operation customary in the machine-learning arts as practised at
the time of execution or as may hereafter be developed;

(c) public performance, public display, and communication to the
public, in each case to the extent reasonably necessary to evaluate,
demonstrate, market, publish, present, or otherwise exhibit Derived
Models or aggregated outputs thereof, provided that no Submitted
Material reasonably identifiable to the Consenting Party shall be
exhibited verbatim without the Consenting Party's separate consent
unless such exhibition constitutes an Anonymised Output;

(d) translation, transcoding, format conversion, codec transformation,
spatial and temporal resampling, colour-space conversion, sample-rate
conversion, and any technical operation incident to (a)-(c);

(e) sub-licensing, in whole or in part, to any Sub-Recipient on terms
no less protective of the Consenting Party than the corresponding
provisions of these AI Terms; provided that the Developer remains
responsible for the acts and omissions of such Sub-Recipients as if
they were the acts and omissions of the Developer for purposes of any
liability that the Developer would otherwise bear under the Governing
Instruments;

(f) commercial exploitation of Derived Models, including but not
limited to sale, licensing, software-as-a-service offering,
inference-as-a-service offering, embedded deployment, on-device
deployment, edge deployment, federated deployment, and any monetisation
model (subscription, usage-based, advertising-supported, freemium, or
otherwise) that is or becomes commercially customary;

(g) retention, indefinitely, of (i) any Anonymised Outputs, and (ii)
any Derived Models, and (iii) audit, lineage, provenance, watermarking,
and reproducibility artefacts reasonably necessary to evidence
compliance with applicable law or to defend against allegations of
non-compliance;

(h) use of the Submitted Materials and Derived Models in any combination
with any other lawfully-obtained data, including data of third parties
whose data has been collected under separate legal bases, provided that
such combination does not (in the Developer's reasonable judgment)
result in re-identification of the Consenting Party in a manner
prohibited by Mandatory Law;

(i) inclusion of the Submitted Materials and Derived Models in
benchmarks, evaluation suites, scientific publications, technical
reports, blog posts, conference presentations, academic papers, patent
applications (where novel and non-obvious technical features are
disclosed), and other communications of an academic, technical, or
educational nature, subject in each case to the anonymisation
obligations in §3(c); and

(j) any other use that is (i) reasonably ancillary to any of the
foregoing, (ii) reasonably necessary for the Developer to operate,
maintain, secure, defend, comply, audit, account for, or improve any
of the foregoing, or (iii) reasonably foreseeable from any of the
foregoing in light of customary practice in the artificial-intelligence
and machine-learning industry as that practice evolves over time.

## 4. Permitted Purposes — Indicative, Non-Exhaustive

The Licence in §3 is granted for the following Permitted Purposes,
which the Consenting Party acknowledges are illustrative and which the
Developer may, in the Developer's reasonable discretion, supplement
from time to time provided that any such supplemental purpose is
within the reasonable contemplation of these AI Terms read as a whole:

(a) the improvement of any aspect of the Service, including but not
limited to shot classification, court calibration, shuttle tracking,
pose estimation, condition analysis, expected-point-value estimation,
and any further analytic feature whether stable, advanced, or research
tier;

(b) the development, training, evaluation, refinement, distillation,
and deployment of artificial-intelligence and machine-learning models
of any architecture (including but not limited to convolutional,
recurrent, transformer, state-space, mixture-of-experts, retrieval-
augmented, and any hybrid thereof) and of any size or compute regime;

(c) the licensing or sale of Derived Models to third parties, including
to badminton federations, broadcasters, sports analytics companies,
academic researchers, and to the general public via inference APIs or
model-distribution platforms;

(d) academic research and publication, subject to anonymisation
obligations and, where reasonably practicable, to advance disclosure to
the Consenting Party of the intended publication venue;

(e) the production, training, evaluation, and improvement of
foundation models that are not specific to badminton, including
general-purpose vision, video, and multimodal models, for which the
Submitted Materials constitute a small but non-trivial training
contribution; and

(f) such further purposes as the Developer may, from time to time,
reasonably determine to be in furtherance of the development,
maintenance, improvement, or commercial exploitation of the Service or
of any Derived Models, including without limitation the use of the
Submitted Materials and Derived Models in connection with any merger,
acquisition, divestiture, reorganisation, asset sale, financing, or
similar corporate transaction.

## 5. Anonymisation, De-Identification, and Aggregation

(a) The Developer shall employ technical and organisational measures
that are, in the Developer's reasonable engineering judgment,
appropriate to the state of the art at the time of processing to
produce Anonymised Outputs from the Submitted Materials. Such measures
may include, without limitation, k-anonymity-style generalisation,
l-diversity, t-closeness, differential privacy (with any reasonable
choice of epsilon and delta parameters consistent with utility), random
or systematic perturbation, suppression, noise addition, and federated
aggregation.

(b) The Consenting Party acknowledges that anonymisation is a
spectrum, not a binary state, and that no anonymisation technique is
absolutely robust against all possible adversaries; the Consenting
Party further acknowledges that the Developer's anonymisation
obligations are obligations of means rather than of result, and that
no failure of anonymisation by an adversary in possession of
auxiliary data not in the Developer's possession shall constitute a
breach of these AI Terms.

(c) Anonymised Outputs, once produced, are deemed to fall outside the
scope of the Consenting Party's personal data and may be retained and
used by the Developer and by any Sub-Recipient without further
restriction, including after the Withdrawal Effective Date.

## 6. Retention and Provenance

(a) The Submitted Materials, in their non-anonymised form, may be
retained for the duration of the Consenting Party's participation in
the Service and for a reasonable period thereafter sufficient to (i)
respond to lawful access, deletion, and rectification requests, (ii)
defend against legal claims, (iii) comply with statutory record-
retention obligations, and (iv) perform reproducibility, audit, and
lineage operations on Derived Models.

(b) Derived Models, including those trained in whole or in part on
Submitted Materials, may be retained indefinitely. The Consenting Party
acknowledges that, given the architectural characteristics of modern
machine-learning models, the Developer cannot practicably extract or
"un-learn" the contribution of any particular individual's Submitted
Materials from a Derived Model once training has completed, and the
Consenting Party therefore agrees that no Withdrawal under §10 shall
oblige the Developer to perform such extraction or un-learning.

## 7. Audit, Logging, and Watermarking

The Developer may, at its discretion, watermark, fingerprint, or
otherwise mark Derived Models, model outputs, embeddings, and other
artefacts derived from the Submitted Materials, for the purposes of
provenance, anti-leak detection, attribution disputes, and lawful
audit. Such marking, where applied to Anonymised Outputs, shall be
applied in a manner that does not re-introduce identifiability.

## 8. Sub-Recipients and Onward Transfers

The Developer may, without further consent from the Consenting Party,
transfer Submitted Materials or Derived Models to Sub-Recipients,
provided that the Developer:

(a) imposes on each Sub-Recipient contractual obligations consistent
with these AI Terms;

(b) where the transfer is a cross-border transfer of personal data,
complies with the safeguards described in §2(d); and

(c) remains responsible for the acts and omissions of such
Sub-Recipients as set out in §3(e).

The Consenting Party expressly acknowledges that the Developer is not
required to obtain incremental consent for each onward transfer or
each new Sub-Recipient.

## 9. No Compensation; No Royalty

The Licence is granted on a royalty-free, fully-paid-up basis. The
Consenting Party acknowledges that the consideration for the grant of
the Licence includes the Consenting Party's continued access to the
Service and the right to benefit from improvements to the Service that
result, directly or indirectly, from the Permitted Activities. No
further consideration shall be payable by the Developer to the
Consenting Party in respect of the Permitted Activities, the Derived
Models, the commercial exploitation thereof, or otherwise.

## 10. Withdrawal of Consent

(a) The Consenting Party may, at any time, withdraw the consent given
under these AI Terms by toggling the relevant control in the
ShuttleScope Settings page (Condition tab, Body composition disclosure
section, or wherever subsequently relocated), by sending a written
notice to `contact@shuttle-scope.com`, or by such other reasonable
means as the Developer may from time to time make available.

(b) Withdrawal shall not affect (i) the lawfulness of any processing
performed in reliance on the consent prior to the Withdrawal Effective
Date, (ii) the rights granted to Sub-Recipients prior to the
Withdrawal Effective Date, (iii) the right of the Developer to retain
and use Anonymised Outputs and Derived Models as set out in §5(c) and
§6(b), or (iv) any other right or remedy of the Developer that has
accrued prior to the Withdrawal Effective Date.

(c) Following Withdrawal, the Developer shall, within a reasonable
period and to the extent practicable having regard to the
considerations set out in §6(b), cease to use the Submitted Materials,
in their non-anonymised form, for the Permitted Activities. The
Developer shall not be required to delete Derived Models or Anonymised
Outputs.

(d) The **Withdrawal Effective Date** shall be the later of (i) the
date on which the Developer's systems first record the Withdrawal in a
durable form, and (ii) any later date that the Developer reasonably
determines is necessary to permit the orderly cessation of relevant
processing, the propagation of the Withdrawal to Sub-Recipients, and
the maintenance of audit and reproducibility records.

## 11. Severability and Construction

If any provision of these AI Terms is held by a court of competent
jurisdiction to be invalid, illegal, or unenforceable, that provision
shall be enforced to the maximum extent permitted by law to give effect
to the parties' intent, and the remaining provisions shall continue in
full force and effect. Headings are for convenience only and shall not
affect construction. The expression "including" is to be read as
"including, without limitation".

## 12. Governing Law and Dispute Resolution

These AI Terms shall be governed by, and construed in accordance with,
the law specified in the ToS for the governing law of the ToS, and
disputes shall be resolved in accordance with the dispute-resolution
provisions of the ToS, mutatis mutandis.

## 13. Entire Agreement on the Subject

These AI Terms, together with the Governing Instruments, constitute
the entire understanding of the parties with respect to the subject
matter hereof and supersede all prior or contemporaneous oral or
written communications, representations, or understandings on that
subject matter.

---

*End of Supplemental Terms for AI / Machine-Learning Use.*
